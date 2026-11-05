"""
gallery.py

Comando fix-gallery: crea un archivo vacío .nomedia en las carpetas de
álbum para que las apps de galería no muestren las portadas. No abre ni
modifica audio, letras ni etiquetas (solo lee la etiqueta de álbum cuando
--only indica un nombre de álbum).

- Por defecto solo simula. Con apply=True crea los .nomedia.
- Solo en carpetas con imágenes, o en todas las que tienen audio con
  all_folders=True.
- La carpeta indicada no se toca si es una raíz (tiene subcarpetas con
  audio), ni tampoco Music, Pictures, DCIM o Download, salvo con
  include_root=True. Si la carpeta indicada tiene audio y ninguna
  subcarpeta con audio, es un álbum y se trata como tal.
- Lo creado se anota en ChoconostleLRCTool_back/fix-gallery_creados.json.
  remove=True quita solo esos archivos, nunca un .nomedia que ya existía.

Autor: AndrewSkarlet
Licencia: MIT
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from choconostle import run as runs
from choconostle.config import BACKUP_DIR_NAME, SUPPORTED_AUDIO
from choconostle.utils import long_path

NOMEDIA = ".nomedia"
RECORD_NAME = "fix-gallery_creados.json"
GALLERY_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
PROTECTED_NAMES = {"music", "pictures", "dcim", "download"}
# Cada cuántas carpetas se guarda la lista de lo creado.
BATCH = 50

CREATED = "creado"
PENDING = "pendiente"  # anotado antes de crearlo; se confirma al releer

_AUDIO = {ext.lower() for ext in SUPPORTED_AUDIO}


class GalleryStop(Exception):
    """La unidad dejó de responder o se llenó: hay que salir con código 3."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass
class FolderInfo:
    path: Path
    rel: str
    has_audio: bool
    has_images: bool
    has_nomedia: bool


@dataclass
class GalleryResult:
    reviewed: int = 0
    created: list[str] = field(default_factory=list)      # o «se crearían» en la simulación
    existing: list[str] = field(default_factory=list)
    protected: list[tuple[str, str]] = field(default_factory=list)
    not_matching: int = 0                                 # sin imágenes (o sin audio con all_folders)
    errors: list[tuple[str, str]] = field(default_factory=list)
    root_note: str | None = None
    missing_albums: list[str] = field(default_factory=list)
    stopped: GalleryStop | None = None
    record_error: str | None = None
    # --remove
    removed: list[str] = field(default_factory=list)       # o «se quitarían»
    gone: list[str] = field(default_factory=list)          # ya no estaba
    kept: list[tuple[str, str]] = field(default_factory=list)

    @property
    def skipped(self) -> int:
        return self.not_matching + len(self.protected)


# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------

def _rel(path: Path, root: Path) -> str:
    if path == root:
        return "."
    return "/".join(path.relative_to(root).parts)


def _from_rel(root: Path, rel: str) -> Path | None:
    if rel == ".":
        return root
    parts = rel.split("/")
    if any(part in ("", ".", "..") for part in parts) or Path(rel).is_absolute():
        return None  # entrada no válida: nunca fuera de la biblioteca
    return root.joinpath(*parts)


def record_path(root: Path) -> Path:
    return Path(root) / BACKUP_DIR_NAME / RECORD_NAME


def _stop_for(exc: BaseException, root: Path) -> GalleryStop | None:
    kind = runs.fatal_kind(exc, root, backups=False)
    if kind == "space":
        return GalleryStop(kind, f"fix-gallery se detuvo: no queda espacio libre ({exc}).")
    if kind == "device":
        return GalleryStop(kind, f"fix-gallery se detuvo: la biblioteca dejó de estar accesible "
                                 f"(¿se desconectó la tarjeta SD?) ({exc}).")
    return None


def _check_reachable(root: Path) -> None:
    if not runs.reachable(root, backups=False):
        raise GalleryStop("device", "fix-gallery se detuvo: la biblioteca dejó de estar accesible "
                                    "(¿se desconectó la tarjeta SD?).")


# --------------------------------------------------------------------------
# Recorrido
# --------------------------------------------------------------------------

def _scan_dir(folder: Path, root: Path, include_hidden: bool):
    """(subcarpetas, nombres de archivo) de una carpeta, ordenados."""
    dirs, files = [], []
    with os.scandir(long_path(folder)) as entries:
        for entry in entries:
            name = entry.name
            if name.startswith(".") and name != NOMEDIA and not include_hidden:
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir:
                if folder == root and name == BACKUP_DIR_NAME:
                    continue
                if name.startswith(".") and not include_hidden:
                    continue
                dirs.append(name)
            else:
                files.append(name)
    return sorted(dirs, key=str.lower), sorted(files, key=str.lower)


def _album_names(folder: Path, files: list[str]) -> set[str]:
    """Etiquetas de álbum (en minúsculas) de los archivos de audio de la carpeta. Solo lee."""
    import mutagen
    names = set()
    for name in files:
        if Path(name).suffix.lower() not in _AUDIO:
            continue
        try:
            audio = mutagen.File(long_path(folder / name), easy=True)
            for value in (audio.tags.get("album") if audio is not None and audio.tags else None) or []:
                names.add(str(value).strip().lower())
        except Exception:  # etiquetas ilegibles: la carpeta simplemente no coincide
            continue
    return names


