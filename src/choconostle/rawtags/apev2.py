"""
rawtags/apev2.py

Editor byte a byte de letras en etiquetas APEv2 (WavPack, Monkey's
Audio).

El tag APEv2 está al final del archivo (opcionalmente seguido de un tag
ID3v1 de 128 bytes). Solo cambian el campo de letra y los tamaños de la
cabecera y el pie; el orden de los campos se conserva (mutagen los
ordena por tamaño). El archivo cambia de tamaño al final; el audio, que
está antes, no se mueve.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from choconostle.rawtags import MODE_TAIL, Edit, Patch, Slot, Unsupported
from choconostle.tags import LYRICS_KEYS

TAG_FORMAT = "apev2"
_PREAMBLE = b"APETAGEX"
_HAS_HEADER = 0x80000000


@dataclass
class Item:
    offset: int
    raw: bytes
    flags: int
    key: str
    value: bytes

    @property
    def is_text(self) -> bool:
        return (self.flags >> 1) & 3 == 0


@dataclass
class _Layout:
    header_offset: int | None
    footer_offset: int
    items: list[Item]
    size: int
    count: int


def _parse(region: bytes, footer_offset: int) -> _Layout:
    footer = region[footer_offset:footer_offset + 32]
    if footer[:8] != _PREAMBLE:
        raise Unsupported("ape_invalid", "falta el pie APETAGEX")
    _version, size, count, flags = struct.unpack("<4I", footer[8:24])
    items_start = footer_offset + 32 - size
    header_offset = items_start - 32 if flags & _HAS_HEADER else None
    if items_start < 0 or (header_offset is not None and header_offset < 0):
        raise Unsupported("ape_invalid", "tamaño del tag APEv2 no válido")
    if header_offset is not None and region[header_offset:header_offset + 8] != _PREAMBLE:
        raise Unsupported("ape_invalid", "falta la cabecera APETAGEX")
    items = []
    position = items_start
    for _ in range(count):
        try:
            length, item_flags = struct.unpack("<2I", region[position:position + 8])
        except struct.error as exc:
            raise Unsupported("ape_invalid", "campo APEv2 cortado") from exc
        key_end = region.find(b"\0", position + 8, footer_offset)
        if key_end < 0:
            raise Unsupported("ape_invalid", "clave APEv2 sin terminador")
        end = key_end + 1 + length
        if end > footer_offset:
            raise Unsupported("ape_invalid", "campo APEv2 más largo que el tag")
        items.append(Item(position, region[position:end], item_flags,
                          region[position + 8:key_end].decode("ascii", "replace"), region[key_end + 1:end]))
        position = end
    if position != footer_offset:
        raise Unsupported("ape_invalid", "bytes sobrantes en el tag APEv2")
    return _Layout(header_offset, footer_offset, items, size, count)


def _lyric_items(layout: _Layout) -> list[Item]:
    return [item for item in layout.items if item.key.lower() in LYRICS_KEYS and item.is_text]


class APEv2Editor:
    """Letras de un tag APEv2 al final del archivo."""

    tag_format = TAG_FORMAT

    def __init__(self, path: Path, start: int, region: bytes, file_size: int, footer_offset: int):
        self.path = Path(path)
        self.start = start
        self.region = region
        self.file_size = file_size
        self.at_eof = True
        self.footer_offset = footer_offset
        self.layout = _parse(region, footer_offset)
        self.values = {}
        for item in _lyric_items(self.layout):
            try:
                self.values[item.key] = item.value.decode("utf-8").split("\0")
            except UnicodeDecodeError as exc:
                raise Unsupported("ape_invalid", "letra que no es UTF-8 válido") from exc

    def slots(self) -> list[Slot]:
        return [Slot(TAG_FORMAT, key, index, key, value)
                for key, values in self.values.items() for index, value in enumerate(values)]

    def build(self, values: dict) -> Edit:
        region = self.region
        patches = []
        delta = 0
        expected = {}
        for item in _lyric_items(self.layout):
            texts = list(self.values[item.key])
            changed = False
            for index in range(len(texts)):
                if (item.key, index) in values:
                    texts[index] = values[(item.key, index)]
                    changed = True
                expected[(item.key, index)] = texts[index]
            if not changed:
                continue
            value = "\0".join(texts).encode("utf-8")
            raw = struct.pack("<2I", len(value), item.flags) + item.raw[8:len(item.raw) - len(item.value)] + value
            if raw != item.raw:
                patches.append(Patch(item.offset, item.raw, raw))
                delta += len(raw) - len(item.raw)
        if not patches:
            return Edit([], MODE_TAIL, len(region), len(region), "", expected)
        size = struct.pack("<I", self.layout.size + delta)
        for offset in (self.layout.header_offset, self.layout.footer_offset):
            if offset is not None:
                patches.append(Patch(offset + 12, region[offset + 12:offset + 16], size))
        return Edit(patches, MODE_TAIL, len(region), len(region) + delta,
                    f"tag APEv2 al final: el archivo cambia {delta:+d} bytes", expected)

    def verify(self, new_region: bytes, expected: dict) -> list[str]:
        problems = []
        footer_offset = self.footer_offset + len(new_region) - len(self.region)
        try:
            new = _parse(new_region, footer_offset)
        except Unsupported as exc:
            return [f"el tag nuevo no se puede leer: {exc}"]
        old = self.layout

        def fixed(region, layout, offset):
            block = region[offset:offset + 32]
            return block[:12] + block[16:]
        for offset_old, offset_new in ((old.header_offset, new.header_offset), (old.footer_offset, new.footer_offset)):
            if (offset_old is None) != (offset_new is None):
                problems.append("cambió la cabecera o el pie APEv2")
            elif offset_old is not None and fixed(self.region, old, offset_old) != fixed(new_region, new, offset_new):
                problems.append("cambió la cabecera o el pie APEv2")
        if [i.key for i in old.items] != [i.key for i in new.items]:
            problems.append("cambió el orden o la cantidad de campos APEv2")
            return problems
        for before, after in zip(old.items, new.items):
            if before in _lyric_items(old):
                if after.flags != before.flags:
                    problems.append(f"cambiaron las marcas del campo {before.key}")
                texts = after.value.decode("utf-8", "replace").split("\0")
                for index, text in enumerate(texts):
                    wanted = expected.get((before.key, index), self.values[before.key][index]
                                          if index < len(self.values[before.key]) else None)
                    if text != wanted:
                        problems.append(f"la letra {before.key} no quedó como se esperaba")
            elif before.raw != after.raw:
                problems.append(f"cambió el campo {before.key}, que no es una letra")
        if self.region[self.footer_offset + 32:] != new_region[footer_offset + 32:]:
            problems.append("cambió el tag ID3v1 del final")
        return problems


def open_apev2(path: Path) -> APEv2Editor:
    path = Path(path)
    file_size = path.stat().st_size
    with open(path, "rb") as handle:
        trailer = 0
        if file_size >= 128:
            handle.seek(file_size - 128)
            if handle.read(3) == b"TAG":
                trailer = 128
        footer_at = file_size - trailer - 32
        if footer_at < 0:
            raise Unsupported("ape_invalid", "archivo demasiado corto")
        handle.seek(footer_at)
        footer = handle.read(32)
        if footer[:8] != _PREAMBLE:
            raise Unsupported("ape_invalid", "no hay un tag APEv2 al final del archivo")
        _version, size, _count, flags = struct.unpack("<4I", footer[8:24])
        start = footer_at + 32 - size - (32 if flags & _HAS_HEADER else 0)
        if start < 0:
            raise Unsupported("ape_invalid", "tamaño del tag APEv2 no válido")
        handle.seek(start)
        region = handle.read(file_size - start)
    return APEv2Editor(path, start, region, file_size, footer_at - start)
