"""
backup.py

Respaldo y reversión de normalize-lyrics.

Cada ejecución con --apply crea:

    <biblioteca>/ChoconostleLRCTool_back/<fecha-hora>/
        originales/      Texto original completo de cada letra modificada
        registro.txt     Registro legible (cambios y diferencias)
        manifiesto.json  Todo lo necesario para revertir

No se copian archivos de audio. De las letras incrustadas se guarda el
texto (para leerlo) y los "parches" de la edición byte a byte: los bytes
originales de la letra y de los campos de tamaño o relleno que cambiaron
(nunca portadas ni audio). revert los aplica al revés y comprueba con
SHA-256 que la región de etiquetas queda idéntica a la original.

Autor: AndrewSkarlet
Licencia: MIT
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from choconostle.config import APP_NAME, APP_VERSION, BACKUP_DIR_NAME
from choconostle.embedded import open_editor
from choconostle.legacy_embedded import EmbeddedError, EmbeddedLyrics
from choconostle.rawtags import (
    MODE_FULL, Edit, Unsupported, apply_patches, invert_patches, patches_from_json,
)
from choconostle.rawtags.ogg import OggEditor
from choconostle.rawtags.writer import (
    RECOVERED_COMPLETE, RECOVERED_FAILED, VERIFY_AUTO, ChangedError, Journal, RestoreError, WriteError,
    effective_verify, file_sha256, file_signature, recover, rewrite_with, write_edit,
)
from choconostle.utils import write_file_atomic

MANIFEST_NAME = "manifiesto.json"
LOG_NAME = "registro.txt"
ORIGINALS_DIR = "originales"

ITEM_APPLIED = "applied"
ITEM_FAILED = "failed"

REVERT_RESTORED = "restored"
REVERT_ALREADY = "already"
REVERT_CONFLICT = "conflict"
REVERT_ERROR = "error"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _python_value(value):
    if isinstance(value, list):
        return [(text, time) for text, time in value]
    return value


# --------------------------------------------------------------------------
# Reversión
# --------------------------------------------------------------------------

@dataclass
class RevertResult:
    item: dict
    status: str
    message: str = ""
    exc: BaseException | None = field(default=None, compare=False, repr=False)
    """Excepción original de un error (para distinguir una desconexión de un fallo de ese archivo)."""


class RevertStopped(Exception):
    """revert se detuvo (unidad desconectada, sin espacio, restauración fallida); se puede repetir."""

    def __init__(self, results: list, kind: str, message: str):
        self.results = results
        self.kind = kind
        super().__init__(message)


class RevertNoSpace(Exception):
    """No hay espacio libre suficiente para revertir; no se tocó nada."""


def _library_root(folder: Path, manifest: dict) -> Path:
    # Se prefiere la ubicación real del respaldo: la biblioteca pudo cambiar
    # de ruta (otra letra de unidad en Windows, /sdcard en Android...).
    if folder.parent.name == BACKUP_DIR_NAME:
        return folder.parent.parent
    return Path(manifest["root"])


def _is_run(folder: Path) -> bool:
    """True si la carpeta es una ejecución de formato 3 (estado.json + plan + diario)."""
    return (Path(folder) / "estado.json").is_file()


class BackupNotFound(FileNotFoundError):
    """La ruta no es una carpeta de respaldo (o no hay respaldos)."""


def not_found_message(folder: Path) -> str:
    return (f"No se encontró estado.json (ni manifiesto.json de versiones anteriores) en: {folder}\n"
            "Comprueba que la ruta esté completa y en una sola línea: las rutas largas pueden partirse "
            "al copiarlas de la terminal. También puedes indicar la carpeta de la biblioteca con --latest "
            "para usar el respaldo más reciente.")


def is_backup_folder(folder: Path) -> bool:
    folder = Path(folder)
    return _is_run(folder) or (folder / MANIFEST_NAME).is_file()


def backup_date(folder: Path) -> str:
    """Fecha de creación (ISO) de un respaldo, o el nombre de la carpeta si no se puede leer."""
    for name in ("estado.json", MANIFEST_NAME):
        path = Path(folder) / name
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8")).get("created_at") or folder.name
            except (OSError, json.JSONDecodeError):
                break
    return Path(folder).name


def resolve_backup(path: Path, latest: bool = False) -> Path:
    """
    Carpeta de respaldo a partir de lo que indicó el usuario: la carpeta
    de un respaldo, o (con latest=True) la biblioteca o su carpeta
    ChoconostleLRCTool_back, de la que se toma el respaldo más reciente.
    """
    path = Path(path)
    if is_backup_folder(path):
        return path
    base = path if path.name == BACKUP_DIR_NAME else path / BACKUP_DIR_NAME
    if base.is_dir():
        found = sorted((folder for folder in base.iterdir() if folder.is_dir() and is_backup_folder(folder)),
                       key=lambda folder: (backup_date(folder), folder.name))
        if not found:
            raise BackupNotFound(f"No hay respaldos en: {base}")
        if latest:
            return found[-1]
        recent = "\n".join(f"  {folder}" for folder in found[-5:])
        raise BackupNotFound(f"{path} no es un respaldo sino una carpeta con {len(found)} respaldos. "
                             f"Indica uno, o usa --latest para el más reciente. Los últimos:\n{recent}")
    raise BackupNotFound(not_found_message(path))


def load_manifest(folder: Path) -> dict:
    if _is_run(folder):
        from choconostle.run import Run
        return Run(folder).manifest
    path = Path(folder) / MANIFEST_NAME
    if not path.is_file():
        raise BackupNotFound(not_found_message(folder))
    return json.loads(path.read_text(encoding="utf-8"))


def revert(folder: Path, force: bool = False, dry_run: bool = False, progress=None) -> list[RevertResult]:
    """
    Restaura las letras originales desde una carpeta de respaldo.

    Solo restaura una letra si su contenido actual es el que dejó
    normalize-lyrics. Si cambió después (otra herramienta, edición
    manual), se reporta como conflicto y no se toca, salvo con force=True.
    """
    folder = Path(folder)
    if _is_run(folder):
        from choconostle.run import revert_run
        return revert_run(folder, force=force, dry_run=dry_run, progress=progress)
    manifest = load_manifest(folder)
    root = _library_root(folder, manifest)
    results: list[RevertResult] = []
    if not dry_run:
        recover_session(folder)
        manifest = load_manifest(folder)

    embedded_by_path: dict[str, list[dict]] = {}
    edits = {edit["id"]: edit for edit in manifest.get("edits", [])}
    by_edit: dict[int, list[dict]] = {}
    for item in manifest["items"]:
        if item["kind"] == "file":
            results.append(_revert_file(item, folder, root, force, dry_run))
        elif item.get("edit") in edits:
            by_edit.setdefault(item["edit"], []).append(item)
        elif item["status"] == ITEM_FAILED and manifest.get("manifest_version", 1) >= 2:
            results.append(RevertResult(item, REVERT_ALREADY, "No se había aplicado."))
        else:
            embedded_by_path.setdefault(item["path"], []).append(item)

    for edit_id, items in by_edit.items():
        results.extend(_revert_edit(edits[edit_id], items, folder, root, dry_run))
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
        return RevertResult(item, REVERT_ERROR, f"No se pudo leer la copia original: {exc}", exc)
    if sha256(original) != item["original_sha256"]:
        return RevertResult(item, REVERT_ERROR, "La copia original del respaldo está dañada.")

    try:
        current = target.read_bytes()
    except FileNotFoundError:
        current = None
    except OSError as exc:
        return RevertResult(item, REVERT_ERROR, f"No se pudo leer: {exc}", exc)

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
        return RevertResult(item, REVERT_ERROR, f"No se pudo escribir: {exc}", exc)
    return RevertResult(item, REVERT_RESTORED)


def _revert_edit(record: dict, items: list[dict], folder: Path, root: Path, dry_run: bool) -> list[RevertResult]:
    """Deshace una edición byte a byte (o una reescritura Ogg) de un archivo de audio."""
    path = root / record["path"]

    def all_items(status, message="", exc=None):
        return [RevertResult(item, status, message, exc) for item in items]

    if record["status"] != ITEM_APPLIED:
        return all_items(REVERT_ALREADY, "No se había aplicado.")
    try:
        if record["writer"] == "mutagen-ogg":
            return _revert_ogg(record, items, path, dry_run)
        data = json.loads((folder / record["patches"]).read_text(encoding="utf-8"))
        editor = open_editor(path)
        if editor is None or editor.start != data["start"]:
            return all_items(REVERT_CONFLICT, "Las etiquetas cambiaron después de normalizarlas.")
        current = editor.region
        if sha256(current[:data["old_len"]]) == record.get("old_sha") and \
                len(current) == data["old_len"] and file_signature(path)[0] == record["size_before"]:
            return all_items(REVERT_ALREADY, "Ya está como el original.")
        if len(current) != data["new_len"] or sha256(current) != record["new_sha"] \
                or file_signature(path)[0] != record["size_after"]:
            return all_items(REVERT_CONFLICT, "Las etiquetas cambiaron después de normalizarlas; no se tocan.")
        inverse = invert_patches(patches_from_json(data["patches"]))
        original = apply_patches(current, inverse)
        if sha256(original) != record["old_sha"]:
            return all_items(REVERT_ERROR, "Los parches del respaldo no reconstruyen el original.")
        if dry_run:
            return all_items(REVERT_RESTORED, "Se restauraría.")
        expected = {}
        for item in items:
            slot = item["slot"]
            expected[(slot["key"], slot["index"])] = _python_value(item["original_value"])
        mode = MODE_FULL if record["mode"] == MODE_FULL else record["mode"]
        # Frames ID3 cuya codificación cambió (convert-lyrics --id3-encoding): vuelven a la original.
        encodings = {item["slot"]["key"]: item["original_encoding"] for item in items
                     if item.get("new_encoding") is not None and item.get("original_encoding") is not None
                     and item["new_encoding"] != item["original_encoding"]}
        edit = Edit(inverse, mode, len(current), len(original), "", expected, encodings)
        # La misma verificación que se usó al aplicar (auto: rápida en su sitio,
        # completa al reescribir). Antes se usaba siempre la completa (hash de
        # todo el audio dos veces), y revert tardaba casi el triple que --apply.
        write_edit(path, editor, edit, Journal(folder), f"revert-{record['id']:04d}",
                   file_signature(path), record["path"],
                   verify=effective_verify(record.get("verify", VERIFY_AUTO), mode))
        _restore_mtime(path, record)
    except (Unsupported, ChangedError, WriteError, OSError, ValueError, KeyError) as exc:
        return all_items(REVERT_ERROR, f"No se pudo restaurar: {exc}", exc)
    except RestoreError as exc:
        return all_items(REVERT_ERROR, f"ERROR GRAVE: {exc}", exc)
    return all_items(REVERT_RESTORED)


def _revert_ogg(record: dict, items: list[dict], path: Path, dry_run: bool) -> list[RevertResult]:
    current_sha = file_sha256(path)
    if current_sha == record.get("old_sha"):
        return [RevertResult(item, REVERT_ALREADY, "Ya está como el original.") for item in items]
    if current_sha != record.get("new_sha"):
        return [RevertResult(item, REVERT_CONFLICT, "El archivo cambió después de normalizarlo; no se toca.")
                for item in items]
    if dry_run:
        return [RevertResult(item, REVERT_RESTORED, "Se restauraría.") for item in items]
    editor = open_editor(path)
    values = {(item["slot"]["key"], item["slot"]["index"]): _python_value(item["original_value"])
              for item in items}
    expected = {(s.key, s.index): values.get((s.key, s.index), s.value) for s in editor.slots()}
    rewrite_with(path, file_signature(path), lambda tmp: OggEditor.modify(tmp, values),
                 lambda original, tmp: editor.check(original, tmp, expected))
    _restore_mtime(path, record)
    message = "" if file_sha256(path) == record["old_sha"] else \
        "Audio y etiquetas restaurados, pero el archivo no es idéntico en bytes al original."
    return [RevertResult(item, REVERT_RESTORED, message) for item in items]


def _restore_mtime(path: Path, record: dict) -> None:
    mtime_ns = record["signature"][1]
    os.utime(path, ns=(mtime_ns, mtime_ns))


def recover_session(folder: Path) -> list[tuple[str, str, str]]:
    """
    Resuelve las escrituras interrumpidas de una carpeta de respaldo y
    actualiza el manifiesto: una escritura que había terminado cuenta como
    aplicada; una que no empezó o se restauró, como no aplicada.
    """
    folder = Path(folder)
    if _is_run(folder):
        from choconostle.run import recover_run
        return recover_run(folder)
    manifest = load_manifest(folder)
    root = _library_root(folder, manifest)
    results = recover(folder, root)
    if not results:
        return results
    edits = {f"edit-{edit['id']:04d}": edit for edit in manifest.get("edits", [])}
    items = {item["id"]: item for item in manifest["items"]}
    for name, status, message in results:
        edit = edits.get(name)
        if edit is None:
            continue
        applied = status == RECOVERED_COMPLETE
        if status == RECOVERED_FAILED:
            edit["error"] = message
            continue
        edit["status"] = ITEM_APPLIED if applied else ITEM_FAILED
        edit["error"] = None if applied else f"interrumpida: {message}"
        for item_id in edit["items"]:
            items[item_id]["status"] = edit["status"]
            items[item_id]["error"] = edit["error"]
    path = folder / MANIFEST_NAME
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return results


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