def collect(root: Path, only: list[str] | None = None, include_hidden: bool = False,
            on_folder=None) -> tuple[list[FolderInfo], list[str], list[tuple[str, str]], bool]:
    """
    Recorre la biblioteca (o lo que indique --only) y devuelve
    (carpetas, álbumes no encontrados, errores, la raíz tiene subcarpetas con audio).
    """
    root = Path(root)
    folders, albums = runs.resolve_only(root, only or [])
    starts = [root] if albums or not folders else folders
    infos: list[FolderInfo] = []
    errors: list[tuple[str, str]] = []
    found_albums: set[str] = set()
    root_has_audio_below = False
    seen: set[Path] = set()
    for start in starts:
        stack = [Path(start)]
        while stack:
            folder = stack.pop()
            if folder in seen:
                continue
            seen.add(folder)
            _check_reachable(root)
            try:
                dirs, files = _scan_dir(folder, root, include_hidden)
            except OSError as exc:
                stop = _stop_for(exc, root)
                if stop:
                    raise stop from exc
                errors.append((_rel(folder, root), f"no se pudo leer la carpeta: {exc}"))
                continue
            lower = [name.lower() for name in files]
            has_audio = any(Path(n).suffix in _AUDIO for n in lower)
            info = FolderInfo(
                path=folder, rel=_rel(folder, root), has_audio=has_audio,
                has_images=any(Path(n).suffix in GALLERY_IMAGES for n in lower),
                has_nomedia=NOMEDIA in lower,
            )
            if has_audio and folder != root:
                root_has_audio_below = True
            selected = True
            if albums:
                names = _album_names(folder, files) & albums
                found_albums |= names
                in_folders = any(folder == f or f in folder.parents for f in folders)
                selected = bool(names) or in_folders
            if selected:
                infos.append(info)
            if on_folder is not None:
                on_folder(len(seen))
            stack.extend(folder / name for name in reversed(dirs))
    if folders and not albums and root not in folders:
        # Con --only de carpetas no se recorre el resto: la raíz no está en juego.
        root_has_audio_below = True
    return infos, sorted(albums - found_albums), errors, root_has_audio_below


# --------------------------------------------------------------------------
# Lista de lo creado
# --------------------------------------------------------------------------

