"""
backup.py

Respaldo y reversión de normalize-lyrics.

Cada ejecución con --apply crea:

    <biblioteca>/ChoconostleLRCTool_back/<fecha-hora>/
        originales/      Texto original completo de cada letra modificada
        registro.txt     Registro legible (cambios y diferencias)
        manifiesto.json  Todo lo necesario para revertir

No se copian archivos de audio: de las letras incrustadas se guarda solo
el texto.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from choconostle.config import APP_NAME, APP_VERSION, BACKUP_DIR_NAME
from choconostle.embedded import EmbeddedError, EmbeddedLyrics
from choconostle.textio import diff_lines
from choconostle.utils import write_file_atomic

MANIFEST_NAME = "manifiesto.json"
LOG_NAME = "registro.txt"
ORIGINALS_DIR = "originales"
MANIFEST_VERSION = 1

ITEM_PENDING = "pending"
ITEM_APPLIED = "applied"
ITEM_FAILED = "failed"

REVERT_RESTORED = "restored"
REVERT_ALREADY = "already"
REVERT_CONFLICT = "conflict"
REVERT_ERROR = "error"

_UNSAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_name(name: str, limit: int = 80) -> str:
    """Nombre de archivo válido en Windows, Linux y Android."""
    name = _UNSAFE_NAME_RE.sub("_", name).strip(" .") or "letra"
    return name[:limit]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _jsonable(value):
    """SYLT: lista de tuplas -> lista de listas."""
    if isinstance(value, list):
        return [[text, time] for text, time in value]
    return value


def _python_value(value):
    if isinstance(value, list):
        return [(text, time) for text, time in value]
    return value


def _diff(original: str, new: str) -> list[str]:
    """Diferencias por línea; los caracteres invisibles se ven como ⟨U+200B⟩."""
    return diff_lines(original, new)


# --------------------------------------------------------------------------
# Creación del respaldo
# --------------------------------------------------------------------------

class BackupSession:
    """Una carpeta de respaldo para una ejecución de normalize-lyrics."""

    def __init__(self, root: Path, mode: str, encoding: str, now: datetime | None = None):
        self.root = Path(root)
        now = now or datetime.now()
        base = self.root / BACKUP_DIR_NAME
        name = now.strftime("%Y-%m-%d_%H-%M-%S")
        folder = base / name
        counter = 2
        while folder.exists():
            folder = base / f"{name}_{counter}"
            counter += 1
        self.folder = folder
        (folder / ORIGINALS_DIR).mkdir(parents=True)
        self.manifest = {
            "app": APP_NAME,
            "app_version": APP_VERSION,
            "manifest_version": MANIFEST_VERSION,
            "created_at": now.isoformat(timespec="seconds"),
            "root": str(self.root),
            "mode": mode,
            "encoding": encoding,
            "items": [],
        }
        self._changes: list = []

    def add(self, change) -> dict:
        """Guarda el original de un cambio y lo registra en el manifiesto."""
        number = len(self.manifest["items"]) + 1
        item = {
            "id": number,
            "kind": change.kind,
            "path": _relative(change.path, self.root),
            "track": _relative(change.track_path, self.root) if change.track_path else None,
            "label": change.label,
            "details": list(change.details),
            "status": ITEM_PENDING,
            "error": None,
        }
        if change.kind == "file":
            copy_name = f"{number:04d} - {_safe_name(change.path.name)}"
            (self.folder / ORIGINALS_DIR / copy_name).write_bytes(change.original_bytes)
            item.update({
                "original_copy": f"{ORIGINALS_DIR}/{copy_name}",
                "original_sha256": sha256(change.original_bytes),
                "new_sha256": sha256(change.new_bytes),
                "original_mtime": change.original_mtime,
            })
        else:
            copy_name = f"{number:04d} - {_safe_name(change.path.name)} [{_safe_name(change.label, 40)}].txt"
            (self.folder / ORIGINALS_DIR / copy_name).write_text(
                change.original_text, encoding="utf-8", newline="")
            item.update({
                "original_copy": f"{ORIGINALS_DIR}/{copy_name}",
                "slot": change.slot.ref(),
                "original_value": _jsonable(change.original_value),
                "new_value": _jsonable(change.new_value),
                "original_id3_encoding": change.slot.id3_encoding,
            })
        self.manifest["items"].append(item)
        self._changes.append(change)
        return item

    def save_manifest(self) -> None:
        path = self.folder / MANIFEST_NAME
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def write_log(self) -> None:
        mode_names = {"strip": "quitar cabeceras (--strip-headers)",
                      "standardize": "estandarizar cabeceras (--standardize-headers)"}
        status_names = {ITEM_APPLIED: "aplicado", ITEM_FAILED: "FALLÓ", ITEM_PENDING: "pendiente"}
        lines = [
            f"{APP_NAME} {APP_VERSION} - normalize-lyrics",
            f"Fecha: {self.manifest['created_at']}",
            f"Biblioteca: {self.root}",
            f"Modo: {mode_names.get(self.manifest['mode'], self.manifest['mode'])}",
            f"Codificación de archivos .lrc/.txt: {self.manifest['encoding']}",
            f"Letras modificadas: {sum(1 for i in self.manifest['items'] if i['status'] == ITEM_APPLIED)}"
            f" de {len(self.manifest['items'])}",
            "",
            f"Para deshacer: choconostle revert \"{self.folder}\"",
            "",
        ]
        for item, change in zip(self.manifest["items"], self._changes):
            kind = "archivo" if item["kind"] == "file" else f"incrustada {item['label']}"
            lines.append("=" * 72)
            lines.append(f"[{item['id']:04d}] {item['path']}  ({kind})")
            if item["track"] and item["track"] != item["path"]:
                lines.append(f"  Canción: {item['track']}")
            lines.append(f"  Cambios: {'; '.join(item['details']) or '-'}")
            if getattr(change, "source_encoding", None):
                lines.append(f"  Codificación de origen: {change.source_encoding}")
            for warning in getattr(change, "warnings", []):
                lines.append(f"  Aviso: {warning}")
            if getattr(change, "approximate", False):
                lines.append("  Vista aproximada: la codificación de origen no se pudo confirmar; "
                             "el archivo se modifica byte a byte sin depender de ella.")
            lines.append(f"  Estado: {status_names.get(item['status'], item['status'])}"
                         + (f" ({item['error']})" if item["error"] else ""))
            lines.append(f"  Original guardado en: {item['original_copy']}")
            lines.extend("  " + line for line in _diff(change.original_text, change.new_text))
        lines.append("")
        (self.folder / LOG_NAME).write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# Reversión
# --------------------------------------------------------------------------

@dataclass
class RevertResult:
    item: dict
    status: str
    message: str = ""


def _library_root(folder: Path, manifest: dict) -> Path:
    # Se prefiere la ubicación real del respaldo: la biblioteca pudo cambiar
    # de ruta (otra letra de unidad en Windows, /sdcard en Android...).
    if folder.parent.name == BACKUP_DIR_NAME:
        return folder.parent.parent
    return Path(manifest["root"])


def load_manifest(folder: Path) -> dict:
    path = Path(folder) / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"No se encontró {MANIFEST_NAME} en {folder}")
    return json.loads(path.read_text(encoding="utf-8"))


def revert(folder: Path, force: bool = False, dry_run: bool = False) -> list[RevertResult]:
    """
    Restaura las letras originales desde una carpeta de respaldo.

    Solo restaura una letra si su contenido actual es el que dejó
    normalize-lyrics. Si cambió después (otra herramienta, edición
    manual), se reporta como conflicto y no se toca, salvo con force=True.
    """
    folder = Path(folder)
    manifest = load_manifest(folder)
    root = _library_root(folder, manifest)
    results: list[RevertResult] = []

    embedded_by_path: dict[str, list[dict]] = {}
    for item in manifest["items"]:
        if item["kind"] == "file":
            results.append(_revert_file(item, folder, root, force, dry_run))
        else:
            embedded_by_path.setdefault(item["path"], []).append(item)

    for relative, items in embedded_by_path.items():
        results.extend(_revert_embedded(root / relative, items, force, dry_run))

    if not dry_run:
        _write_revert_log(folder, root, results)
    return results


def _revert_file(item: dict, folder: Path, root: Path, force: bool, dry_run: bool) -> RevertResult:
    target = root / item["path"]
    try:
        original = (folder / item["original_copy"]).read_bytes()
    except OSError as exc:
        return RevertResult(item, REVERT_ERROR, f"No se pudo leer la copia original: {exc}")
    if sha256(original) != item["original_sha256"]:
        return RevertResult(item, REVERT_ERROR, "La copia original del respaldo está dañada.")

    try:
        current = target.read_bytes()
    except FileNotFoundError:
        current = None
    except OSError as exc:
        return RevertResult(item, REVERT_ERROR, f"No se pudo leer: {exc}")

    if current is not None and sha256(current) == item["original_sha256"]:
        return RevertResult(item, REVERT_ALREADY, "Ya está como el original.")
    if current is None and not force:
        return RevertResult(item, REVERT_CONFLICT, "El archivo ya no existe (usa --force para recrearlo).")
    if current is not None and sha256(current) != item["new_sha256"] and not force:
        return RevertResult(item, REVERT_CONFLICT,
                            "El archivo cambió después de normalizarlo (usa --force para sobrescribirlo).")
    if dry_run:
        return RevertResult(item, REVERT_RESTORED, "Se restauraría.")

    try:
        write_file_atomic(target, original)
        if item.get("original_mtime"):
            os.utime(target, (item["original_mtime"], item["original_mtime"]))
    except OSError as exc:
        return RevertResult(item, REVERT_ERROR, f"No se pudo escribir: {exc}")
    return RevertResult(item, REVERT_RESTORED)


def _revert_embedded(path: Path, items: list[dict], force: bool, dry_run: bool) -> list[RevertResult]:
    try:
        audio = EmbeddedLyrics(path)
    except (EmbeddedError, OSError) as exc:
        return [RevertResult(item, REVERT_ERROR, f"No se pudo abrir: {exc}") for item in items]
    except Exception as exc:  # noqa: BLE001
        return [RevertResult(item, REVERT_ERROR, f"No se pudo abrir: {exc}") for item in items]

    results: list[RevertResult] = []
    pending: list[RevertResult] = []
    for item in items:
        slot = audio.get(item["slot"])
        if slot is None:
            results.append(RevertResult(item, REVERT_CONFLICT,
                                        f"La etiqueta {item['label']} ya no existe."))
            continue
        original = _python_value(item["original_value"])
        new = _python_value(item["new_value"])
        if slot.value == original and slot.id3_encoding == item.get("original_id3_encoding"):
            results.append(RevertResult(item, REVERT_ALREADY, "Ya está como el original."))
            continue
        if slot.value != new and not force:
            results.append(RevertResult(item, REVERT_CONFLICT,
                                        "La etiqueta cambió después de normalizarla (usa --force)."))
            continue
        if not dry_run:
            try:
                audio.set(item["slot"], original, id3_encoding=item.get("original_id3_encoding"))
            except Exception as exc:  # noqa: BLE001
                results.append(RevertResult(item, REVERT_ERROR, f"No se pudo modificar: {exc}"))
                continue
        pending.append(RevertResult(item, REVERT_RESTORED, "Se restauraría." if dry_run else ""))

    if pending and not dry_run:
        try:
            audio.save()
        except Exception as exc:  # noqa: BLE001
            pending = [RevertResult(r.item, REVERT_ERROR, f"No se pudo guardar: {exc}") for r in pending]
    return results + pending


def _write_revert_log(folder: Path, root: Path, results: list[RevertResult]) -> None:
    names = {REVERT_RESTORED: "restaurado", REVERT_ALREADY: "ya estaba como el original",
             REVERT_CONFLICT: "CONFLICTO, no se tocó", REVERT_ERROR: "ERROR"}
    now = datetime.now()
    lines = [
        f"{APP_NAME} {APP_VERSION} - revert",
        f"Fecha: {now.isoformat(timespec='seconds')}",
        f"Biblioteca: {root}",
        "",
    ]
    for result in results:
        item = result.item
        where = item["path"] if item["kind"] == "file" else f"{item['path']} [{item['label']}]"
        line = f"[{item['id']:04d}] {where}: {names.get(result.status, result.status)}"
        if result.message:
            line += f" - {result.message}"
        lines.append(line)
    lines.append("")
    name = f"revert_{now.strftime('%Y-%m-%d_%H-%M-%S')}.txt"
    (folder / name).write_text("\n".join(lines), encoding="utf-8")
