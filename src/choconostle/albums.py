"""
albums.py

Agrupa las pistas de un escaneo en álbumes, por carpeta o por etiqueta.

Responsabilidades:
- Agrupar por carpeta (las subcarpetas CD1/CD2 cuentan como un álbum).
- Agrupar por etiqueta (artista del álbum + álbum).

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

from pathlib import Path

from choconostle.models.album import Album
from choconostle.scanner import LibraryScan, is_disc_folder

GROUP_BY_FOLDER = "folder"
GROUP_BY_TAG = "tag"


def album_folder(path: Path) -> Path:
    """Carpeta del álbum de un archivo: su carpeta, o la padre si es "CD1"."""
    folder = path.parent
    if is_disc_folder(folder):
        return folder.parent
    return folder


def _relative(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return str(path)
    return relative if relative != "." else root.name or str(root)


def group_albums(scan: LibraryScan, mode: str = GROUP_BY_FOLDER) -> list[Album]:
    """
    Agrupa las pistas en álbumes.

    En modo GROUP_BY_TAG se agrupa por artista del álbum + álbum; las
    pistas sin etiqueta de álbum se agrupan por carpeta.
    """
    albums: dict[str, Album] = {}
    for track in scan.tracks:
        if track.error:
            continue
        folder = album_folder(track.filepath)

        if mode == GROUP_BY_TAG and track.album:
            # Solo el artista del álbum: usar el de cada pista partiría las
            # compilaciones y los álbumes con artistas invitados.
            artist = track.album_artist or ""
            key = f"tag:{artist.lower()}\x00{track.album.lower()}"
            name = f"{artist} - {track.album}" if artist else track.album
        else:
            key = f"folder:{folder}"
            name = _relative(folder, scan.root)

        album = albums.get(key)
        if album is None:
            album = albums[key] = Album(key=key, name=name)
        album.tracks.append(track)
        for candidate in (folder, track.filepath.parent):
            if candidate not in album.folders:
                album.folders.append(candidate)

    for album in albums.values():
        candidates = [cover for folder in album.folders for cover in scan.folder_covers.get(folder, [])]
        # La portada asignada a cada pista cubre el caso de escanear
        # directamente una subcarpeta CD1 cuya portada está en la carpeta padre.
        candidates += [track.folder_cover for track in album.tracks if track.folder_cover]
        for cover in candidates:
            if cover not in album.folder_covers:
                album.folder_covers.append(cover)

    return sorted(albums.values(), key=lambda album: album.name.lower())
