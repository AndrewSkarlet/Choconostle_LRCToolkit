"""
legacy_embedded.py

Lectura y escritura de letras incrustadas con mutagen (v0.2.0).

Desde la v0.3.0 las letras se escriben byte a byte (paquete rawtags).
Este módulo se conserva solo para revertir respaldos creados por la
v0.2.0, cuyo manifiesto guarda los valores de las etiquetas.

Cada letra incrustada se identifica con un "slot":
(formato de etiqueta, clave, índice). Solo se modifican esos valores;
el resto de las etiquetas y el audio no se tocan.

Formatos que se pueden escribir:
- ID3 (MP3, WAV, AIFF): USLT, SYLT, TXXX:LYRICS...
- Vorbis Comment (FLAC, Ogg Vorbis, Opus, Ogg FLAC): LYRICS, UNSYNCEDLYRICS...
- MP4 (M4A/ALAC/AAC): ©lyr
- APEv2 (APE, WavPack): Lyrics, UNSYNCEDLYRICS...

Matroska (.mka) solo se puede leer.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen.apev2 import APEv2, BINARY
from mutagen.id3 import ID3, Encoding
from mutagen.mp4 import MP4Tags

from choconostle.audio import is_matroska, open_audio
from choconostle.tags import LYRICS_KEYS

try:  # VCommentDict vive en un módulo interno de mutagen.
    from mutagen._vorbis import VCommentDict
except ImportError:  # pragma: no cover
    VCommentDict = None

FORMAT_ID3 = "id3"
FORMAT_VORBIS = "vorbis"
FORMAT_MP4 = "mp4"
FORMAT_APEV2 = "apev2"

MP4_LYRICS_KEY = "\xa9lyr"


class EmbeddedError(Exception):
    """No se pueden leer o escribir las letras incrustadas de este archivo."""


@dataclass
class Slot:
    """Una letra incrustada concreta dentro de un archivo de audio."""
    tag_format: str
    key: str
    """Clave exacta: "USLT::spa", "SYLT::eng", "TXXX:LYRICS", "LYRICS", "©lyr"..."""
    index: int
    """Índice entre los valores con la misma clave (Vorbis y MP4 permiten varios)."""
    label: str
    """Nombre corto para mostrar: USLT, SYLT, LYRICS, UNSYNCEDLYRICS, ©lyr..."""
    value: object
    """str, o lista de (texto, tiempo) para SYLT."""
    id3_encoding: int | None = None

    @property
    def is_sylt(self) -> bool:
        return self.tag_format == FORMAT_ID3 and self.key.startswith("SYLT")

    def ref(self) -> dict:
        """Identificador serializable (para el manifiesto)."""
        return {"tag_format": self.tag_format, "key": self.key, "index": self.index, "label": self.label}


class EmbeddedLyrics:
    """Archivo de audio abierto para leer y modificar sus letras incrustadas."""

    def __init__(self, path: Path):
        self.path = Path(path)
        if is_matroska(self.path):
            raise EmbeddedError("Matroska (.mka): las etiquetas solo se pueden leer, no escribir.")
        audio = open_audio(self.path)
        if audio is None:
            raise EmbeddedError("Formato no reconocido.")
        self.audio = audio
        tags = audio.tags
        if tags is None:
            self.tag_format = None
        elif isinstance(tags, ID3):
            self.tag_format = FORMAT_ID3
        elif VCommentDict is not None and isinstance(tags, VCommentDict):
            self.tag_format = FORMAT_VORBIS
        elif isinstance(tags, MP4Tags):
            self.tag_format = FORMAT_MP4
        elif isinstance(tags, APEv2):
            self.tag_format = FORMAT_APEV2
        else:
            self.tag_format = None
        self._dirty = False

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------

    def slots(self) -> list[Slot]:
        """Todas las letras incrustadas del archivo."""
        tags = self.audio.tags
        found: list[Slot] = []
        if self.tag_format == FORMAT_ID3:
            for frame in tags.values():
                frame_id = frame.FrameID
                if frame_id == "USLT":
                    found.append(Slot(FORMAT_ID3, frame.HashKey, 0, "USLT", frame.text,
                                      int(frame.encoding)))
                elif frame_id == "SYLT":
                    found.append(Slot(FORMAT_ID3, frame.HashKey, 0, "SYLT",
                                      [(text, time) for text, time in frame.text],
                                      int(frame.encoding)))
                elif frame_id == "TXXX" and (frame.desc or "").lower() in LYRICS_KEYS:
                    found.append(Slot(FORMAT_ID3, frame.HashKey, 0, f"TXXX:{frame.desc}",
                                      "\n".join(frame.text), int(frame.encoding)))
        elif self.tag_format == FORMAT_VORBIS:
            counts: dict[str, int] = {}
            for key, value in tags:
                lower = key.lower()
                if lower in LYRICS_KEYS:
                    index = counts.get(lower, 0)
                    counts[lower] = index + 1
                    found.append(Slot(FORMAT_VORBIS, lower, index, key.upper(), value))
        elif self.tag_format == FORMAT_MP4:
            for index, value in enumerate(tags.get(MP4_LYRICS_KEY, [])):
                found.append(Slot(FORMAT_MP4, MP4_LYRICS_KEY, index, MP4_LYRICS_KEY, value))
        elif self.tag_format == FORMAT_APEV2:
            for key, value in tags.items():
                if key.lower() in LYRICS_KEYS and value.kind != BINARY:
                    found.append(Slot(FORMAT_APEV2, key, 0, key, str(value)))
        return found

    def get(self, ref: dict) -> Slot | None:
        """Busca un slot por su identificador del manifiesto."""
        for slot in self.slots():
            if (slot.tag_format == ref["tag_format"] and slot.key == ref["key"]
                    and slot.index == ref["index"]):
                return slot
        return None

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------

    def set(self, ref: dict, value, id3_encoding: int | None = None) -> None:
        """Cambia el valor de un slot. No guarda hasta llamar a save()."""
        tags = self.audio.tags
        tag_format, key, index = ref["tag_format"], ref["key"], ref["index"]
        if tag_format != self.tag_format:
            raise EmbeddedError(f"El archivo ya no tiene etiquetas {tag_format}.")

        if tag_format == FORMAT_ID3:
            frame = tags.get(key)
            if frame is None:
                raise EmbeddedError(f"No existe la etiqueta {key}.")
            if frame.FrameID == "TXXX":
                # Un solo valor con saltos de línea: ID3 2.3 uniría varios con "/".
                frame.text = [value]
            elif frame.FrameID == "SYLT":
                frame.text = [(text, time) for text, time in value]
            else:
                frame.text = value
            if id3_encoding is not None:
                frame.encoding = Encoding(id3_encoding)
            elif frame.encoding == Encoding.LATIN1 and not _fits_latin1(value):
                # El texto nuevo (p. ej. un título en japonés) no cabe en Latin-1.
                frame.encoding = Encoding.UTF16 if tags.version < (2, 4, 0) else Encoding.UTF8
        elif tag_format == FORMAT_VORBIS:
            seen = 0
            for position, (existing_key, _value) in enumerate(tags):
                if existing_key.lower() == key:
                    if seen == index:
                        # Se reemplaza en su lugar: conserva el orden y la clave original.
                        # VCommentDict redefine [] por clave; se usa el de list.
                        list.__setitem__(tags, position, (existing_key, value))
                        break
                    seen += 1
            else:
                raise EmbeddedError(f"No existe la etiqueta {key.upper()} #{index + 1}.")
        elif tag_format == FORMAT_MP4:
            values = list(tags.get(key, []))
            if index >= len(values):
                raise EmbeddedError(f"No existe la etiqueta {key} #{index + 1}.")
            values[index] = value
            tags[key] = values
        elif tag_format == FORMAT_APEV2:
            if key not in tags:
                raise EmbeddedError(f"No existe la etiqueta {key}.")
            tags[key] = value
        else:
            raise EmbeddedError("Formato de etiquetas no compatible.")
        self._dirty = True

    def save(self) -> None:
        """Guarda las etiquetas. Conserva la versión de ID3 (2.3 o 2.4)."""
        if not self._dirty:
            return
        if self.tag_format == FORMAT_ID3:
            version = 3 if self.audio.tags.version < (2, 4, 0) else 4
            self.audio.save(v2_version=version)
        else:
            self.audio.save()
        self._dirty = False


def _fits_latin1(value) -> bool:
    texts = [text for text, _time in value] if isinstance(value, list) else [value]
    try:
        for text in texts:
            text.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return True
