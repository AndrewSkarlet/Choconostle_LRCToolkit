"""
rawtags/id3.py

Editor byte a byte de letras en ID3v2.3 y ID3v2.4 (USLT, SYLT y TXXX de
letra).

- Solo se reconstruyen los frames de letra, con su misma codificación,
  idioma, descripción, BOM de cada cadena y terminador final (si lo había).
- Los demás frames se copian sin tocar un byte.
- El tamaño del tag se mantiene usando el relleno; si la letra nueva no
  cabe en el relleno, la edición es una reescritura completa.
- Cada valor de un TXXX de letra es un slot propio: nunca se unen.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from choconostle.rawtags import (
    MODE_FULL, MODE_INPLACE, Edit, Patch, Slot, Unsupported,
)
from choconostle.tags import LYRICS_KEYS

TAG_FORMAT = "id3"

_FRAME_ID_RE = re.compile(rb"[A-Z0-9]{4}")
_LYRIC_FRAMES = ("USLT", "SYLT", "TXXX")
_TERMINATORS = {0: b"\0", 1: b"\0\0", 2: b"\0\0", 3: b"\0"}


def syncsafe(data: bytes) -> int:
    value = 0
    for byte in data:
        value = (value << 7) | (byte & 0x7F)
    return value


def to_syncsafe(value: int) -> bytes:
    if value >= 1 << 28:
        raise Unsupported("id3_invalid", "frame demasiado grande")
    return bytes([(value >> 21) & 0x7F, (value >> 14) & 0x7F, (value >> 7) & 0x7F, value & 0x7F])


# --------------------------------------------------------------------------
# Cadenas codificadas
# --------------------------------------------------------------------------

def _find_terminator(data: bytes, start: int, encoding: int) -> int:
    """Posición del terminador desde `start`, o -1."""
    if len(_TERMINATORS[encoding]) == 1:
        return data.find(b"\0", start)
    position = start
    while position + 1 < len(data):
        if data[position] == 0 and data[position + 1] == 0:
            return position
        position += 2
    return -1


def _decode(raw: bytes, encoding: int) -> tuple[str, bytes]:
    """(texto, BOM) de una cadena. Lanza UnicodeError si no es válida."""
    if encoding == 0:
        return raw.decode("latin-1"), b""
    if encoding == 3:
        return raw.decode("utf-8"), b""
    if encoding == 2:
        return raw.decode("utf-16-be"), b""
    if raw[:2] == b"\xff\xfe":
        return raw[2:].decode("utf-16-le"), raw[:2]
    if raw[:2] == b"\xfe\xff":
        return raw[2:].decode("utf-16-be"), raw[:2]
    if len(raw) % 2:
        raise UnicodeError("UTF-16 de longitud impar")
    return raw.decode("utf-16-le"), b""


def _encode(text: str, encoding: int, bom: bytes) -> bytes:
    if encoding == 0:
        return text.encode("latin-1")
    if encoding == 3:
        return text.encode("utf-8")
    if encoding == 2:
        return text.encode("utf-16-be")
    if bom == b"\xfe\xff":
        return bom + text.encode("utf-16-be")
    return bom + text.encode("utf-16-le")


# --------------------------------------------------------------------------
# Frames de letra
# --------------------------------------------------------------------------

@dataclass
class LyricFrame:
    """Cuerpo de un frame de letra separado en partes."""
    frame_id: str
    encoding: int
    head: bytes
    """Bytes antes de los textos: codificación, idioma, formato, descripción y su terminador."""
    desc: str
    lang: str
    values: list
    """USLT/TXXX: [(texto, BOM)]. SYLT: [(texto, BOM, tiempo)]."""
    trailing: bool = False
    """USLT/TXXX: el último texto lleva terminador."""

    def reencoded(self, encoding: int) -> "LyricFrame":
        """
        El mismo frame con otra codificación de texto (convert-lyrics
        --id3-encoding): se rehacen el byte de codificación, la descripción y
        el BOM de cada cadena (UTF-16 con BOM FF FE). Idioma, formato de
        tiempo y tipo de contenido (SYLT) no cambian.
        """
        if encoding == self.encoding:
            return self
        bom = b"\xff\xfe" if encoding == 1 else b""
        head = bytes([encoding])
        if self.frame_id in ("USLT", "SYLT"):
            head += self.head[1:4]
        if self.frame_id == "SYLT":
            head += self.head[4:6]
        head += _encode(self.desc, encoding, bom) + _TERMINATORS[encoding]
        if self.frame_id == "SYLT":
            values = [(text, bom, time) for text, _b, time in self.values]
        else:
            values = [(text, bom) for text, _b in self.values]
        return LyricFrame(self.frame_id, encoding, head, self.desc, self.lang, values, self.trailing)

    def build(self, new_values=None) -> bytes:
        """Cuerpo del frame; `new_values` reemplaza los textos (misma forma, sin BOM)."""
        term = _TERMINATORS[self.encoding]
        parts = [self.head]
        if self.frame_id == "SYLT":
            entries = new_values if new_values is not None else [(t, time) for t, _b, time in self.values]
            boms = [bom for _t, bom, _time in self.values]
            default = boms[0] if boms else b"\xff\xfe"
            for position, (text, time) in enumerate(entries):
                bom = boms[position] if position < len(boms) else default
                parts.append(_encode(text, self.encoding, bom) + term + struct.pack(">I", time))
            return b"".join(parts)
        texts = new_values if new_values is not None else [t for t, _b in self.values]
        boms = [bom for _t, bom in self.values]
        encoded = [_encode(text, self.encoding, boms[min(i, len(boms) - 1)] if boms else b"")
                   for i, text in enumerate(texts)]
        parts.append(term.join(encoded))
        if self.trailing:
            parts.append(term)
        return b"".join(parts)


def parse_lyric_frame(frame_id: str, body: bytes) -> LyricFrame:
    """Separa el cuerpo de un frame de letra. Lanza Unsupported si no se reconstruye igual."""
    try:
        frame = _parse_lyric_frame(frame_id, body)
    except (IndexError, UnicodeError, struct.error) as exc:
        raise Unsupported("id3_frame_format", f"frame {frame_id} no válido: {exc}") from exc
    if frame.build() != body:
        raise Unsupported("id3_frame_format", f"frame {frame_id} con formato no reproducible")
    return frame


def _parse_lyric_frame(frame_id: str, body: bytes) -> LyricFrame:
    encoding = body[0]
    if encoding not in _TERMINATORS:
        raise UnicodeError(f"codificación de texto {encoding}")
    term = _TERMINATORS[encoding]
    position = 1
    lang = ""
    if frame_id in ("USLT", "SYLT"):
        lang = body[1:4].decode("latin-1")
        position = 4
    if frame_id == "SYLT":
        position += 2  # formato de tiempo y tipo de contenido
    end = _find_terminator(body, position, encoding)
    if end < 0:
        raise UnicodeError("descripción sin terminador")
    desc, _bom = _decode(body[position:end], encoding)
    position = end + len(term)
    head = body[:position]

    if frame_id == "SYLT":
        entries = []
        while position < len(body):
            end = _find_terminator(body, position, encoding)
            if end < 0:
                raise UnicodeError("entrada SYLT sin terminador")
            raw = body[position:end]
            text, bom = _decode(raw, encoding)
            (time,) = struct.unpack(">I", body[end + len(term):end + len(term) + 4])
            entries.append((text, bom, time))
            position = end + len(term) + 4
        return LyricFrame(frame_id, encoding, head, desc, lang, entries)

    rest = body[position:]
    trailing = False
    if rest.endswith(term) and (len(term) == 1 or len(rest) % 2 == 0):
        trailing = True
        rest = rest[:-len(term)]
    raws = [rest]
    if frame_id == "TXXX":
        raws = []
        start = 0
        while True:
            end = _find_terminator(rest, start, encoding)
            if end < 0:
                raws.append(rest[start:])
                break
            raws.append(rest[start:end])
            start = end + len(term)
    elif _find_terminator(rest, 0, encoding) >= 0:
        raise UnicodeError("USLT con varios textos")
    values = [_decode(raw, encoding) for raw in raws]
    return LyricFrame(frame_id, encoding, head, desc, lang, values, trailing)


# --------------------------------------------------------------------------
# Tag
# --------------------------------------------------------------------------

@dataclass
class Frame:
    frame_id: str
    offset: int
    """Posición dentro de la región."""
    raw: bytes
    """Cabecera + cuerpo."""
    flags: bytes
    lyric: LyricFrame | None = None
    key: str | None = None

    @property
    def body(self) -> bytes:
        return self.raw[10:]


@dataclass
class ID3Layout:
    version: int
    header: bytes
    extended: bytes
    frames: list[Frame]
    padding_offset: int
    padding: int
    size: int
    syncsafe_frames: bool
    lyric_problem: str | None = None
    frame_ids: list[str] = field(default_factory=list)


def parse_tag(region: bytes) -> ID3Layout:
    """Interpreta un tag ID3v2 completo (cabecera + frames + relleno)."""
    if region[:3] != b"ID3" or len(region) < 10:
        raise Unsupported("id3_position")
    version, flags = region[3], region[5]
    if version == 2:
        raise Unsupported("id3v22")
    if version not in (3, 4):
        raise Unsupported("id3_version", f"ID3v2.{version} no soportado")
    if flags & 0x80:
        raise Unsupported("id3_unsync")
    if version == 4 and flags & 0x10:
        raise Unsupported("id3_footer")
    size = syncsafe(region[6:10])
    end = 10 + size
    if end > len(region):
        raise Unsupported("id3_invalid", "el tag es más largo que el archivo")
    position = 10
    extended = b""
    if flags & 0x40:
        if version == 3:
            length = 4 + int.from_bytes(region[10:14], "big")
            if region[14] & 0x80:
                raise Unsupported("id3_crc")
        else:
            length = syncsafe(region[10:14])
            if len(region) > 15 and region[15] & 0x20:
                raise Unsupported("id3_crc")
        extended = region[10:10 + length]
        position += length

    modes = [True, False] if version == 4 else [False]
    for syncsafe_frames in modes:
        try:
            frames, padding_offset = _parse_frames(region, position, end, version, syncsafe_frames)
        except Unsupported:
            if syncsafe_frames is modes[-1]:
                raise
            continue
        break
    layout = ID3Layout(version, region[:10], extended, frames, padding_offset, end - padding_offset,
                       size, syncsafe_frames)
    _mark_lyrics(layout)
    return layout


def _parse_frames(region, position, end, version, syncsafe_frames):
    frames = []
    while position + 10 <= end and region[position] != 0:
        frame_id = region[position:position + 4]
        if not _FRAME_ID_RE.fullmatch(frame_id):
            raise Unsupported("id3_invalid", f"identificador de frame no válido {frame_id!r}")
        raw_size = region[position + 4:position + 8]
        size = syncsafe(raw_size) if syncsafe_frames else int.from_bytes(raw_size, "big")
        if position + 10 + size > end:
            raise Unsupported("id3_invalid", f"frame {frame_id.decode()} más largo que el tag")
        frames.append(Frame(frame_id.decode(), position, region[position:position + 10 + size],
                            region[position + 8:position + 10]))
        position += 10 + size
    if region[position:end].strip(b"\0"):
        raise Unsupported("id3_invalid", "datos no reconocidos tras los frames")
    return frames, position


def _mark_lyrics(layout: ID3Layout) -> None:
    counts: dict[str, int] = {}
    for frame in layout.frames:
        if frame.frame_id not in _LYRIC_FRAMES:
            continue
        if frame.frame_id == "TXXX" and not _flags_block(layout, frame):
            desc = _peek_txxx_desc(frame.body)
            if desc is None or desc.lower() not in LYRICS_KEYS:
                continue
        if _flags_block(layout, frame):
            raise Unsupported("id3_frame_flags", f"frame {frame.frame_id} comprimido, cifrado o con otras marcas")
        frame.lyric = parse_lyric_frame(frame.frame_id, frame.body)
        identity = f"{frame.frame_id}:{frame.lyric.lang}:{frame.lyric.desc}"
        occurrence = counts.get(identity, 0)
        counts[identity] = occurrence + 1
        frame.key = f"{identity}#{occurrence}"


def _peek_txxx_desc(body: bytes) -> str | None:
    try:
        encoding = body[0]
        end = _find_terminator(body, 1, encoding)
        return _decode(body[1:end], encoding)[0] if end > 0 else None
    except (IndexError, UnicodeError, KeyError):
        return None


def _flags_block(layout: ID3Layout, frame: Frame) -> bool:
    """True si el frame tiene compresión, cifrado, agrupación o similares."""
    format_flags = frame.flags[1]
    return bool(format_flags & (0xE0 if layout.version == 3 else 0x4F))


def _frame_header(layout: ID3Layout, frame: Frame, body_len: int) -> bytes:
    if layout.version == 4 and layout.syncsafe_frames:
        size = to_syncsafe(body_len)
    else:
        size = body_len.to_bytes(4, "big")
    return frame.frame_id.encode() + size + frame.flags


# --------------------------------------------------------------------------
# Editor
# --------------------------------------------------------------------------

class ID3Editor:
    """Letras de un tag ID3v2 (al inicio de un MP3 o dentro de un chunk WAV/AIFF)."""

    tag_format = TAG_FORMAT

    def __init__(self, path: Path, start: int, region: bytes, file_size: int, in_chunk: bool = False):
        self.path = Path(path)
        self.start = start
        self.region = region
        self.file_size = file_size
        self.in_chunk = in_chunk
        self.at_eof = False
        self.layout = parse_tag(region)

    def slots(self) -> list[Slot]:
        found = []
        for frame in self.layout.frames:
            lyric = frame.lyric
            if lyric is None:
                continue
            if frame.frame_id == "SYLT":
                found.append(Slot(TAG_FORMAT, frame.key, 0, "SYLT",
                                  [(text, time) for text, _bom, time in lyric.values], lyric.encoding))
            elif frame.frame_id == "USLT":
                found.append(Slot(TAG_FORMAT, frame.key, 0, "USLT", lyric.values[0][0], lyric.encoding))
            else:
                for index, (text, _bom) in enumerate(lyric.values):
                    found.append(Slot(TAG_FORMAT, frame.key, index, f"TXXX:{lyric.desc}", text, lyric.encoding))
        return found

    def build(self, values: dict, encodings: dict | None = None) -> Edit:
        """
        `values`: {(clave, índice): valor nuevo}. `encodings`: {clave del
        frame: codificación nueva} (0 Latin-1, 1 UTF-16, 3 UTF-8 solo en v2.4).
        """
        encodings = {key: enc for key, enc in (encodings or {}).items()}
        patches: list[Patch] = []
        delta = 0
        expected = {}
        changed_encodings = {}
        for frame in self.layout.frames:
            if frame.lyric is None:
                continue
            mine = {index: value for (key, index), value in values.items() if key == frame.key}
            new_encoding = encodings.get(frame.key)
            if not mine and new_encoding in (None, frame.lyric.encoding):
                continue
            lyric = frame.lyric
            if new_encoding is not None and new_encoding != lyric.encoding:
                if new_encoding in (2, 3) and self.layout.version < 4:
                    raise Unsupported("id3_utf8_needs_v24")
                try:
                    lyric = lyric.reencoded(new_encoding)
                except UnicodeEncodeError as exc:
                    raise Unsupported("id3_unencodable", f"la descripción del frame {frame.frame_id} no cabe "
                                                         "en la codificación pedida") from exc
                changed_encodings[frame.key] = new_encoding
            if frame.frame_id == "TXXX":
                texts = [text for text, _bom in lyric.values]
                for index, value in mine.items():
                    texts[index] = value
                new_values = texts
                for index, text in enumerate(texts):
                    expected[(frame.key, index)] = text
            elif frame.frame_id == "USLT":
                new_values = [mine.get(0, lyric.values[0][0])]
                expected[(frame.key, 0)] = new_values[0]
            else:
                current = [(text, time) for text, _bom, time in lyric.values]
                new_values = [(text, time) for text, time in mine.get(0, current)]
                expected[(frame.key, 0)] = new_values
            try:
                body = lyric.build(new_values)
            except UnicodeEncodeError as exc:
                raise Unsupported("id3_unencodable",
                                  f"el texto nuevo no cabe en la codificación del frame {frame.frame_id}") from exc
            raw = _frame_header(self.layout, frame, len(body)) + body
            if raw != frame.raw:
                patches.append(Patch(frame.offset, frame.raw, raw))
                delta += len(raw) - len(frame.raw)

        padding = self.layout.padding
        if delta <= padding:
            new_padding = padding - delta
            if new_padding != padding:
                patches.append(Patch(self.layout.padding_offset, b"\0" * padding, b"\0" * new_padding))
            note = f"relleno ID3 {padding} -> {new_padding} bytes" if new_padding != padding else ""
            return Edit(patches, MODE_INPLACE, len(self.region), len(self.region), note, expected,
                        changed_encodings)

        if self.in_chunk:
            raise Unsupported("id3_chunk_grow")
        # No cabe: el tag crece y el audio se desplaza. Sin relleno extra.
        patches.append(Patch(self.layout.padding_offset, b"\0" * padding, b""))
        new_size = self.layout.size + delta - padding
        patches.append(Patch(6, self.region[6:10], to_syncsafe(new_size)))
        return Edit(patches, MODE_FULL, len(self.region), len(self.region) + delta - padding,
                    f"el tag ID3 crece {delta - padding} bytes", expected, changed_encodings)

    def verify(self, new_region: bytes, expected: dict, encodings: dict | None = None) -> list[str]:
        """
        Diferencias no previstas entre la región original y la nueva.
        `encodings`: frames cuya codificación debía cambiar (y a cuál).
        """
        encodings = encodings or {}
        problems = []
        try:
            new = parse_tag(new_region)
        except Unsupported as exc:
            return [f"el tag nuevo no se puede leer: {exc}"]
        old = self.layout
        if new.header[:6] != old.header[:6]:
            problems.append("cambió la cabecera ID3")
        if new.extended != old.extended:
            problems.append("cambió la cabecera extendida")
        if new.syncsafe_frames != old.syncsafe_frames:
            problems.append("cambió el formato de tamaño de los frames")
        if [f.frame_id for f in new.frames] != [f.frame_id for f in old.frames]:
            problems.append("cambió el orden o la cantidad de frames")
            return problems
        for before, after in zip(old.frames, new.frames):
            if before.lyric is None:
                if before.raw != after.raw:
                    problems.append(f"cambió el frame {before.frame_id}, que no es una letra")
                continue
            if after.lyric is None or after.key != before.key:
                problems.append(f"el frame de letra {before.key} desapareció")
                continue
            if before.key in encodings:
                old_head, new_head = before.lyric, after.lyric
                if new_head.encoding != encodings[before.key]:
                    problems.append(f"la codificación del frame {before.key} no quedó como se pidió")
                if (new_head.lang, new_head.desc) != (old_head.lang, old_head.desc) or after.flags != before.flags \
                        or (before.frame_id == "SYLT" and new_head.head[4:6] != old_head.head[4:6]):
                    problems.append(f"cambió la cabecera del frame {before.key}")
            elif after.lyric.head != before.lyric.head or after.flags != before.flags:
                problems.append(f"cambió la cabecera del frame {before.key}")
            new_slots = {(s.key, s.index): s.value for s in ID3Editor._slots_of(after)}
            for key, value in new_slots.items():
                wanted = expected.get(key, None)
                if wanted is None:
                    old_values = {(s.key, s.index): s.value for s in ID3Editor._slots_of(before)}
                    wanted = old_values.get(key)
                if value != wanted:
                    problems.append(f"la letra {before.key} no quedó como se esperaba")
        if new_region[new.padding_offset:].strip(b"\0"):
            problems.append("el relleno no es cero")
        return problems

    @staticmethod
    def _slots_of(frame: Frame) -> list[Slot]:
        lyric = frame.lyric
        if frame.frame_id == "SYLT":
            return [Slot(TAG_FORMAT, frame.key, 0, "SYLT", [(t, time) for t, _b, time in lyric.values])]
        return [Slot(TAG_FORMAT, frame.key, index, frame.frame_id, text)
                for index, (text, _bom) in enumerate(lyric.values)]


# --------------------------------------------------------------------------
# Localización del tag
# --------------------------------------------------------------------------

def open_id3(path: Path) -> ID3Editor:
    """Editor del tag ID3v2 de un MP3 (al inicio) o de un WAV/AIFF (chunk "id3 ")."""
    path = Path(path)
    file_size = path.stat().st_size
    with open(path, "rb") as handle:
        head = handle.read(12)
        if head[:3] == b"ID3":
            handle.seek(0)
            header = handle.read(10)
            length = 10 + syncsafe(header[6:10])
            handle.seek(0)
            return ID3Editor(path, 0, handle.read(length), file_size)
        if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            found = _find_chunk(handle, 12, file_size, "little", {b"id3 ", b"ID3 ", b"id3\0"})
        elif head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
            found = _find_chunk(handle, 12, file_size, "big", {b"ID3 ", b"id3 "})
        else:
            found = None
        if found is None:
            raise Unsupported("id3_position")
        offset, size = found
        handle.seek(offset)
        header = handle.read(10)
        if header[:3] != b"ID3":
            raise Unsupported("id3_position")
        length = 10 + syncsafe(header[6:10])
        if length > size:
            raise Unsupported("id3_invalid", "el tag es más largo que su chunk")
        handle.seek(offset)
        return ID3Editor(path, offset, handle.read(length), file_size, in_chunk=True)


def _find_chunk(handle, position, file_size, byteorder, names):
    while position + 8 <= file_size:
        handle.seek(position)
        header = handle.read(8)
        size = int.from_bytes(header[4:8], byteorder)
        if header[:4] in names:
            return position + 8, size
        position += 8 + size + (size & 1)
    return None
