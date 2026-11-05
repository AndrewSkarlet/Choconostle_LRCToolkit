"""
rawtags/ogg.py

Letras en Ogg (Opus, Vorbis, FLAC en Ogg).

El comentario va en las primeras páginas Ogg; si cambia de tamaño, todas
las páginas siguientes cambian de número y de CRC. mutagen las reescribe
desplazando el resto del archivo en su sitio, algo que no es seguro ante
una interrupción. Por eso la edición es siempre una reescritura completa:
mutagen trabaja sobre una copia temporal, se verifica y se reemplaza el
original de forma atómica.

Verificación: el contenido de las páginas de audio (sin número de página
ni CRC), el vendor y los comentarios que no son letras deben quedar
iguales.

Autor: AndrewSkarlet
Licencia: MIT
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from choconostle.rawtags import MODE_FULL, Edit, Slot, Unsupported
from choconostle.tags import LYRICS_KEYS

TAG_FORMAT = "vorbis"


def audio_pages_hash(path: Path) -> str:
    """
    Hash de las páginas de audio: tipo, granule, serie, tabla de segmentos
    y datos de cada página, a partir de la primera con granule distinto de
    0 (las anteriores son cabeceras y comentarios).
    """
    digest = hashlib.sha256()
    started = False
    with open(path, "rb") as handle:
        while True:
            header = handle.read(27)
            if len(header) < 27:
                break
            if header[:4] != b"OggS":
                raise Unsupported("vorbis_invalid", "página Ogg no válida")
            header_type = header[5]
            (granule,) = struct.unpack("<q", header[6:14])
            serial = header[14:18]
            segments = header[26]
            table = handle.read(segments)
            payload = handle.read(sum(table))
            if not started and granule != 0:
                started = True
            if started:
                digest.update(bytes([header_type]) + header[6:14] + serial + bytes([segments]) + table + payload)
    return digest.hexdigest()


class OggEditor:
    """Comentarios de letra de un archivo Ogg (con mutagen)."""

    tag_format = TAG_FORMAT

    def __init__(self, path: Path, audio):
        self.path = Path(path)
        self.audio = audio
        self.file_size = self.path.stat().st_size

    def slots(self) -> list[Slot]:
        counts: dict[str, int] = {}
        found = []
        for key, value in self.audio.tags:
            lower = key.lower()
            if lower in LYRICS_KEYS:
                index = counts.get(lower, 0)
                counts[lower] = index + 1
                found.append(Slot(TAG_FORMAT, lower, index, key.upper(), value))
        return found

    def build(self, values: dict, encodings: dict | None = None) -> Edit:
        expected = {(slot.key, slot.index): values.get((slot.key, slot.index), slot.value) for slot in self.slots()}
        return Edit([], MODE_FULL, 0, 0, "Ogg: el comentario va en las primeras páginas", expected)

    @staticmethod
    def modify(path: Path, values: dict) -> None:
        """Cambia los valores en `path` (la copia temporal) y guarda con mutagen."""
        from choconostle.audio import open_audio
        audio = open_audio(path)
        seen: dict[str, int] = {}
        for position, (key, _value) in enumerate(list(audio.tags)):
            lower = key.lower()
            if lower not in LYRICS_KEYS:
                continue
            index = seen.get(lower, 0)
            seen[lower] = index + 1
            if (lower, index) in values:
                # VCommentDict redefine [] por clave; se usa el de list para conservar orden y clave.
                list.__setitem__(audio.tags, position, (key, values[(lower, index)]))
        audio.save()

    def check(self, original: Path, candidate: Path, expected: dict) -> list[str]:
        from choconostle.audio import open_audio
        problems = []
        if audio_pages_hash(original) != audio_pages_hash(candidate):
            problems.append("cambiaron las páginas de audio")
        new = open_audio(candidate)
        old_tags, new_tags = list(self.audio.tags), list(new.tags)
        if getattr(self.audio.tags, "vendor", None) != getattr(new.tags, "vendor", None):
            problems.append("cambió el vendor de los comentarios")
        plain = lambda tags: [(k, v) for k, v in tags if k.lower() not in LYRICS_KEYS]  # noqa: E731
        if plain(old_tags) != plain(new_tags):
            problems.append("cambió un comentario que no es una letra")
        if [k for k, _v in old_tags] != [k for k, _v in new_tags]:
            problems.append("cambió el orden de los comentarios")
        new_slots = {(s.key, s.index): s.value for s in OggEditor(candidate, new).slots()}
        if new_slots != expected:
            problems.append("las letras no quedaron como se esperaba")
        return problems
