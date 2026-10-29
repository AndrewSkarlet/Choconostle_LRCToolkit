"""
rawtags/writer.py

Escritura segura de la región de etiquetas de un archivo de audio.

Antes de escribir:
- el archivo debe seguir igual que al planificar (tamaño, fecha de
  modificación y bytes de la región);
- se calcula el hash de todo lo que está fuera de la región (el audio y
  el resto del archivo);
- se guarda en el diario (carpeta "pendiente" del respaldo) la parte de
  la región que se va a sobrescribir, con fsync.

Después de escribir se relee el archivo: la región debe ser la prevista,
su estructura debe conservar todo lo que no es letra y el hash de fuera
de la región no debe cambiar. Si algo no coincide, se restaura el
original y se informa del error.

Si la escritura se interrumpe (corte de luz, tarjeta SD desconectada),
recover() usa el diario para dejar el archivo como estaba.

La reescritura completa (cuando el audio tiene que desplazarse) se hace
en un archivo temporal junto al original y se reemplaza de forma atómica.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from choconostle.rawtags import MODE_FULL, apply_patches, sha256
from choconostle.utils import long_path

JOURNAL_DIR = "pendiente"
VERIFY_FULL = "full"
"""Se calcula el hash de todo el archivo fuera de la región, antes y después."""
VERIFY_AUTO = "auto"
"""quick si el audio no se escribe (edición en su sitio o al final), full si se reescribe el archivo."""
VERIFY_QUICK = "quick"
"""Del resto del archivo solo se comparan el tamaño, el primer y el último MB."""
_SAMPLE = 1 << 20
TEMP_SUFFIX = ".choconostle-tmp"
_CHUNK = 1 << 20
_SPACE_MARGIN = 1 << 20


class WriteError(Exception):
    """La escritura falló o no pasó la verificación; el archivo quedó como el original."""


class RestoreError(Exception):
    """La escritura falló y no se pudo restaurar el original. El diario se conserva."""


class ChangedError(WriteError):
    """El archivo cambió desde la planificación; no se tocó."""


def _write(handle, data: bytes) -> None:
    """Escribe datos (punto único para simular interrupciones en las pruebas)."""
    handle.write(data)


def _fsync_dir(folder: Path) -> None:
    try:
        descriptor = os.open(folder, os.O_RDONLY)
    except OSError:  # Windows no permite abrir carpetas
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def read_at(path: Path, start: int, length: int) -> bytes:
    with open(long_path(path), "rb") as handle:
        handle.seek(start)
        return handle.read(length)


def outside_hash(path: Path, start: int, length: int, verify: str = VERIFY_FULL) -> str:
    """
    SHA-256 de todo el archivo salvo los bytes [start, start + length).

    Con VERIFY_QUICK solo se usan el tamaño de esa parte, su primer MB y
    su último MB.
    """
    if verify == VERIFY_QUICK:
        return _outside_sample(path, start, length)
    digest = hashlib.sha256()
    with open(long_path(path), "rb") as handle:
        remaining = start
        while remaining > 0:
            chunk = handle.read(min(_CHUNK, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
        handle.seek(start + length)
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _outside_sample(path: Path, start: int, length: int) -> str:
    size = os.stat(long_path(path)).st_size
    segments = [(0, start), (start + length, size - start - length)]
    total = sum(n for _o, n in segments)

    def read_range(first: int, count: int) -> bytes:
        """Bytes [first, first + count) de la parte de fuera de la región."""
        out = []
        position = 0
        with open(long_path(path), "rb") as handle:
            for offset, n in segments:
                low, high = max(first, position), min(first + count, position + n)
                if low < high:
                    handle.seek(offset + low - position)
                    out.append(handle.read(high - low))
                position += n
        return b"".join(out)
    digest = hashlib.sha256(str(total).encode())
    digest.update(read_range(0, min(_SAMPLE, total)))
    digest.update(read_range(max(0, total - _SAMPLE), min(_SAMPLE, total)))
    return digest.hexdigest()


def effective_verify(verify: str, mode: str) -> str:
    """Verificación que corresponde a una edición: auto elige según si se reescribe el archivo."""
    if verify == VERIFY_AUTO:
        return VERIFY_FULL if mode == MODE_FULL else VERIFY_QUICK
    return verify


def file_signature(path: Path) -> tuple[int, int]:
    info = os.stat(long_path(path))
    return info.st_size, info.st_mtime_ns


def _common_prefix(a: bytes, b: bytes) -> int:
    limit = min(len(a), len(b))
    low, high = 0, limit
    while low < high:  # búsqueda binaria sobre comparaciones de bloques
        middle = (low + high + 1) // 2
        if a[:middle] == b[:middle]:
            low = middle
        else:
            high = middle - 1
    return low


# --------------------------------------------------------------------------
# Diario
# --------------------------------------------------------------------------

class Journal:
    """Copias previas de las regiones que se están escribiendo."""

    def __init__(self, backup_folder: Path):
        self.folder = Path(backup_folder) / JOURNAL_DIR

    def begin(self, name: str, record: dict, preimage: bytes) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        for suffix, data in ((".bin", preimage), (".json", json.dumps(record, ensure_ascii=False).encode())):
            target = self.folder / (name + suffix)
            with open(target, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        _fsync_dir(self.folder)

    def end(self, name: str) -> None:
        for suffix in (".json", ".bin"):
            target = self.folder / (name + suffix)
            if target.exists():
                target.unlink()
        _fsync_dir(self.folder)

    def pending(self) -> list[tuple[str, dict]]:
        if not self.folder.is_dir():
            return []
        found = []
        for path in sorted(self.folder.glob("*.json")):
            found.append((path.stem, json.loads(path.read_text(encoding="utf-8"))))
        return found

    def preimage(self, name: str) -> bytes:
        return (self.folder / (name + ".bin")).read_bytes()


# --------------------------------------------------------------------------
# Escritura
# --------------------------------------------------------------------------

def write_edit(path: Path, editor, edit, journal: Journal, name: str,
               signature: tuple[int, int], root_path: str | None = None,
               verify: str = VERIFY_FULL) -> dict:
    """
    Aplica `edit` (calculada sobre `editor.region`) al archivo.

    Retorna un resumen {old_sha, new_sha, size_before, size_after, outside}.
    Lanza ChangedError, WriteError o RestoreError.
    """
    path = Path(path)
    if file_signature(path) != tuple(signature):
        raise ChangedError("el archivo cambió desde que se planearon los cambios")
    old = editor.region
    if read_at(path, editor.start, len(old)) != old:
        raise ChangedError("las etiquetas cambiaron desde que se planearon los cambios")
    new = apply_patches(old, edit.patches)
    problems = editor.verify(new, edit.expected)
    if problems:
        raise WriteError("la edición calculada no es segura: " + "; ".join(problems))

    before = outside_hash(path, editor.start, len(old), verify)
    size_before = signature[0]
    size_after = size_before + len(new) - len(old)
    summary = {"old_sha": sha256(old), "new_sha": sha256(new), "size_before": size_before,
               "mtime_ns": signature[1],
               "size_after": size_after, "outside": before, "start": editor.start,
               "old_len": len(old), "new_len": len(new), "verify": verify}
    if edit.mode == MODE_FULL:
        _rewrite_file(path, editor.start, len(old), new, before,
                      lambda candidate: _check(candidate, editor.start, new, before, editor, edit, verify))
        return summary

    if not editor.at_eof and len(new) != len(old):
        raise WriteError("la región cambiaría de tamaño en medio del archivo")
    first = _common_prefix(old, new)
    record = dict(summary, path=root_path or str(path), first=first)
    journal.begin(name, record, old[first:])
    try:
        with open(long_path(path), "r+b") as handle:
            handle.seek(editor.start + first)
            _write(handle, new[first:])
            if len(new) < len(old):
                handle.truncate(editor.start + len(new))
            handle.flush()
            os.fsync(handle.fileno())
        problems = _check(path, editor.start, new, before, editor, edit, verify)
    except Exception as exc:  # noqa: BLE001 - se restaura ante cualquier fallo de escritura
        _restore(path, record, old[first:], journal, name)
        raise WriteError(f"no se pudo escribir ({exc}); se restauró el original") from exc
    if problems:
        _restore(path, record, old[first:], journal, name)
        raise WriteError("la verificación tras escribir falló (" + "; ".join(problems)
                         + "); se restauró el original")
    journal.end(name)
    return summary


def _check(path: Path, start: int, new: bytes, before: str, editor, edit, verify: str = VERIFY_FULL) -> list[str]:
    """Relee el archivo y compara región, estructura y hash de fuera de la región."""
    problems = []
    written = read_at(path, start, len(new))
    if written != new:
        problems.append("la región escrita no coincide")
    else:
        problems += editor.verify(written, edit.expected)
    if outside_hash(path, start, len(new), verify) != before:
        problems.append("cambió el audio o el resto del archivo")
    return problems


def _restore(path: Path, record: dict, preimage: bytes, journal: Journal, name: str) -> None:
    """Vuelve a escribir los bytes originales y lo comprueba. Si no puede, conserva el diario."""
    try:
        with open(long_path(path), "r+b") as handle:
            handle.seek(record["start"] + record["first"])
            _write(handle, preimage)
            handle.truncate(record["size_before"])
            handle.flush()
            os.fsync(handle.fileno())
        if record.get("mtime_ns"):
            # Bytes y fecha como antes: así la comprobación "no cambió desde la
            # planificación" sigue valiendo al reanudar.
            os.utime(long_path(path), ns=(record["mtime_ns"], record["mtime_ns"]))
        region = read_at(path, record["start"], record["old_len"])
        ok = (sha256(region) == record["old_sha"]
              and os.stat(long_path(path)).st_size == record["size_before"]
              and outside_hash(path, record["start"], record["old_len"],
                               record.get("verify", VERIFY_FULL)) == record["outside"])
    except OSError as exc:
        raise RestoreError(f"no se pudo restaurar {path}: {exc}. "
                           f"El diario de recuperación se conserva en {journal.folder}.") from exc
    if not ok:
        raise RestoreError(f"la restauración de {path} no quedó idéntica al original. "
                           f"El diario de recuperación se conserva en {journal.folder}.")
    journal.end(name)


def required_space(size_after: int) -> int:
    return size_after + _SPACE_MARGIN


def _rewrite_file(path: Path, start: int, old_len: int, new: bytes, before: str, check) -> None:
    """Reescribe el archivo completo en un temporal y lo reemplaza de forma atómica."""
    size = os.stat(long_path(path)).st_size
    need = required_space(size + len(new) - old_len)
    free = shutil.disk_usage(long_path(path.parent)).free
    if free < need:
        raise WriteError(f"espacio insuficiente para la reescritura completa: requiere {need} bytes, "
                         f"hay {free}")
    temporary = path.with_name(path.name + TEMP_SUFFIX)
    try:
        with open(long_path(path), "rb") as source, open(long_path(temporary), "wb") as target:
            remaining = start
            while remaining > 0:
                chunk = source.read(min(_CHUNK, remaining))
                target.write(chunk)
                remaining -= len(chunk)
            target.write(new)
            source.seek(start + old_len)
            while chunk := source.read(_CHUNK):
                _write(target, chunk)
            target.flush()
            os.fsync(target.fileno())
        shutil.copymode(long_path(path), long_path(temporary))
        problems = check(temporary)
        if problems:
            raise WriteError("la verificación de la copia falló: " + "; ".join(problems))
        os.replace(long_path(temporary), long_path(path))
        _fsync_dir(path.parent)
    except OSError as exc:
        raise WriteError(f"no se pudo reescribir el archivo ({exc}); el original no cambió") from exc
    finally:
        if os.path.exists(long_path(temporary)):
            os.unlink(long_path(temporary))


def rewrite_with(path: Path, signature: tuple[int, int], modify, check) -> dict:
    """
    Reescritura completa delegada (Ogg con mutagen): copia el archivo a un
    temporal, `modify(temporal)` lo cambia, `check(original, temporal)`
    devuelve problemas, y si no hay ninguno se reemplaza el original.
    """
    path = Path(path)
    if file_signature(path) != tuple(signature):
        raise ChangedError("el archivo cambió desde que se planearon los cambios")
    size = signature[0]
    need = required_space(size)
    free = shutil.disk_usage(long_path(path.parent)).free
    if free < need:
        raise WriteError(f"espacio insuficiente para la reescritura completa: requiere {need} bytes, hay {free}")
    original_sha = file_sha256(path)
    temporary = path.with_name(path.name + TEMP_SUFFIX)
    try:
        shutil.copyfile(long_path(path), long_path(temporary))
        shutil.copymode(long_path(path), long_path(temporary))
        modify(temporary)
        with open(long_path(temporary), "rb+") as handle:
            os.fsync(handle.fileno())
        problems = check(path, temporary)
        if problems:
            raise WriteError("la verificación de la copia falló: " + "; ".join(problems))
        new_sha = file_sha256(temporary)
        size_after = os.stat(long_path(temporary)).st_size
        os.replace(long_path(temporary), long_path(path))
        _fsync_dir(path.parent)
    except OSError as exc:
        raise WriteError(f"no se pudo reescribir el archivo ({exc}); el original no cambió") from exc
    finally:
        if os.path.exists(long_path(temporary)):
            os.unlink(long_path(temporary))
    return {"old_sha": original_sha, "new_sha": new_sha, "size_before": size, "size_after": size_after}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(long_path(path), "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# Recuperación
# --------------------------------------------------------------------------

RECOVERED_COMPLETE = "complete"
RECOVERED_UNTOUCHED = "untouched"
RECOVERED_RESTORED = "restored"
RECOVERED_FAILED = "failed"


def recover(backup_folder: Path, root: Path) -> list[tuple[str, str, str]]:
    """
    Resuelve las escrituras interrumpidas de una carpeta de respaldo.

    Retorna [(nombre, estado, mensaje)]: la escritura había terminado
    (complete), no había empezado (untouched), o el archivo quedó a medias
    y se restauró el original (restored). Si no se puede, el diario se
    conserva (failed).
    """
    journal = Journal(backup_folder)
    results = []
    for name, record in journal.pending():
        path = Path(record["path"])
        if not path.is_absolute():
            path = Path(root) / path
        try:
            size = os.stat(long_path(path)).st_size
            new_region = read_at(path, record["start"], record["new_len"])
            old_region = read_at(path, record["start"], record["old_len"])
            if size == record["size_after"] and sha256(new_region) == record["new_sha"] \
                    and outside_hash(path, record["start"], record["new_len"],
                                     record.get("verify", VERIFY_FULL)) == record["outside"]:
                journal.end(name)
                results.append((name, RECOVERED_COMPLETE, "la escritura había terminado"))
                continue
            if size == record["size_before"] and sha256(old_region) == record["old_sha"]:
                journal.end(name)
                results.append((name, RECOVERED_UNTOUCHED, "no se había modificado"))
                continue
            _restore(path, record, journal.preimage(name), journal, name)
            results.append((name, RECOVERED_RESTORED, "escritura interrumpida: se restauró el original"))
        except (OSError, RestoreError) as exc:
            results.append((name, RECOVERED_FAILED, str(exc)))
        # Copias temporales de reescrituras completas que no llegaron a reemplazar.
        temporary = path.with_name(path.name + TEMP_SUFFIX)
        if os.path.exists(long_path(temporary)):
            os.unlink(long_path(temporary))
    return results
