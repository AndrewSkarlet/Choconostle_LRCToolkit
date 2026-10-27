"""
rawtags/flac.py

Editor byte a byte de letras en FLAC (comentarios Vorbis LYRICS,
UNSYNCEDLYRICS...).

Solo cambian: la entrada del comentario de letra, el tamaño del bloque
VORBIS_COMMENT y el relleno (bloque PADDING), que compensa la diferencia
para que el audio no se mueva. Los demás bloques (STREAMINFO, PICTURE,
SEEKTABLE...) y comentarios se copian sin tocar.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from choconostle.rawtags import (
    MODE_FULL, MODE_INPLACE, Edit, Patch, Slot, Unsupported,
)
from choconostle.tags import LYRICS_KEYS

TAG_FORMAT = "vorbis"
_PADDING = 1
_VORBIS_COMMENT = 4
_MAX_BLOCK = 0xFFFFFF


@dataclass
class Block:
    offset: int
    kind: int
    last: bool
    raw: bytes
    """Cabecera (4 bytes) + contenido."""


@dataclass
class Comment:
    offset: int
    """Posición dentro de la región (del campo de longitud)."""
    raw: bytes
    key: bytes
    value: bytes


@dataclass
class FlacLayout:
    blocks: list[Block]
    vendor: bytes
    comments: list[Comment]
    comment_block: Block | None


def _parse(region: bytes) -> FlacLayout:
    if region[:4] != b"fLaC":
        raise Unsupported("flac_invalid", "falta la marca fLaC")
    blocks = []
    position = 4
    while True:
        if position + 4 > len(region):
            raise Unsupported("flac_invalid", "bloques de metadatos incompletos")
        header = region[position]
        length = int.from_bytes(region[position + 1:position + 4], "big")
        blocks.append(Block(position, header & 0x7F, bool(header & 0x80),
                            region[position:position + 4 + length]))
        position += 4 + length
        if header & 0x80:
            break
    if position != len(region):
        raise Unsupported("flac_invalid", "la región no termina en el último bloque")

    comment_blocks = [block for block in blocks if block.kind == _VORBIS_COMMENT]
    if len(comment_blocks) > 1:
        raise Unsupported("vorbis_invalid", "más de un bloque VORBIS_COMMENT")
    vendor = b""
    comments = []
    block = comment_blocks[0] if comment_blocks else None
    if block is not None:
        data = block.raw
        try:
            (vendor_len,) = struct.unpack("<I", data[4:8])
            vendor = data[8:8 + vendor_len]
            position = 8 + vendor_len
            (count,) = struct.unpack("<I", data[position:position + 4])
            position += 4
            for _ in range(count):
                (length,) = struct.unpack("<I", data[position:position + 4])
                entry = data[position + 4:position + 4 + length]
                if len(entry) != length:
                    raise struct.error("comentario cortado")
                key, _sep, value = entry.partition(b"=")
                comments.append(Comment(block.offset + position, data[position:position + 4 + length],
                                        key, value))
                position += 4 + length
        except struct.error as exc:
            raise Unsupported("vorbis_invalid", str(exc)) from exc
    return FlacLayout(blocks, vendor, comments, block)


def _lyric_comments(layout: FlacLayout) -> list[tuple[Comment, str, int]]:
    """[(comentario, clave en minúsculas, índice)] de las letras."""
    found = []
    counts: dict[str, int] = {}
    for comment in layout.comments:
        key = comment.key.decode("ascii", errors="replace").lower()
        if key not in LYRICS_KEYS:
            continue
        index = counts.get(key, 0)
        counts[key] = index + 1
        found.append((comment, key, index))
    return found


class FlacEditor:
    """Letras de los comentarios Vorbis de un archivo FLAC."""

    tag_format = TAG_FORMAT

    def __init__(self, path: Path, region: bytes, file_size: int):
        self.path = Path(path)
        self.start = 0
        self.region = region
        self.file_size = file_size
        self.at_eof = False
        self.layout = _parse(region)
        for comment, _key, _index in _lyric_comments(self.layout):
            try:
                comment.value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise Unsupported("vorbis_invalid", "letra que no es UTF-8 válido") from exc

    def slots(self) -> list[Slot]:
        return [Slot(TAG_FORMAT, key, index, comment.key.decode("ascii", "replace").upper(),
                     comment.value.decode("utf-8"))
                for comment, key, index in _lyric_comments(self.layout)]

    def build(self, values: dict) -> Edit:
        patches = []
        delta = 0
        expected = {}
        for comment, key, index in _lyric_comments(self.layout):
            if (key, index) not in values:
                continue
            value = values[(key, index)]
            expected[(key, index)] = value
            entry = comment.key + b"=" + value.encode("utf-8")
            raw = struct.pack("<I", len(entry)) + entry
            if raw != comment.raw:
                patches.append(Patch(comment.offset, comment.raw, raw))
                delta += len(raw) - len(comment.raw)
        block = self.layout.comment_block
        if not patches:
            return Edit([], MODE_INPLACE, len(self.region), len(self.region), "", expected)

        new_length = len(block.raw) - 4 + delta
        if new_length > _MAX_BLOCK:
            raise Unsupported("vorbis_invalid", "el bloque de comentarios superaría 16 MB")
        header_new = bytes([block.raw[0]]) + new_length.to_bytes(3, "big")
        padding = next((b for b in self.layout.blocks if b.kind == _PADDING), None)

        if padding is not None and len(padding.raw) - 4 - delta >= 0 \
                and len(padding.raw) - 4 - delta <= _MAX_BLOCK:
            old_pad = len(padding.raw) - 4
            new_pad = old_pad - delta
            content = padding.raw[4:]
            new_content = content[:new_pad] if delta > 0 else content + b"\0" * (-delta)
            patches.append(Patch(block.offset, block.raw[:4], header_new))
            patches.append(Patch(padding.offset, padding.raw,
                                 bytes([padding.raw[0]]) + new_pad.to_bytes(3, "big") + new_content))
            return Edit(patches, MODE_INPLACE, len(self.region), len(self.region),
                        f"relleno FLAC {old_pad} -> {new_pad} bytes", expected)

        if padding is None and delta <= -4:
            # Sin relleno: los bytes liberados se convierten en un bloque PADDING
            # justo después de los comentarios.
            was_last = block.last
            first = bytes([block.raw[0] & 0x7F]) + new_length.to_bytes(3, "big")
            patches.append(Patch(block.offset, block.raw[:4], first))
            pad_len = -delta - 4
            new_block = bytes([(0x80 if was_last else 0) | _PADDING]) + pad_len.to_bytes(3, "big") + b"\0" * pad_len
            patches.append(Patch(block.offset + len(block.raw), b"", new_block))
            return Edit(patches, MODE_INPLACE, len(self.region), len(self.region),
                        f"nuevo bloque de relleno FLAC de {pad_len} bytes", expected)

        patches.append(Patch(block.offset, block.raw[:4], header_new))
        return Edit(patches, MODE_FULL, len(self.region), len(self.region) + delta,
                    f"los metadatos FLAC crecen {delta} bytes", expected)

    def verify(self, new_region: bytes, expected: dict) -> list[str]:
        problems = []
        try:
            new = _parse(new_region)
        except Unsupported as exc:
            return [f"los metadatos nuevos no se pueden leer: {exc}"]
        old = self.layout

        def others(layout):
            return [b.raw for b in layout.blocks if b.kind not in (_VORBIS_COMMENT, _PADDING)]
        if others(new) != others(old):
            problems.append("cambió un bloque de metadatos que no es de comentarios")
        if new.vendor != old.vendor:
            problems.append("cambió el vendor de los comentarios")
        old_plain = [c.raw for c in old.comments if c.key.decode("ascii", "replace").lower() not in LYRICS_KEYS]
        new_plain = [c.raw for c in new.comments if c.key.decode("ascii", "replace").lower() not in LYRICS_KEYS]
        if old_plain != new_plain:
            problems.append("cambió un comentario que no es una letra")
        old_keys = [(k, i) for _c, k, i in _lyric_comments(old)]
        new_lyrics = {(k, i): c for c, k, i in _lyric_comments(new)}
        if old_keys != list(new_lyrics):
            problems.append("cambió la cantidad u orden de las letras")
        old_values = {(k, i): c.value.decode("utf-8") for c, k, i in _lyric_comments(old)}
        for key, comment in new_lyrics.items():
            wanted = expected.get(key, old_values.get(key))
            if comment.value.decode("utf-8", "replace") != wanted:
                problems.append(f"la letra {key[0]} no quedó como se esperaba")
        if not new.blocks[-1].last or any(block.last for block in new.blocks[:-1]):
            problems.append("la marca de último bloque no es correcta")
        return problems


def open_flac(path: Path) -> FlacEditor:
    path = Path(path)
    file_size = path.stat().st_size
    with open(path, "rb") as handle:
        if handle.read(4) != b"fLaC":
            raise Unsupported("flac_invalid", "falta la marca fLaC (¿ID3 antes del FLAC?)")
        position = 4
        while True:
            header = handle.read(4)
            if len(header) < 4:
                raise Unsupported("flac_invalid", "bloques de metadatos incompletos")
            length = int.from_bytes(header[1:4], "big")
            position += 4 + length
            handle.seek(position)
            if header[0] & 0x80:
                break
        handle.seek(0)
        return FlacEditor(path, handle.read(position), file_size)
