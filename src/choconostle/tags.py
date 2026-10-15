"""
tags.py

Lectura de etiquetas incrustadas: título, artista, álbum, letras y
portada.

Formatos de etiqueta:
- ID3 (MP3, y también WAV/AIFF): USLT, SYLT, TXXX:LYRICS, APIC.
- Vorbis Comment (FLAC, Ogg Vorbis, Opus): LYRICS, UNSYNCEDLYRICS, imágenes.
- MP4 (M4A/ALAC/AAC): ©lyr, covr.
- APEv2 (APE, WavPack): Lyrics, Cover Art.
- Matroska: LYRICS y adjuntos de imagen (ver matroska.py).

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

from mutagen.apev2 import APEv2, BINARY
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4Tags

from choconostle import lrc
from choconostle.matroska import MatroskaInfo
from choconostle.models.track import Track

try:  # VCommentDict vive en un módulo interno de mutagen.
    from mutagen._vorbis import VCommentDict
except ImportError:  # pragma: no cover
    VCommentDict = None

# Nombres de campo que guardan letras (en minúsculas).
LYRICS_KEYS = {"lyrics", "unsyncedlyrics", "unsynced lyrics", "syncedlyrics", "synced lyrics"}

# Codificación de texto de los frames ID3.
ID3_ENCODINGS = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}


def _first(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _set_basic(track: Track, title=None, artist=None, album=None, album_artist=None) -> None:
    track.title = _first(title)
    track.artist = _first(artist)
    track.album = _first(album)
    track.album_artist = _first(album_artist)


def _read_id3(track: Track, id3: ID3) -> None:
    def text(frame_id):
        frame = id3.get(frame_id)
        return frame.text if frame is not None else None

    _set_basic(track, text("TIT2"), text("TPE1"), text("TALB"), text("TPE2"))

    for frame in id3.getall("USLT"):
        encoding = ID3_ENCODINGS.get(int(frame.encoding), "utf-8")
        track.lyrics.append(lrc.analyze_embedded(frame.text or "", "USLT", encoding))
    for frame in id3.getall("SYLT"):
        encoding = ID3_ENCODINGS.get(int(frame.encoding), "utf-8")
        track.lyrics.append(lrc.analyze_synced_frame(list(frame.text or []), "SYLT", encoding))
    for frame in id3.getall("TXXX"):
        if (frame.desc or "").lower() in LYRICS_KEYS:
            encoding = ID3_ENCODINGS.get(int(frame.encoding), "utf-8")
            track.lyrics.append(
                lrc.analyze_embedded("\n".join(frame.text), f"TXXX:{frame.desc}", encoding)
            )

    track.has_embedded_cover = bool(id3.getall("APIC"))


def _read_vorbis(track: Track, comments, audio) -> None:
    _set_basic(
        track,
        comments.get("title"),
        comments.get("artist"),
        comments.get("album"),
        comments.get("albumartist") or comments.get("album artist"),
    )
    for key in comments.keys():
        if key.lower() in LYRICS_KEYS:
            for value in comments[key]:
                track.lyrics.append(lrc.analyze_embedded(value, key.upper(), "utf-8"))

    has_picture = bool(getattr(audio, "pictures", None)) if isinstance(audio, FLAC) else False
    keys = {key.lower() for key in comments.keys()}
    track.has_embedded_cover = has_picture or bool(keys & {"metadata_block_picture", "coverart"})


def _read_mp4(track: Track, mp4_tags: MP4Tags) -> None:
    _set_basic(
        track,
        mp4_tags.get("\xa9nam"),
        mp4_tags.get("\xa9ART"),
        mp4_tags.get("\xa9alb"),
        mp4_tags.get("aART"),
    )
    for value in mp4_tags.get("\xa9lyr", []):
        track.lyrics.append(lrc.analyze_embedded(value, "\xa9lyr", "utf-8"))
    track.has_embedded_cover = bool(mp4_tags.get("covr"))


def _read_apev2(track: Track, ape: APEv2) -> None:
    values = {key.lower(): value for key, value in ape.items()}

    def text(*names):
        for name in names:
            value = values.get(name)
            if value is not None and value.kind != BINARY:
                return str(value).replace("\x00", " / ")
        return None

    _set_basic(
        track,
        text("title"),
        text("artist"),
        text("album"),
        text("album artist", "albumartist"),
    )
    for key, value in ape.items():
        if key.lower() in LYRICS_KEYS and value.kind != BINARY:
            track.lyrics.append(lrc.analyze_embedded(str(value), key, "utf-8"))
    track.has_embedded_cover = any(
        key.startswith("cover art") and value.kind == BINARY for key, value in values.items()
    )


def read_tags(track: Track, audio) -> None:
    """Lee etiquetas, letras y portada de un objeto de mutagen."""
    tags = audio.tags
    if tags is None:
        if isinstance(audio, FLAC):
            track.has_embedded_cover = bool(audio.pictures)
        return

    if isinstance(tags, ID3):
        _read_id3(track, tags)
    elif VCommentDict is not None and isinstance(tags, VCommentDict):
        _read_vorbis(track, tags, audio)
    elif isinstance(tags, MP4Tags):
        _read_mp4(track, tags)
    elif isinstance(tags, APEv2):
        _read_apev2(track, tags)


def read_matroska_tags(track: Track, info: MatroskaInfo) -> None:
    """Copia etiquetas, letras y portada leídas de un Matroska."""
    values = info.tags
    album_values = info.album_tags
    _set_basic(
        track,
        values.get("TITLE") or info.title,
        values.get("ARTIST"),
        values.get("ALBUM") or album_values.get("TITLE"),
        album_values.get("ARTIST") or values.get("ALBUM_ARTIST") or values.get("ALBUMARTIST"),
    )
    for key, value in values.items():
        if key.lower() in LYRICS_KEYS:
            track.lyrics.append(lrc.analyze_embedded(value, key, "utf-8"))
    track.has_embedded_cover = info.has_cover
