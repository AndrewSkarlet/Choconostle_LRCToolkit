"""
run.py

Ejecución en dos pasadas de normalize-lyrics y convert-lyrics, pensada para bibliotecas
grandes en tarjetas SD.

1. Planificación: se recorre la biblioteca carpeta por carpeta y cada
   cambio se escribe en plan.jsonl (en disco, no en memoria), con los
   hashes del original y del resultado y las diferencias para el
   registro.
2. Aplicación: se lee plan.jsonl y se aplica cada entrada. Antes de
   escribir se comprueba que el original no cambió y que el resultado
   recalculado es exactamente el planeado.

Carpeta de una ejecución (<biblioteca>/ChoconostleLRCTool_back/<fecha-hora>/):

    estado.json    fase, opciones, totales y espacio necesario
    plan.jsonl     una línea por archivo de letra o de audio; termina con {"type": "end"}
    diario.jsonl   eventos con fsync: "intent" antes de escribir, "done" después
    originales/    copia de cada .lrc/.txt modificado y parches de las incrustadas
    pendiente/     diario de escritura byte a byte (rawtags.writer)
    registro.txt   registro legible, escrito a medida que avanza

Pasos de cada entrada (una interrupción en cualquiera se resuelve con
--resume o revert):

    1. copia de respaldo (fsync)   2. evento "intent" (fsync)
    3. escritura                    4. verificación     5. evento "done" (fsync)

Autor: AndrewSkarlet
Licencia: MIT
"""

from __future__ import annotations

import errno
import glob
import json
import os
import re
import shutil
import stat
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from choconostle.config import APP_NAME, APP_VERSION, BACKUP_DIR_NAME
from choconostle.embedded import open_editor
from choconostle.rawtags import MODE_FULL, Unsupported, apply_patches, patches_to_json, sha256
from choconostle.rawtags.ogg import OggEditor
from choconostle.rawtags.writer import (
    TEMP_SUFFIX, VERIFY_AUTO, VERIFY_FULL, ChangedError, Journal, RestoreError, WriteError, file_sha256,
    effective_verify, file_signature, read_at, recover, rewrite_with, write_edit,
)
from choconostle.scanner import iter_folders
from choconostle.textio import diff_lines
from choconostle.utils import format_size, fsync_file, long_path, plural, write_file_atomic

FORMAT = 3
STATE_NAME = "estado.json"
PLAN_NAME = "plan.jsonl"
DIARY_NAME = "diario.jsonl"
LOG_NAME = "registro.txt"
ORIGINALS_DIR = "originales"

STATE_PLANNING = "planning"
STATE_PLANNED = "planned"
STATE_APPLYING = "applying"
STATE_INTERRUPTED = "interrupted"
STATE_COMPLETED = "completed"
STATE_NAMES = {
    STATE_PLANNING: "planificando (no terminó)",
    STATE_PLANNED: "planificada, sin aplicar",
    STATE_APPLYING: "aplicando (no terminó)",
    STATE_INTERRUPTED: "interrumpida",
    STATE_COMPLETED: "completada",
}

APPLIED = "applied"
FAILED = "failed"

# Margen de espacio libre además del estimado.
SPACE_MARGIN = 16 * 1024 * 1024

# Errores que detienen toda la ejecución (no solo el archivo actual).
_SPACE_ERRNOS = {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)}
_DEVICE_ERRNOS = {errno.EIO, errno.ENODEV, errno.ENXIO, getattr(errno, "ESTALE", errno.EIO),
                  errno.EROFS, getattr(errno, "ENOMEDIUM", errno.ENODEV)}
_SPACE_WINERRORS = {39, 112}  # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL
# Errores de Windows (OSError.winerror) que indican que la unidad se fue.
# Un acceso denegado (5) NO está aquí: es un fallo de ese archivo.
DEVICE_WINERRORS = {
    15: "ERROR_INVALID_DRIVE",           # la letra de unidad ya no existe
    21: "ERROR_NOT_READY",
    55: "ERROR_DEV_NOT_EXIST",
    121: "ERROR_SEM_TIMEOUT",            # la unidad dejó de responder
    483: "ERROR_DEVICE_HARDWARE_ERROR",
    1117: "ERROR_IO_DEVICE",
    1128: "ERROR_DEVICE_REMOVED",
    1167: "ERROR_DEVICE_NOT_CONNECTED",
}


def _progress_call(progress, method: str, *args) -> None:
    """Llama a un método del indicador de progreso si existe (es opcional)."""
    function = getattr(progress, method, None) if progress is not None else None
    if function is not None:
        function(*args)


def checkpoint(step: str, record: dict) -> None:
    """Punto entre pasos del diario (las pruebas lo usan para simular cortes)."""


class StopRun(Exception):
    """La ejecución se detiene: sin espacio, unidad desconectada o interrupción."""

    def __init__(self, kind: str, message: str):
        self.kind = kind
        super().__init__(message)


