"""
embedded.py

Letras incrustadas en las etiquetas del audio: elige el editor de cada
formato.

- ID3 (MP3, WAV, AIFF): rawtags.id3, byte a byte.
- Comentarios Vorbis en FLAC: rawtags.flac, byte a byte.
- Comentarios Vorbis en Ogg (Opus, Vorbis): rawtags.ogg, reescritura
  completa verificada.
- MP4 (M4A/ALAC/AAC): rawtags.mp4, byte a byte.
- APEv2 (APE, WavPack): rawtags.apev2, byte a byte.
- Matroska (.mka): solo lectura.

Autor: AndrewSkarlet
Licencia: MIT
"""

from __future__ import annotations

from pathlib import Path

from mutagen.apev2 import APEv2
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4Tags

from choconostle.audio import is_matroska, open_audio
from choconostle.rawtags import Slot, Unsupported
from choconostle.rawtags.apev2 import open_apev2
from choconostle.rawtags.flac import open_flac
from choconostle.rawtags.id3 import open_id3
from choconostle.rawtags.mp4 import open_mp4
from choconostle.rawtags.ogg import OggEditor

try:  # VCommentDict vive en un módulo interno de mutagen.
    from mutagen._vorbis import VCommentDict
except ImportError:  # pragma: no cover
    VCommentDict = None

EmbeddedError = Unsupported

__all__ = ["EmbeddedError", "Slot", "open_editor"]


def open_editor(path: Path):
    """
    Editor de letras del archivo, o None si no tiene etiquetas.

    Lanza Unsupported (con el motivo) si el formato no se puede editar de
    forma segura.
    """
    path = Path(path)
    if is_matroska(path):
        raise Unsupported("matroska")
    audio = open_audio(path)
    if audio is None:
        raise Unsupported("no_tags", "formato no reconocido")
    tags = audio.tags
    if tags is None:
        return None
    if isinstance(tags, ID3):
        return open_id3(path)
    if VCommentDict is not None and isinstance(tags, VCommentDict):
        if isinstance(audio, FLAC):
            return open_flac(path)
        return OggEditor(path, audio)
    if isinstance(tags, MP4Tags):
        return open_mp4(path)
    if isinstance(tags, APEv2):
        return open_apev2(path)
    raise Unsupported("no_tags")
