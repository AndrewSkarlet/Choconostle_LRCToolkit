"""
rawtags

Edición de letras incrustadas byte a byte (sin reescribir las demás
etiquetas).

mutagen vuelve a serializar todas las etiquetas al guardar: en ID3 añade
terminadores y reordena frames, en APEv2 ordena los campos por tamaño y en
MP4 añade un átomo "free". Estos editores solo reemplazan los bytes de la
letra y los campos de tamaño o relleno imprescindibles.

Cada editor:
- localiza la "región" de etiquetas del archivo (tag ID3, bloques de
  metadatos FLAC, átomo moov, tag APEv2);
- lista las letras (slots);
- construye una edición como lista de parches (posición, bytes viejos,
  bytes nuevos) sobre esa región;
- verifica que, en la región nueva, todo lo que no es letra es idéntico.

Los parches son también el respaldo: aplicarlos al revés restaura la
región original exacta sin guardar portadas ni audio.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field

# Modos de escritura.
MODE_INPLACE = "inplace"
"""La región conserva su tamaño: se sobrescribe en su sitio."""
MODE_TAIL = "tail"
"""La región llega hasta el final del archivo y cambia de tamaño."""
MODE_FULL = "full"
"""Hay que desplazar el audio: se reescribe el archivo completo (copia temporal)."""

# Motivos para no editar un archivo (se cuentan en el resumen).
REASONS = {
    "id3v22": "ID3v2.2 (no se edita; mutagen lo convertiría a 2.3/2.4)",
    "id3_version": "versión de ID3 desconocida",
    "id3_unsync": "ID3 con unsynchronisation",
    "id3_crc": "ID3 con CRC en la cabecera extendida",
    "id3_footer": "ID3v2.4 con pie (footer)",
    "id3_position": "ID3 en una posición no soportada",
    "id3_invalid": "estructura ID3 no válida",
    "id3_frame_flags": "frame de letra comprimido, cifrado o con otras marcas",
    "id3_frame_format": "frame de letra con formato no reproducible",
    "id3_unencodable": "el texto nuevo no cabe en la codificación del frame",
    "id3_utf8_needs_v24": "UTF-8 en ID3 solo es válido en ID3v2.4 (el tag es v2.3)",
    "id3_chunk_grow": "ID3 dentro de WAV/AIFF sin relleno suficiente",
    "flac_invalid": "estructura FLAC no válida",
    "vorbis_invalid": "comentario Vorbis no válido",
    "mp4_no_padding": "M4A sin relleno (moov antes de mdat)",
    "mp4_64bit": "M4A con átomos de 64 bits",
    "mp4_invalid": "estructura MP4 no válida",
    "mp4_value_type": "M4A con letra en un formato distinto de texto UTF-8",
    "ape_invalid": "estructura APEv2 no válida",
    "full_rewrite": "reescritura completa (requiere --allow-full-rewrite)",
    "matroska": "Matroska (.mka): solo lectura",
    "no_tags": "formato de etiquetas no compatible",
}


class Unsupported(Exception):
    """No se puede editar este archivo de forma segura."""

    def __init__(self, reason: str, message: str | None = None):
        self.reason = reason
        super().__init__(message or REASONS.get(reason, reason))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Patch:
    """Reemplaza `old` (en `offset` de la región original) por `new`."""
    offset: int
    old: bytes
    new: bytes


def apply_patches(region: bytes, patches: list[Patch]) -> bytes:
    """Aplica parches no solapados (en coordenadas de la región original)."""
    out = []
    position = 0
    for patch in sorted(patches, key=lambda p: p.offset):
        if patch.offset < position:
            raise ValueError("parches solapados")
        if region[patch.offset:patch.offset + len(patch.old)] != patch.old:
            raise ValueError(f"el parche en {patch.offset} no coincide con la región")
        out.append(region[position:patch.offset])
        out.append(patch.new)
        position = patch.offset + len(patch.old)
    out.append(region[position:])
    return b"".join(out)


def invert_patches(patches: list[Patch]) -> list[Patch]:
    """Parches que convierten la región nueva en la original."""
    inverse = []
    shift = 0
    for patch in sorted(patches, key=lambda p: p.offset):
        inverse.append(Patch(patch.offset + shift, patch.new, patch.old))
        shift += len(patch.new) - len(patch.old)
    return inverse


def _pack(data: bytes):
    if data and not data.strip(b"\0"):
        return {"zeros": len(data)}
    return base64.b64encode(data).decode("ascii")


def _unpack(value) -> bytes:
    if isinstance(value, dict):
        return b"\0" * value["zeros"]
    return base64.b64decode(value)


def patches_to_json(patches: list[Patch]) -> list[dict]:
    return [{"offset": p.offset, "old": _pack(p.old), "new": _pack(p.new)} for p in patches]


def patches_from_json(items: list[dict]) -> list[Patch]:
    return [Patch(item["offset"], _unpack(item["old"]), _unpack(item["new"])) for item in items]


@dataclass
class Edit:
    """Edición planeada de la región de etiquetas de un archivo."""
    patches: list[Patch]
    mode: str
    old_len: int
    new_len: int
    note: str = ""
    """Detalle para el reporte (p. ej. "relleno ID3 256 -> 512 bytes")."""
    expected: dict = field(default_factory=dict)
    """{(clave, índice): valor} de las letras tras la edición."""
    encodings: dict = field(default_factory=dict)
    """ID3: {clave del frame: codificación nueva} (convert-lyrics --id3-encoding)."""


@dataclass
class Slot:
    """Una letra incrustada concreta dentro de un archivo de audio."""
    tag_format: str
    key: str
    """Clave estable dentro del archivo ("USLT:eng:#0", "lyrics", "\xa9lyr"...)."""
    index: int
    """Índice del valor (varios campos con la misma clave, o valores de un TXXX)."""
    label: str
    """Nombre corto para mostrar: USLT, SYLT, TXXX:LYRICS, LYRICS, ©lyr..."""
    value: object
    """str, o lista de (texto, tiempo) para SYLT."""
    id3_encoding: int | None = None

    @property
    def is_sylt(self) -> bool:
        return self.label == "SYLT"

    def ref(self) -> dict:
        """Identificador serializable (para el manifiesto)."""
        return {"tag_format": self.tag_format, "key": self.key, "index": self.index, "label": self.label}
