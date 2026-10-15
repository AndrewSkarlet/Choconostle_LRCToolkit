"""
lrc.py

Análisis de letras (archivos .lrc / .txt y letras incrustadas).

Responsabilidades:
- Detectar si una letra está sincronizada (marcas de tiempo), sin
  importar la extensión del archivo.
- Detectar cabeceras LRC ([ar:], [ti:], [al:], [length:], [offset:]...).
- Detectar BOM y codificaciones distintas de UTF-8.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import codecs
import re
from pathlib import Path

from choconostle.config import LRC_HEADER_TAGS, MAX_LYRICS_FILE_SIZE
from choconostle.models.lyrics import SOURCE_EMBEDDED, SOURCE_EXTERNAL, LyricsInfo

# [mm:ss], [mm:ss.xx], [mm:ss:xx], [mm:ss,xxx] al inicio de la línea
# (puede haber varias seguidas: [00:12.00][01:30.00]Texto).
TIMESTAMP_RE = re.compile(r"^\s*(?:\[\d{1,3}:\d{1,2}(?:[.:,]\d{1,3})?\]\s*)+")

# [etiqueta:valor]; solo cuenta como cabecera si la etiqueta está en
# LRC_HEADER_TAGS.
HEADER_RE = re.compile(r"^\s*\[([A-Za-z#][A-Za-z0-9_#-]*)\s*:(.*)\]\s*$")
_HEADER_TAGS = set(LRC_HEADER_TAGS)

# El orden importa: el BOM de UTF-32 LE empieza igual que el de UTF-16 LE.
_BOMS = [
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
]


def analyze_text(
    text: str,
    source: str,
    location: str,
    encoding: str = "utf-8",
    has_bom: bool = False,
) -> LyricsInfo:
    """
    Analiza el texto de una letra ya decodificada.

    Un carácter U+FEFF al inicio del texto también cuenta como BOM
    (ocurre en letras incrustadas copiadas desde un archivo con BOM).
    """
    if text.startswith("﻿"):
        has_bom = True
        text = text[1:]

    timestamp_lines = 0
    plain_lines = 0
    headers: list[str] = []

    for line in text.splitlines():
        if not line.strip():
            continue
        if TIMESTAMP_RE.match(line):
            timestamp_lines += 1
            continue
        header = HEADER_RE.match(line)
        if header and header.group(1).lower() in _HEADER_TAGS:
            name = header.group(1).lower()
            if name not in headers:
                headers.append(name)
            continue
        plain_lines += 1

    return LyricsInfo(
        source=source,
        location=location,
        synced=timestamp_lines > 0,
        timestamp_lines=timestamp_lines,
        plain_lines=plain_lines,
        headers=headers,
        has_bom=has_bom,
        encoding=encoding,
        is_utf8=encoding in ("utf-8", "ascii"),
        empty=timestamp_lines == 0 and plain_lines == 0,
    )


def decode_bytes(data: bytes) -> tuple[str, str, bool]:
    """
    Decodifica los bytes de una letra.

    Retorna
    -------
    (texto, codificación, tiene_bom)
    """
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data[len(bom):].decode(encoding, errors="replace"), encoding, True

    # UTF-16 sin BOM: muchos bytes nulos en posiciones alternas. Se revisa
    # antes que UTF-8 porque los bytes nulos también son UTF-8 válido.
    if len(data) >= 4:
        even_nulls = data[0::2].count(0)
        odd_nulls = data[1::2].count(0)
        half = len(data) // 2
        if odd_nulls > half * 0.3 and even_nulls < half * 0.05:
            return data.decode("utf-16-le", errors="replace"), "utf-16-le", False
        if even_nulls > half * 0.3 and odd_nulls < half * 0.05:
            return data.decode("utf-16-be", errors="replace"), "utf-16-be", False

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        return text, "ascii" if text.isascii() else "utf-8", False

    # Codificación de 8 bits (lo más común: Windows-1252 / Latin-1).
    try:
        return data.decode("cp1252"), "cp1252", False
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1", False


def analyze_file(path: Path) -> LyricsInfo:
    """Analiza un archivo de letra externo (.lrc o .txt)."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            data = handle.read(MAX_LYRICS_FILE_SIZE)
    except OSError as exc:
        return LyricsInfo(
            source=SOURCE_EXTERNAL,
            location=str(path),
            empty=True,
            error=f"No se pudo leer: {exc.strerror or exc}",
        )

    text, encoding, has_bom = decode_bytes(data)
    info = analyze_text(text, SOURCE_EXTERNAL, str(path), encoding, has_bom)
    if size > MAX_LYRICS_FILE_SIZE:
        info.error = "Archivo demasiado grande; solo se analizó el inicio."
    return info


def analyze_embedded(text: str, tag: str, encoding: str = "utf-8") -> LyricsInfo:
    """Analiza una letra incrustada en las etiquetas del audio."""
    return analyze_text(text, SOURCE_EMBEDDED, tag, encoding)


def analyze_synced_frame(entries: list[tuple[str, int]], tag: str, encoding: str) -> LyricsInfo:
    """
    Analiza una letra sincronizada binaria (ID3 SYLT).

    SYLT guarda pares (texto, tiempo); no tiene cabeceras LRC.
    """
    text_lines = [text for text, _time in entries if text and text.strip()]
    has_bom = any(text.startswith("﻿") for text in text_lines)
    return LyricsInfo(
        source=SOURCE_EMBEDDED,
        location=tag,
        synced=bool(text_lines),
        timestamp_lines=len(text_lines),
        has_bom=has_bom,
        encoding=encoding,
        is_utf8=encoding == "utf-8",
        empty=not text_lines,
    )
