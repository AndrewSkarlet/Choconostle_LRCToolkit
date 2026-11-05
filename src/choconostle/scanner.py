"""
scanner.py

Escanea una biblioteca musical y crea objetos Track.

Responsabilidades:
- Recorrer carpetas.
- Detectar archivos compatibles.
- Crear objetos Track y asociarles letras (.lrc / .txt) y portadas
  (Cover.jpg / Folder.jpg) de la misma carpeta.

Autor: AndrewSkarlet
Licencia: MIT
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from choconostle import lrc
from choconostle.audio import analyze_track
from choconostle.config import (
    BACKUP_DIR_NAME,
    COVER_NAMES,
    DISC_FOLDER_PATTERN,
    SUPPORTED_AUDIO,
    SUPPORTED_IMAGES,
    SUPPORTED_LYRICS,
    UNSUPPORTED_AUDIO,
)
from choconostle.models.lyrics import LyricsInfo
from choconostle.models.track import Track

_DISC_FOLDER_RE = re.compile(DISC_FOLDER_PATTERN, re.IGNORECASE)


@dataclass
class LibraryScan:
    """Resultado completo de un escaneo."""
    root: Path
    tracks: list[Track] = field(default_factory=list)
    orphan_lyrics: list[LyricsInfo] = field(default_factory=list)
    """Archivos .lrc sin canción con el mismo nombre."""
    unmatched_txt: list[Path] = field(default_factory=list)
    """Archivos .txt sin canción con el mismo nombre (pueden no ser letras)."""
    unsupported_audio: list[Path] = field(default_factory=list)
    folder_covers: dict[Path, list[Path]] = field(default_factory=dict)
    """Carpeta -> portadas Cover/Folder encontradas en ella."""
    walk_errors: list[str] = field(default_factory=list)
    other_files: int = 0


def is_disc_folder(folder: Path) -> bool:
    """True para subcarpetas tipo "CD1", "Disc 2", "Disco 1"."""
    return bool(_DISC_FOLDER_RE.match(folder.name))


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def create_track(file: Path) -> Track:
    """
    Convierte un archivo encontrado en un objeto Track y analiza su
    formato real y sus etiquetas.
    """
    try:
        size = file.stat().st_size
    except OSError:
        size = 0
    track = Track(
        filename=file.name,
        filepath=file,
        extension=file.suffix.lower(),
        size=size,
    )
    analyze_track(track)
    return track


@dataclass
class FolderScan:
    """Resultado de una sola carpeta (para recorrer la biblioteca por partes)."""
    folder: Path
    tracks: list[Track] = field(default_factory=list)
    orphan_lyrics: list[LyricsInfo] = field(default_factory=list)
    unmatched_txt: list[Path] = field(default_factory=list)


def count_files(directory: Path, include_hidden: bool = False, folders: list[Path] | None = None) -> int:
    """
    Cuenta rápido los archivos de audio y de letra (solo nombres, sin
    abrirlos), para mostrar el progreso con un total.
    """
    total = 0
    wanted = set(SUPPORTED_AUDIO) | set(SUPPORTED_LYRICS)
    for start in folders or [Path(directory)]:
        for _dirpath, dirnames, filenames in os.walk(start):
            _prune(dirnames, include_hidden)
            total += sum(1 for name in filenames
                         if os.path.splitext(name)[1].lower() in wanted and _visible(name, include_hidden))
    return total


def _prune(dirnames: list[str], include_hidden: bool) -> None:
    # La carpeta de respaldos tiene copias de letras: nunca se escanea.
    dirnames[:] = [name for name in dirnames if name.lower() != BACKUP_DIR_NAME.lower()]
    if not include_hidden:
        dirnames[:] = [name for name in dirnames if not _is_hidden(name)]
    dirnames.sort(key=str.lower)


def _visible(name: str, include_hidden: bool) -> bool:
    # "._cancion.flac" son metadatos de macOS, no audio.
    return not (name.startswith("._") or (not include_hidden and _is_hidden(name)))


def iter_folders(
    directory: Path,
    include_hidden: bool = False,
    on_file: Callable[[Path], None] | None = None,
    scan: LibraryScan | None = None,
    folders: list[Path] | None = None,
):
    """
    Recorre la biblioteca carpeta por carpeta y produce un FolderScan por
    cada carpeta con audio o letras. Solo guarda en memoria la carpeta
    actual; los datos globales (portadas, audio no compatible, errores)
    se acumulan en `scan` si se indica.

    `folders` limita el recorrido a esas subcarpetas.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"No es una carpeta: {directory}")
    scan = scan if scan is not None else LibraryScan(root=directory)

    def on_error(error: OSError) -> None:
        scan.walk_errors.append(f"{error.filename}: {error.strerror or error}")

    for start in folders or [directory]:
        for dirpath, dirnames, filenames in os.walk(start, onerror=on_error):
            _prune(dirnames, include_hidden)
            result = _scan_folder(Path(dirpath), filenames, include_hidden, on_file, scan)
            if result is not None:
                yield result


