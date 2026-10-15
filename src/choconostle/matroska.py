"""
matroska.py

Lector mínimo de Matroska (.mka) para identificar el códec de audio,
las etiquetas básicas, las letras (LYRICS) y la portada adjunta.

mutagen no soporta Matroska, así que se recorre la estructura EBML
directamente. Solo se leen los elementos necesarios; los bloques de
audio (Clusters) se saltan sin leerlos.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Iterator

EBML_MAGIC = b"\x1a\x45\xdf\xa3"

# IDs de elementos EBML / Matroska.
_EBML = 0x1A45DFA3
_DOCTYPE = 0x4282
_SEGMENT = 0x18538067
_INFO = 0x1549A966
_TIMESTAMP_SCALE = 0x2AD7B1
_DURATION = 0x4489
_TITLE = 0x7BA9
_TRACKS = 0x1654AE6B
_TRACK_ENTRY = 0xAE
_TRACK_TYPE = 0x83
_CODEC_ID = 0x86
_AUDIO = 0xE1
_SAMPLING_FREQUENCY = 0xB5
_CHANNELS = 0x9F
_BIT_DEPTH = 0x6264
_TAGS = 0x1254C367
_TAG = 0x7373
_TARGETS = 0x63C0
_TARGET_TYPE_VALUE = 0x68CA
_SIMPLE_TAG = 0x67C8
_TAG_NAME = 0x45A3
_TAG_STRING = 0x4487
_ATTACHMENTS = 0x1941A469
_ATTACHED_FILE = 0x61A7
_FILE_MEDIA_TYPE = 0x4660
_FILE_NAME = 0x466E

_TRACK_TYPE_AUDIO = 2
_UNKNOWN_SIZE = -1
_MAX_LEAF_SIZE = 1024 * 1024


class MatroskaError(Exception):
    """El archivo no es Matroska válido."""


@dataclass
class MatroskaInfo:
    doctype: str = "matroska"
    codec_id: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    bits_per_sample: int | None = None
    duration: float | None = None
    title: str | None = None
    """Título del segmento (ffmpeg guarda aquí el título de la canción)."""
    tags: dict[str, str] = field(default_factory=dict)
    """Etiquetas de pista (TargetTypeValue 30 o sin nivel)."""
    album_tags: dict[str, str] = field(default_factory=dict)
    """Etiquetas de álbum (TargetTypeValue 50)."""
    has_cover: bool = False


def _read_vint(handle: BinaryIO, keep_marker: bool) -> tuple[int, int]:
    """Lee un entero de longitud variable. Retorna (valor, bytes_leídos)."""
    first = handle.read(1)
    if not first:
        raise EOFError
    byte = first[0]
    length = 1
    mask = 0x80
    while length <= 8 and not byte & mask:
        mask >>= 1
        length += 1
    if length > 8:
        raise MatroskaError("Entero EBML inválido.")
    rest = handle.read(length - 1)
    if len(rest) != length - 1:
        raise EOFError
    value = byte if keep_marker else byte & (mask - 1)
    all_ones = (byte & (mask - 1)) == mask - 1
    for extra in rest:
        value = (value << 8) | extra
        all_ones = all_ones and extra == 0xFF
    if not keep_marker and all_ones:
        return _UNKNOWN_SIZE, length
    return value, length


def _children(handle: BinaryIO, start: int, end: int | None) -> Iterator[tuple[int, int, int]]:
    """Recorre los hijos de un elemento. Produce (id, inicio_datos, tamaño)."""
    pos = start
    while end is None or pos < end:
        handle.seek(pos)
        try:
            element_id, id_len = _read_vint(handle, keep_marker=True)
            size, size_len = _read_vint(handle, keep_marker=False)
        except EOFError:
            return
        data_start = pos + id_len + size_len
        yield element_id, data_start, size
        if size == _UNKNOWN_SIZE:
            return
        pos = data_start + size


def _read_bytes(handle: BinaryIO, start: int, size: int) -> bytes:
    if size < 0 or size > _MAX_LEAF_SIZE:
        return b""
    handle.seek(start)
    return handle.read(size)


def _read_uint(handle: BinaryIO, start: int, size: int) -> int:
    return int.from_bytes(_read_bytes(handle, start, size), "big") if 0 < size <= 8 else 0


def _read_float(handle: BinaryIO, start: int, size: int) -> float | None:
    data = _read_bytes(handle, start, size)
    if size == 4:
        return struct.unpack(">f", data)[0]
    if size == 8:
        return struct.unpack(">d", data)[0]
    return None


def _read_str(handle: BinaryIO, start: int, size: int) -> str:
    return _read_bytes(handle, start, size).rstrip(b"\x00").decode("utf-8", errors="replace")


def _parse_track_entry(handle: BinaryIO, start: int, end: int, info: MatroskaInfo) -> None:
    track_type = None
    codec_id = None
    audio: tuple[int, int] | None = None
    for element_id, data_start, size in _children(handle, start, end):
        if element_id == _TRACK_TYPE:
            track_type = _read_uint(handle, data_start, size)
        elif element_id == _CODEC_ID:
            codec_id = _read_str(handle, data_start, size)
        elif element_id == _AUDIO:
            audio = (data_start, size)

    if track_type != _TRACK_TYPE_AUDIO or info.codec_id is not None:
        return
    info.codec_id = codec_id
    if audio is None:
        return
    for element_id, data_start, size in _children(handle, audio[0], audio[0] + audio[1]):
        if element_id == _SAMPLING_FREQUENCY:
            rate = _read_float(handle, data_start, size)
            info.sample_rate = int(rate) if rate else None
        elif element_id == _CHANNELS:
            info.channels = _read_uint(handle, data_start, size)
        elif element_id == _BIT_DEPTH:
            info.bits_per_sample = _read_uint(handle, data_start, size)


def _parse_tag(handle: BinaryIO, start: int, end: int, info: MatroskaInfo) -> None:
    # Sin TargetTypeValue explícito se tratan como etiquetas de la pista:
    # en un .mka de una sola canción (ffmpeg, mkvmerge) así se guardan
    # el título y el artista.
    target = 0
    simple_tags: list[tuple[int, int]] = []
    for element_id, data_start, size in _children(handle, start, end):
        if element_id == _TARGETS:
            for sub_id, sub_start, sub_size in _children(handle, data_start, data_start + size):
                if sub_id == _TARGET_TYPE_VALUE:
                    target = _read_uint(handle, sub_start, sub_size)
        elif element_id == _SIMPLE_TAG:
            simple_tags.append((data_start, size))

    destination = info.album_tags if target >= 50 else info.tags
    for data_start, size in simple_tags:
        name = value = None
        for sub_id, sub_start, sub_size in _children(handle, data_start, data_start + size):
            if sub_id == _TAG_NAME:
                name = _read_str(handle, sub_start, sub_size)
            elif sub_id == _TAG_STRING:
                value = _read_str(handle, sub_start, sub_size)
        if name and value is not None:
            destination.setdefault(name.upper(), value)


def _parse_attachments(handle: BinaryIO, start: int, end: int, info: MatroskaInfo) -> None:
    for element_id, data_start, size in _children(handle, start, end):
        if element_id != _ATTACHED_FILE:
            continue
        for sub_id, sub_start, sub_size in _children(handle, data_start, data_start + size):
            if sub_id == _FILE_MEDIA_TYPE:
                if _read_str(handle, sub_start, sub_size).lower().startswith("image/"):
                    info.has_cover = True


def read_matroska(handle: BinaryIO) -> MatroskaInfo:
    """Lee un archivo Matroska abierto en modo binario."""
    handle.seek(0, 2)
    file_size = handle.tell()
    handle.seek(0)
    if handle.read(4) != EBML_MAGIC:
        raise MatroskaError("No es un archivo Matroska.")

    info = MatroskaInfo()
    segment: tuple[int, int] | None = None
    for element_id, data_start, size in _children(handle, 0, file_size):
        if element_id == _EBML:
            for sub_id, sub_start, sub_size in _children(handle, data_start, data_start + size):
                if sub_id == _DOCTYPE:
                    info.doctype = _read_str(handle, sub_start, sub_size)
        elif element_id == _SEGMENT:
            end = file_size if size == _UNKNOWN_SIZE else min(data_start + size, file_size)
            segment = (data_start, end)
            break
    if segment is None:
        raise MatroskaError("Matroska sin segmento.")

    timestamp_scale = 1_000_000
    raw_duration = None
    for element_id, data_start, size in _children(handle, segment[0], segment[1]):
        if size == _UNKNOWN_SIZE:
            # Un elemento de tamaño desconocido (normalmente un Cluster en
            # una grabación en vivo) impide saltar al resto del archivo.
            break
        end = data_start + size
        if element_id == _INFO:
            for sub_id, sub_start, sub_size in _children(handle, data_start, end):
                if sub_id == _TIMESTAMP_SCALE:
                    timestamp_scale = _read_uint(handle, sub_start, sub_size) or timestamp_scale
                elif sub_id == _DURATION:
                    raw_duration = _read_float(handle, sub_start, sub_size)
                elif sub_id == _TITLE:
                    info.title = _read_str(handle, sub_start, sub_size) or None
        elif element_id == _TRACKS:
            for sub_id, sub_start, sub_size in _children(handle, data_start, end):
                if sub_id == _TRACK_ENTRY:
                    _parse_track_entry(handle, sub_start, sub_start + sub_size, info)
        elif element_id == _TAGS:
            for sub_id, sub_start, sub_size in _children(handle, data_start, end):
                if sub_id == _TAG:
                    _parse_tag(handle, sub_start, sub_start + sub_size, info)
        elif element_id == _ATTACHMENTS:
            _parse_attachments(handle, data_start, end, info)

    if raw_duration:
        info.duration = raw_duration * timestamp_scale / 1e9
    return info