class ResumeError(Exception):
    """--resume no puede continuar con seguridad."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def _rel(path: Path, root: Path) -> str:
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return str(path)


def write_json_atomic(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with open(long_path(temporary), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2))
        fsync_file(handle)
    os.replace(long_path(temporary), long_path(path))


def _open_jsonl(path: Path, mode: str):
    """
    Abre un archivo del respaldo para leerlo, o None si no existe.

    No se usa Path.exists(): en Windows, con la tarjeta SD quitada, devuelve
    False (WinError 21, 3...) en vez de fallar, y el diario se leía como
    vacío («Aplicadas 0»). Aquí, si el archivo no aparece y tampoco su
    carpeta, el error se propaga como el de una unidad desconectada.
    """
    kwargs = {"encoding": "utf-8"} if "b" not in mode else {}
    try:
        return open(long_path(path), mode, **kwargs)
    except FileNotFoundError:
        try:
            if stat.S_ISDIR(os.stat(long_path(Path(path).parent)).st_mode):
                return None  # la carpeta está: el archivo simplemente no existe
        except FileNotFoundError:
            pass
        raise


def iter_jsonl(path: Path):
    """
    Líneas JSON de un archivo. Una línea a medias (corte de luz o unidad
    desconectada mientras se escribía) se ignora: lo que no llegó entero
    al disco no cuenta como confirmado.
    """
    handle = _open_jsonl(path, "r")
    if handle is None:
        return
    with handle:
        for line in handle:
            if not line.endswith("\n"):
                return
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _jsonl_offsets(path: Path):
    """(posición, evento) de cada línea completa, con las mismas reglas que iter_jsonl."""
    handle = _open_jsonl(path, "rb")
    if handle is None:
        return
    with handle:
        offset = 0
        for line in handle:
            start, offset = offset, offset + len(line)
            if not line.endswith(b"\n"):
                return
            try:
                yield start, json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue


class DiaryEvents(Mapping):
    """Eventos del diario por id, leídos del disco al pedirlos (solo se guardan las posiciones)."""

    def __init__(self, path: Path, offsets: dict[int, int]):
        self._path = path
        self._offsets = offsets

    def __getitem__(self, entry: int) -> dict:
        offset = self._offsets[entry]
        with open(long_path(self._path), "rb") as handle:
            handle.seek(offset)
            return json.loads(handle.readline().decode("utf-8"))

    def __iter__(self):
        return iter(self._offsets)

    def __len__(self) -> int:
        return len(self._offsets)

    def values(self):
        """Todos los eventos en una sola lectura del diario."""
        wanted = {offset for offset in self._offsets.values()}
        for offset, event in _jsonl_offsets(self._path):
            if offset in wanted:
                yield event


def _safe_name(name: str, limit: int = 80) -> str:
    import re
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "letra"
    return name[:limit]


def fatal_kind(exc: BaseException, root: Path, backups: bool = True) -> str | None:
    """
    "space", "device" o None según el error (y si la biblioteca sigue
    accesible). Con backups=False no se exige que exista la carpeta de
    respaldos (fix-gallery en simulación no la crea).
    """
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError):
            winerror = getattr(current, "winerror", None)
            if winerror in _SPACE_WINERRORS or (winerror is None and current.errno in _SPACE_ERRNOS):
                return "space"
            if winerror in DEVICE_WINERRORS or (winerror is None and current.errno in _DEVICE_ERRNOS):
                return "device"
        current = current.__cause__ or current.__context__
    if not reachable(root, backups=backups):
        return "device"
    return None


def reachable(root: Path, backups: bool = True) -> bool:
    """
    True si la biblioteca (y, con backups=True, su carpeta de respaldos)
    sigue accesible. Si desaparece la letra de unidad o el punto de
    montaje de la tarjeta SD, es False.
    """
    # Con os.stat y no os.path.isdir: en Windows isdir es una función en C
    # (nt._path_isdir) y se comporta distinto ante algunos errores; así el
    # criterio es el mismo en Windows, Linux y Android.
    def is_dir(path) -> bool:
        try:
            return stat.S_ISDIR(os.stat(long_path(path)).st_mode)
        except (OSError, ValueError):
            return False
    return is_dir(root) and (not backups or is_dir(Path(root) / BACKUP_DIR_NAME))


# --------------------------------------------------------------------------
# Carpeta de la ejecución
# --------------------------------------------------------------------------

class Run:
    """Una ejecución (planificación + aplicación) guardada en disco."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        path = self.folder / STATE_NAME
        if not path.is_file():
            from choconostle.backup import BackupNotFound, not_found_message
            raise BackupNotFound(not_found_message(self.folder))
        self.state = json.loads(path.read_text(encoding="utf-8"))
        if self.state.get("format") != FORMAT:
            raise ValueError(f"Formato de ejecución desconocido: {self.state.get('format')}")
        self._diary = None
        # Copia en memoria de lo confirmado en el diario ({id: estado}), para
        # el resumen del paro cuando la unidad ya no se puede leer.
        self.confirmed: dict[int, str] = {}

    @classmethod
    def create(cls, root: Path, command: str, options: dict, temporary: bool = False,
               now: datetime | None = None) -> "Run":
        now = now or datetime.now()
        if temporary:
            folder = Path(tempfile.mkdtemp(prefix="choconostle-simulacion-"))
        else:
            base = Path(root) / BACKUP_DIR_NAME
            name = now.strftime("%Y-%m-%d_%H-%M-%S")
            folder = base / name
            counter = 2
            # Tampoco se reutiliza el nombre de una carpeta que se está borrando
            # (clean-backups la renombra a <nombre>.borrando).
            while folder.exists() or any(base.glob(glob.escape(folder.name) + DELETING_SUFFIX + "*")):
                folder = base / f"{name}_{counter}"
                counter += 1
            (folder / ORIGINALS_DIR).mkdir(parents=True)
        state = {
            "app": APP_NAME, "app_version": APP_VERSION, "format": FORMAT, "command": command,
            "created_at": now.isoformat(timespec="seconds"), "root": str(root),
            "options": options, "state": STATE_PLANNING, "temporary": temporary,
        }
        write_json_atomic(folder / STATE_NAME, state)
        return cls(folder)

    # -- estado -----------------------------------------------------------

    @property
    def phase(self) -> str:
        return self.state["state"]

    def save_state(self, **updates) -> None:
        self.state.update(updates)
        self.state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        write_json_atomic(self.folder / STATE_NAME, self.state)

    def library_root(self) -> Path:
        # La ubicación real del respaldo manda: la biblioteca pudo cambiar de
        # ruta (otra letra de unidad, /sdcard...).
        if self.folder.parent.name == BACKUP_DIR_NAME:
            return self.folder.parent.parent
        return Path(self.state["root"])

    # -- plan ----------------------------------------------------------------

    def plan_records(self):
        for record in iter_jsonl(self.folder / PLAN_NAME):
            if record.get("type") != "end":
                yield record

    def legacy_audio_plans(self) -> int:
        """
        Archivos de audio por modificar cuyo plan no tiene huella del audio
        (planes de la rc1): al aplicarlos solo se comparan tamaño, fecha y
        bytes de las etiquetas.
        """
        return sum(1 for record in self.plan_records()
                   if record.get("status") == "change" and record.get("plan")
                   and "audio" not in record["plan"])

    def plan_complete(self) -> bool:
        last = None
        for last in iter_jsonl(self.folder / PLAN_NAME):
            pass
        return bool(last and last.get("type") == "end")

    # -- diario ----------------------------------------------------------------

    def event(self, data: dict) -> None:
        """
        Agrega un evento al diario con fsync. Si la última línea quedó a
        medias (escritura cortada), se termina antes para que el evento
        nuevo no se pegue a ella.
        """
        path = long_path(self.folder / DIARY_NAME)
        with open(path, "a+b") as handle:
            handle.seek(0, os.SEEK_END)
            prefix = b""
            if handle.tell():
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) != b"\n":
                    prefix = b"\n"
                handle.seek(0, os.SEEK_END)
            handle.write(prefix + (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))
            fsync_file(handle)
        if data.get("event") == "done":
            self.confirmed[data["id"]] = data.get("status")

    def events(self):
        yield from iter_jsonl(self.folder / DIARY_NAME)

    def outcome(self) -> tuple[DiaryEvents, DiaryEvents]:
        """
        ({id: evento intent}, {id: evento done}) (el último de cada uno).

        En memoria solo quedan las posiciones de cada evento en el diario;
        el evento se lee del disco cuando se pide (etapa ⑥: con miles de
        entradas, los eventos enteros ocupaban unos 2 KB por entrada).
        """
        path = self.folder / DIARY_NAME
        intents, done = {}, {}
        for offset, event in _jsonl_offsets(path):
            if event.get("event") == "intent":
                intents[event["id"]] = offset
            elif event.get("event") == "done":
                done[event["id"]] = offset
        return DiaryEvents(path, intents), DiaryEvents(path, done)

    def log(self, lines: list[str]) -> None:
        with open(long_path(self.folder / LOG_NAME), "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()

    # -- compatibilidad ----------------------------------------------------

    @property
    def manifest(self) -> dict:
        """Vista resumida tipo manifiesto (items por letra y ediciones por audio)."""
        intents, done = self.outcome()
        items, edits = [], []
        for record in self.plan_records():
            if record["status"] != "change":
                continue
            result = done.get(record["id"])
            status = result["status"] if result else "pending"
            error = result.get("error") if result else None
            if record["type"] == "file":
                items.append({"id": record["item"], "kind": "file", "path": record["path"],
                              "label": record["label"], "status": status, "error": error,
                              "details": record["details"]})
                continue
            changed = [slot for slot in record["slots"] if slot["status"] == "change"]
            for slot in changed:
                items.append({"id": slot["item"], "kind": "embedded", "path": record["path"],
                              "label": slot["label"], "status": status, "error": error,
                              "details": slot["details"], "edit": record["id"]})
            intent = intents.get(record["id"], {})
            edits.append(dict(intent, id=record["id"], path=record["path"], status=status, error=error,
                              items=[slot["item"] for slot in changed]))
        return {"manifest_version": FORMAT, "items": items, "edits": edits, "state": self.phase}


# --------------------------------------------------------------------------
# Registros del plan
# --------------------------------------------------------------------------

def _base_record(change) -> dict:
    return {
        "status": change.status, "label": change.label, "details": list(change.details),
        "warnings": list(change.warnings), "message": change.message, "skip_reason": change.skip_reason,
        "nearly_empty": change.nearly_empty, "unknown": list(change.unknown_headers),
    }


def _jsonable(value):
    if isinstance(value, list):
        return [[text, time] for text, time in value]
    return value


def python_value(value):
    if isinstance(value, list):
        return [(text, time) for text, time in value]
    return value


class RecordBuilder:
    """Convierte LyricsChange en registros del plan, con identificadores."""

    def __init__(self, root: Path, with_diff: bool = True):
        self.root = Path(root)
        self.with_diff = with_diff
        self.next_id = 1
        self.next_item = 1

    def _ids(self) -> tuple[int, int]:
        entry, item = self.next_id, self.next_item
        self.next_id += 1
        self.next_item += 1
        return entry, item

    def records(self, changes: list) -> list[dict]:
        out = []
        audio: dict[Path, dict] = {}
        for change in changes:
            if change.kind == "file":
                entry, item = self._ids()
                record = _base_record(change)
                record.update({
                    "type": "file", "id": entry, "item": item, "path": _rel(change.path, self.root),
                    "track": _rel(change.track_path, self.root) if change.track_path else None,
                    "headers": [list(pair) for pair in change.headers],
                    "source_encoding": change.source_encoding, "approximate": change.approximate,
                })
                if change.original_bytes is not None:
                    record.update({"original_sha": sha256(change.original_bytes),
                                   "original_size": len(change.original_bytes),
                                   "original_mtime": change.original_mtime})
                if change.new_bytes is not None:
                    record["new_sha"] = sha256(change.new_bytes)
                if self.with_diff and change.status == "change":
                    record["diff"] = diff_lines(change.original_text, change.new_text)
                out.append(record)
                continue
            record = audio.get(change.path)
            if record is None:
                entry = self.next_id
                self.next_id += 1
                record = {"type": "audio", "id": entry, "path": _rel(change.path, self.root),
                          "track": _rel(change.track_path, self.root) if change.track_path else None,
                          "status": "unchanged", "plan": None, "slots": []}
                try:
                    record["size"] = os.stat(long_path(change.path)).st_size
                except OSError:
                    record["size"] = 0
                audio[change.path] = record
                out.append(record)
            slot = _base_record(change)
            slot.update({"item": self.next_item, "ref": change.slot.ref() if change.slot else None,
                         "original": _jsonable(change.original_value), "new": _jsonable(change.new_value),
                         "original_encoding": change.slot.id3_encoding if change.slot else None,
                         "new_encoding": change.new_encoding})
            self.next_item += 1
            if self.with_diff and change.status == "change":
                slot["diff"] = diff_lines(change.original_text, change.new_text)
            record["slots"].append(slot)
            if change.file_plan:
                record["plan"] = change.file_plan
        for record in audio.values():
            statuses = [slot["status"] for slot in record["slots"]]
            record["status"] = "change" if "change" in statuses else (statuses[0] if len(set(statuses)) == 1
                                                                       else "unchanged")
        return out


# --------------------------------------------------------------------------
# Totales
# --------------------------------------------------------------------------

@dataclass
class Totals:
    lyrics: int = 0
    statuses: Counter = field(default_factory=Counter)
    """Por letra (cada copia: archivo o etiqueta)."""
    files_changed: int = 0
    embedded_changed: int = 0
    songs_changed: int = 0
    entries: int = 0
    """Entradas a aplicar (archivos de letra + archivos de audio)."""
    nearly_empty: int = 0
    unknown: int = 0
    skip_reasons: Counter = field(default_factory=Counter)
    """Archivos de audio omitidos por motivo."""
    space: int = 0
    """Espacio para el respaldo (copias y parches)."""
    largest_rewrite: int = 0
    """Mayor espacio temporal necesario a la vez (archivo temporal más grande)."""
    files_seen: int = 0
    full_rewrites: Counter = field(default_factory=Counter)
    """Archivos de audio que necesitarían reescritura completa, por extensión (permitida o no)."""

    def add(self, record: dict) -> None:
        slots = [record] if record["type"] == "file" else record["slots"]
        for slot in slots:
            self.lyrics += 1
            self.statuses[slot["status"]] += 1
            self.nearly_empty += bool(slot["nearly_empty"])
            self.unknown += bool(slot["unknown"])
        reasons = {slot["skip_reason"] for slot in slots if slot["status"] == "skipped" and slot["skip_reason"]}
        for reason in reasons:
            self.skip_reasons[reason] += 1
        if record["type"] == "audio" and ("full_rewrite" in reasons or (
                record["status"] == "change" and record["plan"] and record["plan"]["mode"] == MODE_FULL)):
            self.full_rewrites[Path(record["path"]).suffix.lower().lstrip(".") or "?"] += 1
        if record["status"] != "change":
            return
        self.entries += 1
        if record["type"] == "file":
            self.files_changed += 1
            size = record.get("original_size", 0)
            self.space += size + 4096
            self.largest_rewrite = max(self.largest_rewrite, size)
        else:
            changed = [slot for slot in slots if slot["status"] == "change"]
            self.embedded_changed += len(changed)
            lyric_bytes = sum(len(json.dumps(slot["original"], ensure_ascii=False)) for slot in changed)
            self.space += 4 * lyric_bytes + 4096
            if record["plan"] and record["plan"]["mode"] == MODE_FULL:
                self.largest_rewrite = max(self.largest_rewrite, record.get("size", 0))
            else:
                # Diario de escritura (pre-imagen de la región, temporal).
                self.largest_rewrite = max(self.largest_rewrite, 2 * lyric_bytes + 65536)

    def needed(self) -> int:
        return self.space + self.largest_rewrite + SPACE_MARGIN

    def to_json(self) -> dict:
        return {"lyrics": self.lyrics, "statuses": dict(self.statuses), "files_changed": self.files_changed,
                "embedded_changed": self.embedded_changed, "songs_changed": self.songs_changed,
                "entries": self.entries, "nearly_empty": self.nearly_empty, "unknown": self.unknown,
                "skip_reasons": dict(self.skip_reasons), "space": self.space,
                "largest_rewrite": self.largest_rewrite, "needed": self.needed(),
                "files_seen": self.files_seen, "full_rewrites": dict(self.full_rewrites)}


# --------------------------------------------------------------------------
# Pasada 1: planificación
# --------------------------------------------------------------------------

class SelectionError(Exception):
    """Un valor de --only no corresponde a ninguna carpeta ni álbum."""


def resolve_only(root: Path, only: list[str]) -> tuple[list[Path], set[str]]:
    folders, albums = [], set()
    for value in only or []:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = Path(root) / candidate
        if candidate.is_dir():
            folders.append(candidate.resolve())
        else:
            albums.add(value.strip().lower())
    return folders, albums


def plan_library(run: Run, normalizer, root: Path, only: list[str] | None = None,
                 include_hidden: bool = False, progress=None, with_diff: bool = True) -> Totals:
    """
    Recorre la biblioteca carpeta por carpeta y escribe el plan en disco.

    En memoria solo están la carpeta actual y los totales.
    """
    root = Path(root)
    folders, albums = resolve_only(root, only or [])
    walk = None if albums else (folders or None)
    builder = RecordBuilder(root, with_diff)
    totals = Totals()
    found_albums: set[str] = set()

    def in_folders(path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved == folder or folder in resolved.parents for folder in folders)

    def on_file(_path):
        totals.files_seen += 1
        if progress is not None:
            progress.advance(totals)

    with open(long_path(run.folder / PLAN_NAME), "a", encoding="utf-8") as plan_file:
        for folder_scan in iter_folders(root, include_hidden, on_file, folders=walk):
            if not reachable(root, backups=False):
                raise StopRun("device", "La biblioteca dejó de estar accesible durante la planificación "
                                        "(¿se desconectó la tarjeta SD?). No se modificó nada.")
            tracks, orphans = folder_scan.tracks, folder_scan.orphan_lyrics
            if albums:
                for track in tracks:
                    if (track.album or "").lower() in albums:
                        found_albums.add((track.album or "").lower())
                tracks = [t for t in tracks if (t.album or "").lower() in albums or (folders and in_folders(t.filepath))]
                orphans = [o for o in orphans if folders and in_folders(Path(o.location))]
            records = builder.records(list(normalizer.plan_tracks(tracks, orphans)))
            songs = set()
            for record in records:
                totals.add(record)
                if record["status"] == "change":
                    songs.add(record.get("track") or record["path"])
                plan_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            totals.songs_changed += len(songs)
            plan_file.flush()
        missing = sorted(albums - found_albums)
        plan_file.write(json.dumps({"type": "end", "entries": totals.entries}) + "\n")
        fsync_file(plan_file)
    run.save_state(state=STATE_PLANNED, totals=totals.to_json(), missing_albums=missing)
    return totals


def plan_from_changes(run: Run, changes: list, root: Path) -> Totals:
    """Escribe un plan a partir de cambios ya calculados en memoria (API de LyricsNormalizer)."""
    builder = RecordBuilder(root, with_diff=True)
    totals = Totals()
    with open(long_path(run.folder / PLAN_NAME), "a", encoding="utf-8") as plan_file:
        records = builder.records(changes)
        songs = set()
        for record in records:
            totals.add(record)
            if record["status"] == "change":
                songs.add(record.get("track") or record["path"])
            plan_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        totals.songs_changed = len(songs)
        plan_file.write(json.dumps({"type": "end", "entries": totals.entries}) + "\n")
        fsync_file(plan_file)
    run.save_state(state=STATE_PLANNED, totals=totals.to_json(), missing_albums=[])
    return totals


# --------------------------------------------------------------------------
# Pasada 2: aplicación
# --------------------------------------------------------------------------

class InsufficientSpace(Exception):
    pass


def check_space(run: Run, root: Path) -> None:
    needed = run.state["totals"]["needed"]
    free = shutil.disk_usage(long_path(root)).free
    if free < needed:
        raise InsufficientSpace(
            f"Espacio libre insuficiente en la unidad de la biblioteca: se estiman {format_size(needed)} "
            f"(respaldo {format_size(run.state['totals']['space'])} + temporal "
            f"{format_size(run.state['totals']['largest_rewrite'])} + margen) y hay {format_size(free)}. "
            "No se modificó nada.")


@dataclass
class ApplySummary:
    applied: int = 0
    failed: int = 0
    stopped: str | None = None
    """Motivo si la ejecución se detuvo antes de terminar."""
    stop_kind: str | None = None


def apply_run(run: Run, normalizer, root: Path, progress=None, resume: bool = False,
              verify: str = VERIFY_AUTO) -> ApplySummary:
    """Aplica las entradas del plan que faltan. Se puede reanudar."""
    root = Path(root)
    summary = ApplySummary()
    check_space(run, root)
    journal = Journal(run.folder)
    try:
        intents, done = run.outcome()
        run.confirmed = {event["id"]: event.get("status") for event in done.values()}
        if not resume:
            _log_header(run, root)
        else:
            run.log(["", f"=== Reanudado el {datetime.now().isoformat(timespec='seconds')} ==="])
        run.save_state(state=STATE_APPLYING)
        for record in run.plan_records():
            if record["status"] != "change" or record["id"] in done:
                continue
            if not reachable(root):
                raise StopRun("device", "La biblioteca o su carpeta de respaldo ya no están accesibles "
                                        "(¿se desconectó la tarjeta SD?).")
            if record["type"] == "file":
                status, error = _apply_file(run, normalizer, root, record)
            else:
                status, error = _apply_audio(run, root, record, journal, verify, progress)
            if status == APPLIED:
                summary.applied += 1
            else:
                summary.failed += 1
            if progress is not None:
                progress.applied(summary)
        run.save_state(state=STATE_COMPLETED)
        _log_footer(run, summary)
    except OSError as exc:
        # Error del respaldo (estado, plan, diario, registro), no de un archivo
        # de la biblioteca: no se puede seguir anotando qué se hace.
        stop = _infrastructure_stop(exc, root, run)
        summary.stopped = str(stop)
        summary.stop_kind = stop.kind
        _mark_interrupted(run, root, stop)
    except StopRun as stop:
        summary.stopped = str(stop)
        summary.stop_kind = stop.kind
        _mark_interrupted(run, root, stop)
    except KeyboardInterrupt:
        try:
            run.save_state(state=STATE_INTERRUPTED, stop_reason="interrumpido por el usuario", stop_kind="user")
        except OSError:
            pass
        raise
    return summary


def _infrastructure_stop(exc: OSError, root: Path, run: Run) -> StopRun:
    kind = fatal_kind(exc, root) or "device"
    if kind == "space":
        return StopRun("space", f"Sin espacio libre para escribir el respaldo ({exc}).")
    return StopRun("device", f"No se pudo escribir en la carpeta de respaldo ({exc}); "
                             "¿se desconectó la tarjeta SD?")


def _mark_interrupted(run: Run, root: Path, stop: StopRun) -> None:
    """
    Anota la interrupción si se puede. Si la unidad ya no está, no pasa
    nada: el diario en disco termina en el último evento confirmado y
    --resume decide a partir de él.
    """
    try:
        run.save_state(state=STATE_INTERRUPTED, stop_reason=str(stop), stop_kind=stop.kind)
        run.log(["", f"=== DETENIDO: {stop} ===",
                 f"Para continuar: choconostle {run.state['command']} \"{root}\" --resume \"{run.folder}\""])
    except OSError:
        pass


def _diary(run: Run, root: Path, event: dict) -> None:
    """Escribe un evento del diario; si no se puede, la ejecución se detiene (nunca sigue sin anotar)."""
    try:
        run.event(event)
    except OSError as exc:
        raise _infrastructure_stop(exc, root, run) from exc


def _finish(run: Run, record: dict, status: str, error: str | None, extra: dict | None = None,
            log_lines: list[str] | None = None, root: Path | None = None) -> tuple[str, str | None]:
    root = root if root is not None else run.library_root()
    event = {"event": "done", "id": record["id"], "status": status, "error": error}
    event.update(extra or {})
    _diary(run, root, event)
    try:
        run.log(_log_block(record, status, error) + (log_lines or []))
    except OSError as exc:
        raise _infrastructure_stop(exc, root, run) from exc
    checkpoint("done", record)
    return status, error


def _stop_if_fatal(exc: BaseException, root: Path) -> None:
    kind = fatal_kind(exc, root)
    if kind == "space":
        raise StopRun("space", f"Sin espacio libre en la unidad ({exc}).") from exc
    if kind == "device":
        raise StopRun("device", f"La unidad dejó de responder ({exc}); ¿se desconectó la tarjeta SD?") from exc


def _apply_file(run: Run, normalizer, root: Path, record: dict) -> tuple[str, str | None]:
    path = root / record["path"]
    checkpoint("start", record)
    try:
        current = Path(long_path(path)).read_bytes()
    except OSError as exc:
        _stop_if_fatal(exc, root)
        return _finish(run, record, FAILED, f"no se pudo leer: {exc}")
    if sha256(current) != record["original_sha"]:
        return _finish(run, record, FAILED, "el archivo cambió desde que se planearon los cambios")
    change = normalizer.plan_one_file(path, record["headers"])
    if change.new_bytes is None or sha256(change.new_bytes) != record.get("new_sha"):
        return _finish(run, record, FAILED, "el resultado ya no coincide con el plan")

    copy = f"{ORIGINALS_DIR}/{record['id']:06d} - {_safe_name(path.name)}"
    try:
        with open(long_path(run.folder / copy), "wb") as handle:
            handle.write(current)
            fsync_file(handle)
        checkpoint("backup", record)
        _diary(run, root, {"event": "intent", "id": record["id"], "copy": copy, "original_sha": record["original_sha"],
                   "new_sha": record["new_sha"], "original_mtime": record.get("original_mtime")})
        checkpoint("intent", record)
        write_file_atomic(path, change.new_bytes)
        checkpoint("written", record)
        written = Path(long_path(path)).read_bytes()
    except OSError as exc:
        _stop_if_fatal(exc, root)
        return _finish(run, record, FAILED, f"no se pudo escribir: {exc}")
    if sha256(written) != record["new_sha"]:
        try:
            write_file_atomic(path, current)
        except OSError as exc:
            _stop_if_fatal(exc, root)
        return _finish(run, record, FAILED, "la verificación tras escribir falló; se restauró el original")
    return _finish(run, record, APPLIED, None)


def _apply_audio(run: Run, root: Path, record: dict, journal: Journal, verify: str,
                 progress=None) -> tuple[str, str | None]:
    path = root / record["path"]
    plan = record["plan"]
    changed = [slot for slot in record["slots"] if slot["status"] == "change"]
    checkpoint("start", record)
    try:
        editor = open_editor(path)
        if editor is None:
            raise ChangedError("el archivo ya no tiene etiquetas")
        if file_signature(path) != tuple(plan["signature"]):
            raise ChangedError("el archivo cambió desde que se planearon los cambios")
        if plan["region_sha"] is not None and sha256(editor.region) != plan["region_sha"]:
            raise ChangedError("las etiquetas cambiaron desde que se planearon los cambios")
        current = {(slot.key, slot.index): slot.value for slot in editor.slots()}
        for slot in changed:
            ref = slot["ref"]
            if current.get((ref["key"], ref["index"])) != python_value(slot["original"]):
                raise ChangedError("la letra cambió desde que se planearon los cambios")
        values = {(slot["ref"]["key"], slot["ref"]["index"]): python_value(slot["new"]) for slot in changed}
        encodings = {slot["ref"]["key"]: slot["new_encoding"] for slot in changed
                     if slot.get("new_encoding") is not None}
        edit = editor.build(values, encodings)
        if edit.mode != plan["mode"]:
            raise ChangedError("la forma de escribir cambió desde que se planearon los cambios")
    except (Unsupported, ChangedError) as exc:
        return _finish(run, record, FAILED, str(exc))
    except OSError as exc:
        _stop_if_fatal(exc, root)
        return _finish(run, record, FAILED, f"no se pudo abrir: {exc}")

    is_ogg = isinstance(editor, OggEditor)
    verify = effective_verify(verify, edit.mode)
    intent = {"event": "intent", "id": record["id"], "writer": "mutagen-ogg" if is_ogg else "raw",
              "format": editor.tag_format, "mode": edit.mode, "signature": plan["signature"],
              "verify": verify}
    try:
        if is_ogg:
            intent["old_sha"] = file_sha256(path)
        else:
            patches = f"{ORIGINALS_DIR}/edit-{record['id']:06d} - {_safe_name(path.name)}.json"
            data = {"start": editor.start, "old_len": edit.old_len, "new_len": edit.new_len,
                    "patches": patches_to_json(edit.patches)}
            with open(long_path(run.folder / patches), "w", encoding="utf-8") as handle:
                handle.write(json.dumps(data))
                fsync_file(handle)
            intent.update({
                "patches": patches, "start": editor.start, "old_len": edit.old_len, "new_len": edit.new_len,
                "old_sha": sha256(editor.region), "new_sha": sha256(apply_patches(editor.region, edit.patches)),
                "size_before": plan["signature"][0],
                "size_after": plan["signature"][0] + edit.new_len - edit.old_len,
            })
        checkpoint("backup", record)
        _diary(run, root, intent)
        checkpoint("intent", record)
        if is_ogg or verify == VERIFY_FULL:
            _progress_call(progress, "step", f"verificando el audio completo: {path.name}")
        if is_ogg:
            result = rewrite_with(path, tuple(plan["signature"]), lambda tmp: OggEditor.modify(tmp, values),
                                  lambda original, tmp: editor.check(original, tmp, edit.expected),
                                  plan.get("audio"))
        else:
            result = write_edit(path, editor, edit, journal, f"edit-{record['id']:06d}",
                                tuple(plan["signature"]), record["path"], verify, plan.get("audio"))
        _progress_call(progress, "step", "")
        checkpoint("written", record)
    except RestoreError as exc:
        raise StopRun("restore", f"ERROR GRAVE en {record['path']}: {exc}") from exc
    except (WriteError, OSError) as exc:
        _stop_if_fatal(exc, root)
        return _finish(run, record, FAILED, str(exc))
    extra = {key: result[key] for key in ("new_sha", "size_after") if is_ogg and key in result}
    return _finish(run, record, APPLIED, None, extra)


# --------------------------------------------------------------------------
# Registro (registro.txt)
# --------------------------------------------------------------------------

def _log_header(run: Run, root: Path) -> None:
    options = run.state["options"]
    totals = run.state["totals"]
    run.log([
        f"{APP_NAME} {APP_VERSION} - {run.state['command']}",
        f"Fecha: {run.state['created_at']}",
        f"Biblioteca: {root}",
        "Opciones: " + ", ".join(f"{key}={value}" for key, value in options.items()),
        f"Entradas a aplicar: {totals['entries']} ({totals['files_changed']} archivos de letra, "
        f"{totals['embedded_changed']} letras incrustadas)",
        "",
        f'Para deshacer: choconostle revert "{run.folder}"',
        "",
    ])


def _log_block(record: dict, status: str, error: str | None) -> list[str]:
    names = {APPLIED: "aplicado", FAILED: "FALLÓ"}
    lines = ["=" * 72]
    if record["type"] == "file":
        lines.append(f"[{record['id']:06d}] {record['path']}  (archivo)")
        if record.get("track") and record["track"] != record["path"]:
            lines.append(f"  Canción: {record['track']}")
        lines.append(f"  Cambios: {'; '.join(record['details']) or '-'}")
        if record.get("source_encoding"):
            lines.append(f"  Codificación de origen: {record['source_encoding']}")
        lines += [f"  Aviso: {warning}" for warning in record["warnings"]]
        if record.get("approximate"):
            lines.append("  Vista aproximada: la codificación de origen no se pudo confirmar; "
                         "el archivo se modifica byte a byte sin depender de ella.")
        lines.append(f"  Estado: {names.get(status, status)}" + (f" ({error})" if error else ""))
        lines += ["  " + line for line in record.get("diff", [])]
        return lines
    lines.append(f"[{record['id']:06d}] {record['path']}  (audio)")
    lines.append(f"  Estado: {names.get(status, status)}" + (f" ({error})" if error else ""))
    for slot in record["slots"]:
        if slot["status"] != "change":
            continue
        lines.append(f"  {slot['label']}: {'; '.join(slot['details']) or '-'}")
        lines += [f"    Aviso: {warning}" for warning in slot["warnings"]]
        lines += ["    " + line for line in slot.get("diff", [])]
    return lines


def _log_footer(run: Run, summary: ApplySummary) -> None:
    run.log(["", f"Resultado: {plural(summary.applied, 'entrada')} aplicadas, "
                 f"{plural(summary.failed, 'entrada')} con error."])


# --------------------------------------------------------------------------
# Reanudación
# --------------------------------------------------------------------------

def processor_for(run: Run):
    """Normalizador o conversor con las opciones guardadas de la ejecución."""
    options = run.state["options"]
    if run.state.get("command") == "convert-lyrics":
        from choconostle.converter import LyricsConverter
        return LyricsConverter.from_options(options)
    from choconostle.normalizer import LyricsNormalizer
    return LyricsNormalizer.from_options(options)


def resume_check(run: Run, root: Path, normalizer, command: str | None = None, progress=None) -> list[str]:
    """
    Comprueba que la ejecución se puede reanudar con seguridad y resuelve
    las entradas que quedaron a medias. Retorna los problemas; si hay
    alguno, no se cambió nada en la biblioteca.
    """
    root = Path(root)
    problems = []
    phase = run.phase
    expected = command or getattr(normalizer, "command", "normalize-lyrics")
    if run.state.get("command") != expected:
        problems.append(f"la ejecución es de otro comando ({run.state.get('command')}); "
                        f"reanúdala con choconostle {run.state.get('command')} --resume.")
    if phase == STATE_COMPLETED:
        problems.append("la ejecución ya está completada: no hay nada que reanudar.")
    elif phase == STATE_PLANNING or not run.plan_complete():
        problems.append("la planificación no terminó (no se aplicó nada): vuelve a ejecutar sin --resume.")
    if run.folder.parent.parent.resolve() != root.resolve():
        problems.append(f"la carpeta de respaldo no pertenece a esta biblioteca ({run.folder}).")
    if problems:
        return problems

    # 1. Escrituras byte a byte interrumpidas (pre-imagen en pendiente/).
    for name, status, message in recover(run.folder, root):
        if status == "failed":
            problems.append(f"no se pudo recuperar la escritura {name}: {message}")
    if problems:
        return problems

    intents, done = run.outcome()
    resolved = []
    _progress_call(progress, "start", "Comprobando lo ya aplicado", len(intents))
    for record in run.plan_records():
        if record["status"] != "change":
            continue
        entry = record["id"]
        intent = intents.get(entry)
        if intent is not None:
            _progress_call(progress, "tick", 1, record["path"])
        if entry in done and done[entry]["status"] == APPLIED:
            problem = _check_applied(run, root, record, intent)
            if problem:
                problems.append(problem)
        elif entry not in done and intent is not None:
            state, problem = _resolve_intent(run, root, record, intent)
            if problem:
                problems.append(problem)
            elif state == APPLIED:
                resolved.append((record, intent))
    if problems:
        return problems
    for record, intent in resolved:
        run.event(dict({"event": "done", "id": record["id"], "status": APPLIED, "error": None,
                        "note": "completada antes de la interrupción"}, **_applied_extra(root, record, intent)))
        run.log(_log_block(record, APPLIED, None) + ["  (verificado al reanudar)"])
    return []


def _applied_extra(root: Path, record: dict, intent: dict) -> dict:
    """Datos que el evento "done" de una reescritura Ogg necesita para revertir (hash del resultado)."""
    if intent.get("writer") != "mutagen-ogg":
        return {}
    path = root / record["path"]
    return {"new_sha": file_sha256(path), "size_after": file_signature(path)[0]}


def _backup_ok(run: Run, record: dict, intent: dict) -> str | None:
    if record["type"] == "file":
        copy = run.folder / intent["copy"]
        try:
            data = Path(long_path(copy)).read_bytes()
        except OSError:
            return f"falta la copia de respaldo de {record['path']} ({intent['copy']})."
        if sha256(data) != record["original_sha"]:
            return f"la copia de respaldo de {record['path']} está dañada."
        return None
    if intent.get("writer") == "raw":
        if not (run.folder / intent["patches"]).is_file():
            return f"faltan los parches de respaldo de {record['path']}."
    return None


def _file_state(root: Path, record: dict, intent: dict | None) -> str:
    """"new", "original", "changed" o "missing"."""
    path = root / record["path"]
    try:
        if record["type"] == "file":
            digest = sha256(Path(long_path(path)).read_bytes())
            return {record.get("new_sha"): "new", record["original_sha"]: "original"}.get(digest, "changed")
        if intent is None:
            return "original"
        if intent["writer"] == "mutagen-ogg":
            digest = file_sha256(path)
            if digest == intent["old_sha"]:
                return "original"
            return "new" if digest == intent.get("new_sha", digest) else "changed"
        size = file_signature(path)[0]
        if size == intent["size_after"] and sha256(read_at(path, intent["start"], intent["new_len"])) == intent["new_sha"]:
            return "new"
        if size == intent["size_before"] and sha256(read_at(path, intent["start"], intent["old_len"])) == intent["old_sha"]:
            return "original"
        return "changed"
    except FileNotFoundError:
        return "missing"


def _check_applied(run: Run, root: Path, record: dict, intent: dict | None) -> str | None:
    if intent is not None:
        problem = _backup_ok(run, record, intent)
        if problem:
            return problem
    done = {}
    for event in run.events():
        if event["event"] == "done" and event["id"] == record["id"]:
            done = event
    if intent is not None and intent.get("writer") == "mutagen-ogg":
        intent = dict(intent, new_sha=done.get("new_sha"))
    state = _file_state(root, record, intent)
    if state != "new":
        return (f"{record['path']} ya se había aplicado pero ahora "
                + ("no existe." if state == "missing" else "es distinto: cambió fuera de la herramienta."))
    return None


def _resolve_intent(run: Run, root: Path, record: dict, intent: dict) -> tuple[str | None, str | None]:
    problem = _backup_ok(run, record, intent)
    if problem:
        return None, problem
    temporary = (root / record["path"]).with_name(Path(record["path"]).name + TEMP_SUFFIX)
    if os.path.exists(long_path(temporary)):
        os.unlink(long_path(temporary))
    if intent.get("writer") == "mutagen-ogg":
        state = _file_state(root, record, dict(intent, new_sha=None))
        if state == "changed":
            # El reemplazo atómico se completó: se comprueba que las letras son las planeadas.
            editor = open_editor(root / record["path"])
            values = {(s.key, s.index): s.value for s in editor.slots()}
            ok = all(values.get((slot["ref"]["key"], slot["ref"]["index"])) == python_value(slot["new"])
                     for slot in record["slots"] if slot["status"] == "change")
            state = "new" if ok else "changed"
    else:
        state = _file_state(root, record, intent)
    if state == "new":
        return APPLIED, None
    if state == "original":
        return "pending", None
    if state == "missing":
        return None, f"{record['path']} desapareció durante una escritura interrumpida."
    return None, (f"{record['path']} no es ni el original ni el resultado planeado tras una escritura "
                  "interrumpida: cambió fuera de la herramienta.")


# --------------------------------------------------------------------------
# Reversión
# --------------------------------------------------------------------------

def revert_space_needed(run: Run) -> int:
    """
    Espacio libre que necesita revert: el temporal más grande a la vez (un
    .lrc entero, la pre-imagen de una región de etiquetas o un archivo de
    audio si hay reescritura completa) más el margen.
    """
    intents, done = run.outcome()
    largest = 0
    for record in run.plan_records():
        intent = intents.get(record["id"])
        if record["status"] != "change" or intent is None:
            continue
        if record["type"] == "file":
            largest = max(largest, record.get("original_size", 0))
        elif intent.get("writer") == "mutagen-ogg" or intent.get("mode") == MODE_FULL:
            largest = max(largest, record.get("size", 0))
        else:
            largest = max(largest, intent.get("new_len", 0))
    return largest + SPACE_MARGIN


REVERT_ITEM_KEYS = ("id", "kind", "path", "label")


def revert_run(folder: Path, force: bool = False, dry_run: bool = False, progress=None) -> list:
    """
    Deshace una ejecución (formato 3) a partir de su plan y su diario.

    Si la unidad se desconecta, se queda sin espacio o una restauración
    falla, se detiene (RevertStopped) sin seguir con los demás archivos:
    volver a ejecutar revert continúa donde quedó (lo ya restaurado cuenta
    como "ya estaba como el original").
    """
    from choconostle import backup
    run = Run(folder)
    root = run.library_root()
    results: list = []

    def stop(exc: BaseException, kind: str | None = None):
        kind = kind or fatal_kind(exc, root) or "device"
        reason = {"space": "sin espacio libre", "restore": "una restauración no se pudo completar"}.get(
            kind, "la unidad dejó de responder (¿se desconectó la tarjeta SD?)")
        try:
            backup._write_revert_log(run.folder, root, results)
        except OSError:
            pass
        raise backup.RevertStopped(results, kind, f"revert se detuvo: {reason} ({exc}).") from exc

    try:
        if not dry_run:
            needed = revert_space_needed(run)
            free = shutil.disk_usage(long_path(root)).free
            if free < needed:
                raise backup.RevertNoSpace(
                    f"Espacio libre insuficiente para revertir: se necesitan {format_size(needed)} y hay "
                    f"{format_size(free)}. No se modificó nada.")
            if Journal(run.folder).pending():  # la línea solo aparece si hay algo que recuperar
                _progress_call(progress, "start", "Recuperando escrituras pendientes", None)
            recover(run.folder, root)
        intents, done = run.outcome()
        _progress_call(progress, "start", "Comprobando" if dry_run else "Revirtiendo",
                       run.state.get("totals", {}).get("entries"))
        for record in run.plan_records():
            if record["status"] != "change":
                continue
            _progress_call(progress, "tick", 0, record["path"])
            new = _revert_record(run, root, record, intents, done, force, dry_run)
            _progress_call(progress, "tick", 1, "")
            for result in new:
                # Solo lo que usan el registro y la consola: la letra original
                # ocupaba en memoria hasta terminar (etapa ⑥).
                result.item = {key: result.item[key] for key in REVERT_ITEM_KEYS if key in result.item}
            results += new
            for result in new:
                if result.status != backup.REVERT_ERROR or result.exc is None:
                    continue
                if result.message.startswith("ERROR GRAVE"):
                    stop(result.exc, "restore")
                if fatal_kind(result.exc, root):
                    stop(result.exc)
    except OSError as exc:
        if fatal_kind(exc, root) or not reachable(root, backups=False):
            stop(exc)
        raise
    if not dry_run:
        try:
            backup._write_revert_log(run.folder, root, results)
        except OSError as exc:
            stop(exc)
    return results


def _revert_record(run: Run, root: Path, record: dict, intents: dict, done: dict, force: bool,
                   dry_run: bool) -> list:
    from choconostle import backup
    entry = record["id"]
    intent = intents.get(entry)
    result = done.get(entry)
    applied = result is not None and result["status"] == APPLIED
    if result is None and intent is not None:
        state, _problem = _resolve_intent(run, root, record, intent) if not dry_run else (None, None)
        applied = state == APPLIED
        if applied:
            result = dict(_applied_extra(root, record, intent), status=APPLIED)
    items = _items(record)
    if intent is None or not applied:
        return [backup.RevertResult(item, backup.REVERT_ALREADY, "No se había aplicado.") for item in items]
    if record["type"] == "file":
        item = dict(items[0], original_copy=intent["copy"], original_sha256=record["original_sha"],
                    new_sha256=record["new_sha"], original_mtime=record.get("original_mtime"))
        return [backup._revert_file(item, run.folder, root, force, dry_run)]
    edit = dict(intent, id=entry, path=record["path"], status=APPLIED)
    if result and result.get("new_sha"):
        edit["new_sha"] = result["new_sha"]
    return backup._revert_edit(edit, items, run.folder, root, dry_run)


def _items(record: dict) -> list[dict]:
    if record["type"] == "file":
        return [{"id": record["item"], "kind": "file", "path": record["path"], "label": record["label"]}]
    return [{"id": slot["item"], "kind": "embedded", "path": record["path"], "label": slot["label"],
             "slot": slot["ref"], "original_value": slot["original"],
             "original_encoding": slot.get("original_encoding"), "new_encoding": slot.get("new_encoding")}
            for slot in record["slots"] if slot["status"] == "change"]


def recover_run(folder: Path) -> list[tuple[str, str, str]]:
    """Resuelve escrituras byte a byte interrumpidas y anota el resultado en el diario."""
    run = Run(folder)
    root = run.library_root()
    results = recover(run.folder, root)
    intents, done = run.outcome()
    for name, status, message in results:
        if not name.startswith("edit-"):
            continue
        entry = int(name.split("-")[1])
        if entry in done:
            continue
        if status == "complete":
            run.event({"event": "done", "id": entry, "status": APPLIED, "error": None,
                       "note": "completada según el diario de escritura"})
        elif status in ("restored", "untouched"):
            run.event({"event": "done", "id": entry, "status": FAILED, "error": f"interrumpida: {message}"})
    return results


# --------------------------------------------------------------------------
# Limpieza de respaldos
# --------------------------------------------------------------------------

@dataclass
class BackupInfo:
    folder: Path
    created: datetime | None
    kind: str
    """"v3", "v2" o "v1"."""
    state: str
    keep_reason: str | None = None
    """Motivo para no borrarlo nunca (incompleto, reanudable, escrituras pendientes)."""
    size: int = 0
    error: str | None = None
    """Error al borrarlo (p. ej. acceso denegado); se reintenta en la próxima ejecución."""
    deleted: bool = False


def list_backups(root: Path) -> list[BackupInfo]:
    base = Path(root) / BACKUP_DIR_NAME
    if not base.is_dir():
        return []
    found = []
    for folder in sorted(base.iterdir()):
        if not folder.is_dir():
            continue
        if _DELETING_RE.search(folder.name):
            info = BackupInfo(folder, None, "borrado interrumpido", "borrado interrumpido: se terminará de borrar")
        else:
            info = _backup_info(folder)
        info.size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
        found.append(info)
    return found


def _backup_info(folder: Path) -> BackupInfo:
    pending = Journal(folder).pending()
    if (folder / STATE_NAME).is_file():
        try:
            run = Run(folder)
        except (ValueError, json.JSONDecodeError) as exc:
            return BackupInfo(folder, None, "v3", "dañado", f"estado ilegible ({exc})")
        created = _parse_date(run.state.get("created_at"))
        phase = run.phase
        info = BackupInfo(folder, created, "v3", STATE_NAMES.get(phase, phase))
        intents, done = run.outcome()
        if pending:
            info.keep_reason = "tiene escrituras interrumpidas sin resolver (usa recover)"
        elif phase in (STATE_APPLYING, STATE_INTERRUPTED):
            info.keep_reason = "ejecución incompleta y reanudable (--resume)"
        elif phase == STATE_PLANNED and run.state.get("totals", {}).get("entries"):
            info.keep_reason = "planificada sin aplicar (reanudable con --resume)"
        elif set(intents) - set(done):
            info.keep_reason = "hay escrituras sin confirmar en el diario"
        return info
    manifest_path = folder / "manifiesto.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return BackupInfo(folder, None, "v1/v2", "dañado", f"manifiesto ilegible ({exc})")
        kind = f"v{manifest.get('manifest_version', 1)}"
        info = BackupInfo(folder, _parse_date(manifest.get("created_at")), kind, "completada")
        if pending:
            info.keep_reason = "tiene escrituras interrumpidas sin resolver (usa recover)"
        elif any(item.get("status") == "pending" for item in manifest.get("items", [])):
            info.keep_reason = "hay letras sin confirmar en el manifiesto"
        return info
    return BackupInfo(folder, None, "desconocido", "desconocido",
                      "no es una carpeta de respaldo reconocida")


def _parse_date(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


DELETING_SUFFIX = ".borrando"
_DELETING_RE = re.compile(r"\.borrando(-\d+)?$")


class CleanStopped(Exception):
    """clean-backups se detuvo (unidad desconectada); volver a ejecutarlo termina el trabajo."""

    def __init__(self, remove: list, keep: list, kind: str, message: str):
        self.remove = remove
        self.keep = keep
        self.kind = kind
        super().__init__(message)


def _delete_backup(info: BackupInfo) -> None:
    """
    Borra una carpeta de respaldo de forma reanudable: primero se renombra
    a <nombre>.borrando (una carpeta a medias nunca parece un respaldo
    válido) y luego se borra archivo por archivo, con rutas completas
    (igual en Windows, Linux y Android).
    """
    folder = info.folder
    if not _DELETING_RE.search(folder.name):
        target = folder.with_name(folder.name + DELETING_SUFFIX)
        counter = 2
        while os.path.lexists(long_path(target)):  # otro borrado a medias con el mismo nombre
            target = folder.with_name(f"{folder.name}{DELETING_SUFFIX}-{counter}")
            counter += 1
        os.rename(long_path(folder), long_path(target))
        info.folder = folder = target

    def fail(error: OSError):
        raise error
    for dirpath, _dirnames, filenames in os.walk(long_path(folder), topdown=False, onerror=fail):
        for name in filenames:
            os.unlink(os.path.join(dirpath, name))
        os.rmdir(dirpath)


def clean_backups(root: Path, older_than_days: int, apply: bool = False,
                  now: datetime | None = None, progress=None) -> tuple[list[BackupInfo], list[BackupInfo]]:
    """
    (a borrar, a conservar). Solo borra con apply=True y nunca una
    ejecución incompleta, reanudable o con escrituras pendientes. Los
    borrados interrumpidos (<nombre>.borrando) se terminan siempre.

    Un error en una carpeta (p. ej. acceso denegado) se anota en
    `info.error` y se sigue con las demás; si la unidad se desconecta o deja
    de responder, se lanza CleanStopped.
    """
    now = now or datetime.now()
    remove, keep = [], []
    _progress_call(progress, "start", "Revisando respaldos", None)
    for info in list_backups(root):
        if info.kind == "borrado interrumpido":
            remove.append(info)
        elif info.keep_reason:
            keep.append(info)
        elif info.created is None:
            info.keep_reason = "fecha desconocida"
            keep.append(info)
        elif (now - info.created).days >= older_than_days:
            remove.append(info)
        else:
            info.keep_reason = f"tiene {(now - info.created).days} días"
            keep.append(info)
    if apply:
        _progress_call(progress, "start", "Borrando respaldos", len(remove))
        for info in remove:
            _progress_call(progress, "tick", 0, info.folder.name)
            try:
                _delete_backup(info)
            except OSError as exc:
                kind = fatal_kind(exc, root)
                if kind:
                    info.error = str(exc)
                    raise CleanStopped(remove, keep, kind,
                                       f"clean-backups se detuvo: la unidad dejó de responder ({exc}).") from exc
                info.error = str(exc)
                _progress_call(progress, "tick", 1, "")
                continue
            info.deleted = True
            _progress_call(progress, "tick", 1, "")
    _progress_call(progress, "stop")
    return remove, keep