def _scan_folder(folder, filenames, include_hidden, on_file, scan) -> FolderScan | None:
    audio_files: list[Path] = []
    lyrics_files: list[Path] = []
    covers: list[Path] = []

    for name in sorted(filenames, key=str.lower):
        if not _visible(name, include_hidden):
            continue
        path = folder / name
        extension = path.suffix.lower()
        if extension in SUPPORTED_AUDIO:
            audio_files.append(path)
        elif extension in SUPPORTED_LYRICS:
            lyrics_files.append(path)
        elif extension in SUPPORTED_IMAGES:
            if path.stem.lower() in COVER_NAMES:
                covers.append(path)
        elif extension in UNSUPPORTED_AUDIO:
            scan.unsupported_audio.append(path)
        else:
            scan.other_files += 1

    if covers:
        scan.folder_covers[folder] = covers
    if not audio_files and not lyrics_files:
        return None

    # Portada de carpeta: la de esta carpeta, o la de la carpeta del
    # álbum si esta es una subcarpeta de disco (CD1, CD2...).
    folder_cover = covers[0] if covers else None
    if folder_cover is None and is_disc_folder(folder):
        parent_covers = _covers_in(folder.parent, scan, include_hidden)
        folder_cover = parent_covers[0] if parent_covers else None

    result = FolderScan(folder)
    audio_stems = {path.stem.lower() for path in audio_files}
    lyrics_by_stem: dict[str, list[Path]] = {}
    for path in lyrics_files:
        lyrics_by_stem.setdefault(path.stem.lower(), []).append(path)

    for path in audio_files:
        if on_file is not None:
            on_file(path)
        track = create_track(path)
        for lyrics_path in lyrics_by_stem.get(path.stem.lower(), []):
            if on_file is not None:
                on_file(lyrics_path)
            track.lyrics.append(lrc.analyze_file(lyrics_path))
        track.folder_cover = folder_cover
        result.tracks.append(track)

    for stem, paths in lyrics_by_stem.items():
        if stem in audio_stems:
            continue
        for path in paths:
            if on_file is not None:
                on_file(path)
            if path.suffix.lower() == ".lrc":
                result.orphan_lyrics.append(lrc.analyze_file(path))
            else:
                result.unmatched_txt.append(path)
    return result


def scan_directory(
    directory: Path,
    include_hidden: bool = False,
    on_file: Callable[[Path], None] | None = None,
) -> LibraryScan:
    """
    Escanea una carpeta completa y guarda todo en memoria (comando scan).

    Para recorrer bibliotecas grandes sin acumularlas, usa iter_folders().
    """
    scan = LibraryScan(root=Path(directory))
    for result in iter_folders(directory, include_hidden, on_file, scan):
        scan.tracks.extend(result.tracks)
        scan.orphan_lyrics.extend(result.orphan_lyrics)
        scan.unmatched_txt.extend(result.unmatched_txt)
    return scan


def _covers_in(folder: Path, scan: LibraryScan, include_hidden: bool) -> list[Path]:
    """Portadas Cover/Folder de una carpeta (usa lo ya escaneado si existe)."""
    if folder in scan.folder_covers:
        return scan.folder_covers[folder]
    covers: list[Path] = []
    try:
        entries = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        return covers
    for name in entries:
        if not include_hidden and _is_hidden(name):
            continue
        path = folder / name
        if path.suffix.lower() in SUPPORTED_IMAGES and path.stem.lower() in COVER_NAMES:
            covers.append(path)
    return covers