def load_record(root: Path) -> dict[str, str]:
    path = record_path(root)
    try:
        with open(long_path(path), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    entries = data.get("carpetas", {}) if isinstance(data, dict) else {}
    return {str(k): str(v) for k, v in entries.items() if v in (CREATED, PENDING)}


def save_record(root: Path, entries: dict[str, str]) -> None:
    path = record_path(root)
    os.makedirs(long_path(path.parent), exist_ok=True)
    runs.write_json_atomic(path, {
        "comando": "fix-gallery",
        "descripcion": "Carpetas en las que fix-gallery creó .nomedia. --remove solo quita estos.",
        "carpetas": dict(sorted(entries.items())),
    })


def _nomedia_state(folder: Path) -> str:
    """"vacío", "con contenido" o "no existe"."""
    try:
        info = os.stat(long_path(folder / NOMEDIA))
    except FileNotFoundError:
        return "no existe"
    if not stat.S_ISREG(info.st_mode) or info.st_size:
        return "con contenido"
    return "vacío"


def _reconcile(root: Path, entries: dict[str, str]) -> bool:
    """
    Las entradas «pendiente» quedan si una ejecución se cortó entre anotar
    y crear. Se confirman si el .nomedia existe y está vacío (antes de
    anotarlo se comprobó que no existía) y se descartan si no existe.
    Devuelve True si algo cambió.
    """
    changed = False
    for rel, state in list(entries.items()):
        if state != PENDING:
            continue
        folder = _from_rel(root, rel)
        if folder is not None and _nomedia_state(folder) == "vacío":
            entries[rel] = CREATED
        else:
            del entries[rel]
        changed = True
    return changed


# --------------------------------------------------------------------------
# Crear
# --------------------------------------------------------------------------

def plan(root: Path, infos: list[FolderInfo], root_has_audio_below: bool, all_folders: bool,
         include_root: bool, result: GalleryResult) -> list[FolderInfo]:
    """Clasifica las carpetas; devuelve las que recibirían .nomedia."""
    targets = []
    for info in infos:
        result.reviewed += 1
        wanted = info.has_audio if all_folders else info.has_images
        if not wanted:
            result.not_matching += 1
            continue
        reason = None
        if not include_root:
            if info.path == root and root_has_audio_below:
                reason = "carpeta raíz de la biblioteca (tiene subcarpetas con audio)"
            elif info.path.name.lower() in PROTECTED_NAMES:
                reason = f"carpeta de sistema ({info.path.name})"
        if reason:
            result.protected.append((info.rel, reason))
            if info.path == root:
                result.root_note = f"La carpeta raíz queda fuera: {reason}. Usa --include-root para incluirla."
            continue
        if info.has_nomedia:
            result.existing.append(info.rel)
            continue
        targets.append(info)
    return targets


def run_create(root: Path, only: list[str] | None = None, apply: bool = False, all_folders: bool = False,
               include_root: bool = False, include_hidden: bool = False, progress=None) -> GalleryResult:
    root = Path(root)
    result = GalleryResult()
    progress = progress or _NoProgress()
    try:
        progress.searching()
        infos, missing, errors, below = collect(root, only, include_hidden, progress.found)
        result.errors.extend(errors)
        result.missing_albums = missing
        if missing:
            return result
        progress.start("Revisando", len(infos))
        targets = plan(root, infos, below, all_folders, include_root, result)
        progress.advance(len(infos))
        if not apply:
            result.created = [info.rel for info in targets]
            return result
        entries = load_record(root)
        if _reconcile(root, entries):
            save_record(root, entries)
        progress.start("Creando .nomedia", len(targets))
        for start in range(0, len(targets), BATCH):
            batch = targets[start:start + BATCH]
            for info in batch:
                entries[info.rel] = PENDING
            save_record(root, entries)
            try:
                for info in batch:
                    _create_one(root, info, entries, result)
                    progress.advance(1)
            except BaseException:
                # Se intenta guardar lo hecho; si la unidad ya no está, las
                # entradas «pendiente» guardadas antes se confirman al repetir.
                try:
                    save_record(root, entries)
                except OSError as exc:
                    result.record_error = str(exc)
                raise
            save_record(root, entries)
    except GalleryStop as stop:
        result.stopped = stop
    except OSError as exc:
        stop = _stop_for(exc, root)
        if stop is None:
            raise
        result.stopped = stop
    finally:
        progress.stop()
    return result


def _create_one(root: Path, info: FolderInfo, entries: dict[str, str], result: GalleryResult) -> None:
    try:
        # "x": falla si ya existe; así nunca se anota uno que no creó esta herramienta.
        with open(long_path(info.path / NOMEDIA), "x"):
            pass
    except FileExistsError:
        entries.pop(info.rel, None)
        result.existing.append(info.rel)
        return
    except OSError as exc:
        entries.pop(info.rel, None)
        stop = _stop_for(exc, root)
        if stop:
            raise stop from exc
        result.errors.append((info.rel, str(exc)))
        return
    entries[info.rel] = CREATED
    result.created.append(info.rel)


# --------------------------------------------------------------------------
# Quitar
# --------------------------------------------------------------------------

def run_remove(root: Path, only: list[str] | None = None, apply: bool = False, include_hidden: bool = False,
               progress=None) -> GalleryResult:
    root = Path(root)
    result = GalleryResult()
    progress = progress or _NoProgress()
    entries: dict[str, str] | None = None
    changed = False
    try:
        _check_reachable(root)
        entries = load_record(root)
        if apply:
            changed = _reconcile(root, entries)
        scope = None
        if only:
            progress.searching()
            infos, missing, errors, _below = collect(root, only, include_hidden, progress.found)
            result.errors.extend(errors)
            result.missing_albums = missing
            if missing:
                return result
            scope = {info.rel for info in infos}
        selected = [rel for rel in entries if scope is None or rel in scope]
        progress.start("Quitando .nomedia" if apply else "Revisando", len(selected))
        for rel in selected:
            result.reviewed += 1
            folder = _from_rel(root, rel)
            if folder is None:
                result.kept.append((rel, "entrada no válida en la lista; no se toca"))
                progress.advance(1)
                continue
            try:
                state = _nomedia_state(folder)
                if state == "no existe":
                    result.gone.append(rel)
                    if apply:
                        del entries[rel]
                        changed = True
                elif state == "con contenido":
                    result.kept.append((rel, "el .nomedia tiene contenido: no es el que creó fix-gallery"))
                elif entries[rel] == PENDING:  # solo en simulación (con apply ya se reconcilió)
                    result.removed.append(rel)
                else:
                    if apply:
                        os.unlink(long_path(folder / NOMEDIA))
                        del entries[rel]
                        changed = True
                    result.removed.append(rel)
            except OSError as exc:
                stop = _stop_for(exc, root)
                if stop:
                    raise stop from exc
                result.errors.append((rel, str(exc)))
            progress.advance(1)
    except GalleryStop as stop:
        result.stopped = stop
    except OSError as exc:
        stop = _stop_for(exc, root)
        if stop is None:
            raise
        result.stopped = stop
    finally:
        progress.stop()
        if apply and changed and entries is not None:
            try:
                save_record(root, entries)
            except OSError as exc:
                # Si no se pudo guardar, la próxima vez esas entradas salen como «ya no estaba».
                result.record_error = str(exc)
                if result.stopped is None:
                    result.stopped = _stop_for(exc, root)
    return result


class _NoProgress:
    def searching(self) -> None:
        pass

    def found(self, count: int) -> None:
        pass

    def start(self, description: str, total: int) -> None:
        pass

    def advance(self, count: int) -> None:
        pass

    def stop(self) -> None:
        pass
