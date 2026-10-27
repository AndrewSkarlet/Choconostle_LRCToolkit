"""
rawtags/mp4.py

Editor byte a byte de la letra ©lyr en archivos MP4/M4A.

Solo cambian el átomo "data" de la letra y los campos de tamaño de los
átomos que lo contienen (©lyr, ilst, meta, udta, moov). Los offsets de
audio (stco/co64) nunca se tocan: la diferencia de tamaño se compensa,
por orden de preferencia, con:

1. un átomo "free" contiguo a ilst dentro de meta (lo que deja mutagen);
2. un átomo "free" justo después de moov;
3. moov al final del archivo (después de mdat): el archivo cambia de
   tamaño al final y ningún offset se mueve;
4. si la letra se acorta 8 bytes o más, un átomo "free" nuevo tras ilst.

Si nada de eso es posible (moov antes de mdat, sin relleno), el archivo
se omite: corregir los offsets del audio está fuera del alcance.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from choconostle.rawtags import (
    MODE_INPLACE, MODE_TAIL, Edit, Patch, Slot, Unsupported,
)

TAG_FORMAT = "mp4"
LYRICS_KEY = "\xa9lyr"
_LYRICS_ATOM = b"\xa9lyr"
_CONTAINERS = {b"moov", b"udta", b"meta", b"ilst", b"trak", b"mdia", b"minf", b"stbl", b"dinf", b"edts"}
_FREE = (b"free", b"skip")


@dataclass
class Atom:
    kind: bytes
    offset: int
    """Posición dentro de la región."""
    size: int
    header: int = 8
    children: list["Atom"] = field(default_factory=list)
    body_offset: int = 0

    @property
    def end(self) -> int:
        return self.offset + self.size


def _parse_atoms(data: bytes, start: int, end: int) -> list[Atom]:
    atoms = []
    position = start
    while position + 8 <= end:
        size, kind = struct.unpack(">I4s", data[position:position + 8])
        if size == 1:
            raise Unsupported("mp4_64bit")
        if size == 0:
            size = end - position
        if size < 8 or position + size > end:
            raise Unsupported("mp4_invalid", f"átomo {kind!r} con tamaño no válido")
        atom = Atom(kind, position, size)
        body = position + 8
        if kind == b"meta":
            body += 4  # versión y flags
        atom.body_offset = body
        if kind in _CONTAINERS:
            atom.children = _parse_atoms(data, body, position + size)
        elif kind == _LYRICS_ATOM:
            atom.children = _parse_atoms(data, body, position + size)
        atoms.append(atom)
        position += size
    if position != end:
        raise Unsupported("mp4_invalid", "bytes sobrantes dentro de un átomo")
    return atoms


def _child(atom: Atom | None, kind: bytes) -> Atom | None:
    if atom is None:
        return None
    return next((child for child in atom.children if child.kind == kind), None)


@dataclass
class _Layout:
    moov: Atom
    path: list[Atom]
    """[moov, udta, meta, ilst] (los que existan)."""
    ilst: Atom | None
    lyrics: list[tuple[Atom, Atom]]
    """[(átomo ©lyr, átomo data)]."""


def _layout(region: bytes) -> _Layout:
    (moov,) = _parse_atoms(region, 0, len(region)) if region[4:8] == b"moov" else (None,)
    if moov is None:
        raise Unsupported("mp4_invalid", "la región no es un átomo moov")
    udta = _child(moov, b"udta")
    meta = _child(udta, b"meta")
    ilst = _child(meta, b"ilst")
    path = [atom for atom in (moov, udta, meta, ilst) if atom is not None]
    lyrics = []
    if ilst is not None:
        for item in ilst.children:
            if item.kind == _LYRICS_ATOM:
                for data in item.children:
                    if data.kind == b"data":
                        lyrics.append((item, data))
    return _Layout(moov, path, ilst, lyrics)


def _data_value(region: bytes, data: Atom) -> str:
    type_flags = region[data.offset + 8:data.offset + 12]
    if type_flags != b"\0\0\0\x01":
        raise Unsupported("mp4_value_type")
    try:
        return region[data.offset + 16:data.end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Unsupported("mp4_value_type", "letra que no es UTF-8 válido") from exc


class MP4Editor:
    """Letras ©lyr de un archivo MP4/M4A."""

    tag_format = TAG_FORMAT

    def __init__(self, path: Path, start: int, region: bytes, file_size: int,
                 moov_is_last: bool, free_after: int):
        self.path = Path(path)
        self.start = start
        self.region = region
        self.file_size = file_size
        self.moov_is_last = moov_is_last
        self.free_after = free_after
        """Tamaño del átomo free de nivel superior incluido en la región tras moov (0 si no hay)."""
        self.at_eof = moov_is_last
        moov_size = struct.unpack(">I", region[:4])[0]
        self.layout = _layout(region[:moov_size])
        self.values = [_data_value(region, data) for _item, data in self.layout.lyrics]

    def slots(self) -> list[Slot]:
        return [Slot(TAG_FORMAT, LYRICS_KEY, index, LYRICS_KEY, value)
                for index, value in enumerate(self.values)]

    def build(self, values: dict) -> Edit:
        region = self.region
        patches = []
        delta = 0
        expected = {}
        item_delta: dict[int, int] = {}
        for index, (item, data) in enumerate(self.layout.lyrics):
            if (LYRICS_KEY, index) not in values:
                continue
            value = values[(LYRICS_KEY, index)]
            expected[(LYRICS_KEY, index)] = value
            payload = value.encode("utf-8")
            raw = struct.pack(">I", 16 + len(payload)) + region[data.offset + 4:data.offset + 16] + payload
            old = region[data.offset:data.end]
            if raw != old:
                patches.append(Patch(data.offset, old, raw))
                change = len(raw) - len(old)
                delta += change
                item_delta[item.offset] = item_delta.get(item.offset, 0) + change
        if not patches:
            return Edit([], MODE_INPLACE, len(region), len(region), "", expected)

        def size_patch(atom: Atom, change: int) -> Patch:
            return Patch(atom.offset, region[atom.offset:atom.offset + 4],
                         struct.pack(">I", atom.size + change))

        items = {item.offset: item for item, _data in self.layout.lyrics}
        for offset, change in item_delta.items():
            patches.append(size_patch(items[offset], change))
        moov, ilst = self.layout.moov, self.layout.ilst
        meta = self.layout.path[2]
        upper = [atom for atom in self.layout.path if atom is not ilst]  # moov, udta, meta

        # 1. free contiguo a ilst dentro de meta.
        sibling = next((child for child in meta.children if child.offset == ilst.end), None)
        if sibling is not None and sibling.kind in _FREE and (
                sibling.size - delta == 0 or sibling.size - delta >= 8):
            patches.append(size_patch(ilst, delta))
            patches.append(self._resize_free(sibling, delta))
            return Edit(patches, MODE_INPLACE, len(region), len(region),
                        f"relleno MP4 (free) {sibling.size} -> {sibling.size - delta} bytes", expected)

        # 2. free de nivel superior justo después de moov.
        if self.free_after and self.free_after - delta >= 8:
            free = Atom(b"free", moov.size, self.free_after)
            patches.append(size_patch(ilst, delta))
            patches.extend(size_patch(atom, delta) for atom in upper)
            patches.append(self._resize_free(free, delta))
            return Edit(patches, MODE_INPLACE, len(region), len(region),
                        f"relleno MP4 (free tras moov) {self.free_after} -> {self.free_after - delta} bytes",
                        expected)

        # 3. moov al final del archivo: no se mueve ningún offset.
        if self.moov_is_last:
            patches.append(size_patch(ilst, delta))
            patches.extend(size_patch(atom, delta) for atom in upper)
            return Edit(patches, MODE_TAIL, len(region), len(region) + delta,
                        f"moov al final: el archivo cambia {delta:+d} bytes", expected)

        # 4. La letra se acorta: los bytes liberados forman un átomo free nuevo.
        if delta <= -8:
            patches.append(size_patch(ilst, delta))
            patches.append(Patch(ilst.end, b"", struct.pack(">I4s", -delta, b"free") + b"\0" * (-delta - 8)))
            return Edit(patches, MODE_INPLACE, len(region), len(region),
                        f"nuevo átomo free de {-delta} bytes", expected)
        raise Unsupported("mp4_no_padding")

    def _resize_free(self, free: Atom, delta: int) -> Patch:
        old = self.region[free.offset:free.end]
        new_size = free.size - delta
        if new_size == 0:
            return Patch(free.offset, old, b"")
        content = old[8:]
        content = content[:new_size - 8] if delta > 0 else content + b"\0" * (-delta)
        return Patch(free.offset, old, struct.pack(">I", new_size) + old[4:8] + content)

    def verify(self, new_region: bytes, expected: dict) -> list[str]:
        problems = []
        try:
            moov_size = struct.unpack(">I", new_region[:4])[0]
            new = _layout(new_region[:moov_size])
        except (Unsupported, struct.error) as exc:
            return [f"el moov nuevo no se puede leer: {exc}"]

        def leaves(region, atoms, out):
            for atom in atoms:
                if atom.kind in _FREE or atom.kind == _LYRICS_ATOM:
                    continue
                if atom.children or atom.kind in _CONTAINERS:
                    out.append((atom.kind, region[atom.offset + 4:atom.body_offset]))
                    leaves(region, atom.children, out)
                else:
                    out.append((atom.kind, region[atom.offset:atom.end]))
            return out
        if leaves(self.region, [self.layout.moov], []) != leaves(new_region, [new.moov], []):
            problems.append("cambió un átomo que no es la letra")
        values = []
        for _item, data in new.lyrics:
            try:
                values.append(_data_value(new_region, data))
            except Unsupported:
                values.append(None)
        for index, value in enumerate(values):
            wanted = expected.get((LYRICS_KEY, index), self.values[index] if index < len(self.values) else None)
            if value != wanted:
                problems.append(f"la letra ©lyr #{index + 1} no quedó como se esperaba")
        if len(values) != len(self.values):
            problems.append("cambió la cantidad de letras ©lyr")
        old_type = [new_region[d.offset + 4:d.offset + 16] for _i, d in new.lyrics]
        if old_type != [self.region[d.offset + 4:d.offset + 16] for _i, d in self.layout.lyrics]:
            problems.append("cambió el tipo o el idioma de la letra")
        return problems


def open_mp4(path: Path) -> MP4Editor:
    path = Path(path)
    file_size = path.stat().st_size
    top = []
    with open(path, "rb") as handle:
        position = 0
        while position + 8 <= file_size:
            handle.seek(position)
            size, kind = struct.unpack(">I4s", handle.read(8))
            if size == 1:
                (size,) = struct.unpack(">Q", handle.read(8))
                if kind == b"moov":
                    raise Unsupported("mp4_64bit")
            elif size == 0:
                size = file_size - position
            if size < 8:
                raise Unsupported("mp4_invalid", f"átomo {kind!r} con tamaño no válido")
            top.append((kind, position, size))
            position += size
        moovs = [entry for entry in top if entry[0] == b"moov"]
        if len(moovs) != 1:
            raise Unsupported("mp4_invalid", "no hay un único átomo moov")
        index = top.index(moovs[0])
        _kind, start, size = moovs[0]
        rest = top[index + 1:]
        moov_is_last = not rest
        free_after = rest[0][2] if rest and rest[0][0] in _FREE else 0
        length = file_size - start if moov_is_last else size + free_after
        handle.seek(start)
        region = handle.read(length)
    return MP4Editor(path, start, region, file_size, moov_is_last, free_after)
