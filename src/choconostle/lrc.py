"""
lrc.py

Análisis de letras (archivos .lrc / .txt y letras incrustadas).

Responsabilidades:
- Detectar si una letra está sincronizada (marcas de tiempo), sin
  importar la extensión del archivo.
- Detectar cabeceras LRC ([ar:], [ti:], [al:], [length:], [offset:]...),
  también precedidas de caracteres invisibles (U+200B, U+FEFF...).
- Detectar BOM y codificaciones distintas de UTF-8.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import codecs
import re
from pathlib import Path

from choconostle.config import LRC_HEADER_TAGS, MAX_LYRICS_FILE_SIZE, NEARLY_EMPTY_MAX_LINES
from choconostle.models.lyrics import SOURCE_EMBEDDED, SOURCE_EXTERNAL, LyricsInfo
from choconostle.textio import line_contents, strip_invisible_prefix

# [mm:ss], [mm:ss.xx], [mm:ss:xx], [mm:ss,xxx] al inicio de la línea
# (puede haber varias seguidas: [00:12.00][01:30.00]Texto).
# Las expresiones usan re.ASCII: \s y \d no incluyen espacios ni dígitos
# de otros alfabetos (U+3000, dígitos árabes...), que son texto de la letra.
TIMESTAMP_RE = re.compile(r"^\s*(?:\[\d{1,3}:\d{1,2}(?:[.:,]\d{1,3})?\]\s*)+", re.ASCII)

# [etiqueta:valor]; solo cuenta como cabecera si la etiqueta está en
# LRC_HEADER_TAGS.
HEADER_RE = re.compile(r"^\s*\[([A-Za-z#][A-Za-z0-9_#-]*)\s*:(.*)\]\s*$", re.ASCII)
_HEADER_TAGS = set(LRC_HEADER_TAGS)

# Marcas de tiempo por palabra del formato LRC mejorado: <mm:ss.xx>.
WORD_TIMESTAMP_RE = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:,]\d{1,3})?>", re.ASCII)

# El orden importa: el BOM de UTF-32 LE empieza igual que el de UTF-16 LE.
_BOMS = [
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
]


def header_name(line: str) -> str | None:
    """
    Nombre de la cabecera LRC conocida de la línea ("ar", "offset"...) o
    None. Admite caracteres invisibles antes del corchete.
    """
    key = header_key(line)
    if key is not None and key.lower() in _HEADER_TAGS:
        return key.lower()
    return None


def header_key(line: str) -> str | None:
    """
    Clave de cualquier línea con forma [palabra:valor] (conocida o no),
    o None. Las marcas de tiempo no cuentan.
    """
    _prefix, core = strip_invisible_prefix(line)
    if TIMESTAMP_RE.match(core):
        return None
    match = HEADER_RE.match(core)
    return match.group(1) if match else None


def header_value(line: str) -> str:
    _prefix, core = strip_invisible_prefix(line)
    match = HEADER_RE.match(core)
    return match.group(2).strip() if match else ""


def has_text_after_timestamps(line: str, match: re.Match) -> bool:
    return bool(WORD_TIMESTAMP_RE.sub("", line[match.end():]).strip())


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
    if text.startswith("\ufeff"):
        has_bom = True
        text = text[1:]

    timestamp_lines = 0
    plain_lines = 0
    content_lines = 0
    headers: list[str] = []

    for line in line_contents(text):
        if not line.strip():
            continue
        timestamp = TIMESTAMP_RE.match(line)
        if timestamp:
            timestamp_lines += 1
            if has_text_after_timestamps(line, timestamp):
                content_lines += 1
            continue
        name = header_name(line)
        if name:
            if name not in headers:
                headers.append(name)
            continue
        plain_lines += 1
        content_lines += 1

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
        content_lines=content_lines,
        nearly_empty=content_lines <= NEARLY_EMPTY_MAX_LINES,
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
    has_bom = any(text.startswith("\ufeff") for text in text_lines)
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
