"""
textio.py

Lectura y escritura de texto de letras sin perder bytes.

Responsabilidades:
- Separar líneas solo por CRLF, CR y LF, conservando cada delimitador
  (str.splitlines() también corta en U+2028, U+0085, \\x0c... que aquí
  son contenido).
- Decodificar un archivo de letra de forma reversible: volver a
  codificar el texto da exactamente los mismos bytes.
- Detectar la codificación de archivos de 8 bits con charset-normalizer,
  sin dar por buena una detección ambigua.
- Convertir texto a otra codificación sin sustituir caracteres
  (función compartida por normalize-lyrics --encoding y convert-lyrics).
- Avisar de posible mojibake (sin corregirlo).
- Mostrar diferencias con los caracteres invisibles visibles.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import codecs
import difflib
import re
import unicodedata
from dataclasses import dataclass, field

# Caracteres invisibles que pueden preceder a una cabecera LRC (copiados
# de páginas web o de archivos con BOM). Solo se quitan junto con la
# cabecera; en el resto de la letra no se tocan.
INVISIBLE_PREFIX_CHARS = "​﻿‎‏⁠"

_EOL_RE = re.compile(r"\r\n|\r|\n")
_EOL_BYTES_RE = re.compile(rb"\r\n|\r|\n")

# El orden importa: el BOM de UTF-32 LE empieza igual que el de UTF-16 LE.
BOMS = [
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
]

ENCODING_NAMES = {
    "utf-8": "UTF-8", "ascii": "ASCII", "utf-16-le": "UTF-16 LE", "utf-16-be": "UTF-16 BE",
    "utf-32-le": "UTF-32 LE", "utf-32-be": "UTF-32 BE", "cp1252": "Windows-1252",
    "cp1251": "Windows-1251", "cp1250": "Windows-1250", "latin-1": "Latin-1",
    "iso8859-1": "Latin-1", "shift_jis": "Shift-JIS", "cp932": "Shift-JIS (cp932)",
    "gbk": "GBK", "gb18030": "GB18030", "euc_kr": "EUC-KR", "cp949": "EUC-KR (cp949)",
}

# Detección: candidatos con un "caos" hasta este margen sobre el mejor se
# consideran igual de probables. Si decodifican a textos distintos, la
# detección es ambigua.
_CHAOS_MARGIN = 0.1
_MAX_CHAOS = 0.2


def encoding_label(name: str | None) -> str:
    if not name:
        return "desconocida"
    key = codecs.lookup(name).name if _known_codec(name) else name
    return ENCODING_NAMES.get(name, ENCODING_NAMES.get(key, name))


def _known_codec(name: str) -> bool:
    try:
        codecs.lookup(name)
    except LookupError:
        return False
    return True


# --------------------------------------------------------------------------
# Líneas
# --------------------------------------------------------------------------

def split_lines(text: str) -> list[tuple[str, str]]:
    """
    "a\\r\\nb\\rc" -> [("a", "\\r\\n"), ("b", "\\r"), ("c", "")].

    Unir contenido + delimitador de todas las líneas reproduce el texto
    exacto.
    """
    lines = []
    position = 0
    for match in _EOL_RE.finditer(text):
        lines.append((text[position:match.start()], match.group()))
        position = match.end()
    if position < len(text):
        lines.append((text[position:], ""))
    return lines


def join_lines(lines: list[tuple[str, str]]) -> str:
    return "".join(content + eol for content, eol in lines)


def line_contents(text: str) -> list[str]:
    """Contenido de cada línea, sin delimitadores."""
    return [content for content, _eol in split_lines(text)]


def eol_summary(text: str) -> str:
    """"LF", "CRLF", "CR", "mixtos (CRLF, LF)" o "-" si no hay saltos."""
    names = {"\n": "LF", "\r\n": "CRLF", "\r": "CR"}
    found = list(dict.fromkeys(names[match.group()] for match in _EOL_RE.finditer(text)))
    if not found:
        return "-"
    return found[0] if len(found) == 1 else f"mixtos ({', '.join(found)})"


def strip_invisible_prefix(text: str) -> tuple[str, str]:
    """("\\u200b[ti:x]") -> ("\\u200b", "[ti:x]")."""
    core = text.lstrip(INVISIBLE_PREFIX_CHARS)
    return text[:len(text) - len(core)], core


# --------------------------------------------------------------------------
# Detección de codificación
# --------------------------------------------------------------------------

@dataclass
class Detection:
    """Resultado de detectar la codificación de bytes de 8 bits."""
    encoding: str | None
    """Mejor candidato (nombre de códec de Python), o None."""
    confident: bool
    candidates: list[str] = field(default_factory=list)
    """Candidatos igual de probables que decodifican a textos distintos."""
    invalid_utf8: int = 0
    """Si > 0: es casi todo UTF-8, con esta cantidad de secuencias inválidas."""

    def describe(self) -> str:
        if self.invalid_utf8:
            return f"UTF-8 con {plural_bytes(self.invalid_utf8)} inválidos"
        if self.encoding is None:
            return "no se pudo detectar la codificación"
        if self.confident:
            return f"detectada {encoding_label(self.encoding)}"
        names = [encoding_label(name) for name in self.candidates[:3]] or [encoding_label(self.encoding)]
        more = ", ..." if len(self.candidates) > 3 else ""
        return f"codificación ambigua ({', '.join(names)}{more})"


def plural_bytes(count: int) -> str:
    return f"{count} byte" if count == 1 else f"{count} bytes"


def _mostly_utf8(data: bytes) -> int:
    """
    Cantidad de secuencias inválidas si los bytes son casi todo UTF-8
    (p. ej. un fragmento pegado desde Windows-1252), o 0 si no lo son.
    """
    text = data.decode("utf-8", errors="replace")
    invalid = text.count("\ufffd") - data.decode("utf-8", errors="ignore").count("\ufffd")
    valid_multibyte = sum(1 for char in text if ord(char) > 127 and char != "\ufffd")
    if invalid and valid_multibyte >= 3 * invalid:
        return invalid
    return 0


def detect_encoding(data: bytes) -> Detection:
    """
    Detecta la codificación de bytes que no son UTF-8 válido ni tienen BOM.

    Es fiable solo si todos los candidatos igual de probables decodifican
    al mismo texto y volver a codificar da los mismos bytes. Un archivo
    casi todo UTF-8 con algunos bytes inválidos nunca es fiable.
    """
    invalid = _mostly_utf8(data)
    if invalid:
        return Detection(None, False, invalid_utf8=invalid)
    try:
        from charset_normalizer import from_bytes
    except ImportError:  # pragma: no cover - dependencia declarada
        return Detection(None, False)

    results = from_bytes(data)
    best = results.best()
    if best is None:
        return Detection(None, False)
    texts: dict[str, list[str]] = {}
    for match in results:
        if match.chaos <= best.chaos + _CHAOS_MARGIN:
            texts.setdefault(str(match), []).append(match.encoding)
    candidates = [names[0] for names in texts.values()]
    confident = len(texts) == 1 and best.chaos <= _MAX_CHAOS
    if confident:
        try:
            confident = data.decode(best.encoding).encode(best.encoding) == data
        except (UnicodeError, LookupError):
            confident = False
    return Detection(best.encoding, confident, candidates if len(candidates) > 1 else [])


# --------------------------------------------------------------------------
# Decodificación reversible
# --------------------------------------------------------------------------

class LyricsDecodeError(Exception):
    """Los bytes no corresponden a la codificación que indica su BOM."""


@dataclass
class DecodedLyrics:
    """
    Texto de un archivo de letra listo para procesar sin perder bytes.

    `text` usa `codec`; `bom + text.encode(codec)` reproduce el archivo.
    Si la codificación real no se conoce con certeza (8 bits que no son
    UTF-8), `codec` es "latin-1": cada byte es un carácter, así que las
    cabeceras y marcas de tiempo (ASCII) se pueden quitar o ajustar sin
    tocar los demás bytes, aunque no se sepa qué idioma es.
    """
    text: str
    codec: str
    bom: bytes
    exact: bool
    """True si `codec` es la codificación real del archivo."""
    detection: Detection | None = None
    """Solo para archivos de 8 bits (exact=False)."""

    @property
    def source_encoding(self) -> str | None:
        """Codificación real si se conoce con confianza."""
        if self.exact:
            return self.codec
        if self.detection is not None and self.detection.confident:
            return self.detection.encoding
        return None

    @property
    def label(self) -> str:
        if self.exact:
            name = "ascii" if self.codec == "utf-8" and self.text.isascii() and not self.bom else self.codec
            return encoding_label(name) + (" con BOM" if self.bom else "")
        return self.detection.describe() if self.detection else "8 bits desconocida"

    def encode(self, text: str) -> bytes:
        """Codifica texto del mismo "espacio" (codec) que `self.text`."""
        return self.bom + text.encode(self.codec)

    def real_text(self, text: str) -> str | None:
        """Texto real (Unicode) de un texto en el espacio de `codec`, o None si no se sabe."""
        if self.exact:
            return text
        encoding = self.source_encoding
        if encoding is None:
            return None
        return text.encode(self.codec).decode(encoding)

    def display(self, text: str) -> tuple[str, bool]:
        """(texto para mostrar, es_aproximado)."""
        real = self.real_text(text)
        if real is not None:
            return real, False
        detection = self.detection
        if detection is not None and detection.invalid_utf8:
            guess = "utf-8"
        else:
            guess = detection.encoding if detection and detection.encoding else "cp1252"
        return text.encode(self.codec).decode(guess, errors="replace"), True


def _utf16_without_bom(data: bytes) -> str | None:
    """UTF-16 sin BOM: muchos bytes nulos en posiciones alternas."""
    if len(data) < 4:
        return None
    even_nulls = data[0::2].count(0)
    odd_nulls = data[1::2].count(0)
    half = len(data) // 2
    if odd_nulls > half * 0.3 and even_nulls < half * 0.05:
        return "utf-16-le"
    if even_nulls > half * 0.3 and odd_nulls < half * 0.05:
        return "utf-16-be"
    return None


def decode_lyrics(data: bytes) -> DecodedLyrics:
    """
    Decodifica un archivo de letra de forma reversible.

    Lanza LyricsDecodeError si el BOM (o el patrón de UTF-16) indica una
    codificación y los bytes no son válidos en ella.
    """
    codec = bom = None
    for candidate_bom, name in BOMS:
        if data.startswith(candidate_bom):
            codec, bom = name, candidate_bom
            break
    if codec is None:
        codec = _utf16_without_bom(data)
        bom = b""
    if codec is not None:
        body = data[len(bom):]
        try:
            text = body.decode(codec)
        except UnicodeDecodeError as exc:
            raise LyricsDecodeError(f"Bytes inválidos para {encoding_label(codec)}.") from exc
        if text.encode(codec) != body:
            raise LyricsDecodeError(f"El texto no se puede volver a codificar igual en {encoding_label(codec)}.")
        return DecodedLyrics(text, codec, bom, exact=True)

    try:
        return DecodedLyrics(data.decode("utf-8"), "utf-8", b"", exact=True)
    except UnicodeDecodeError:
        pass
    return DecodedLyrics(data.decode("latin-1"), "latin-1", b"", exact=False,
                         detection=detect_encoding(data))


# --------------------------------------------------------------------------
# Conversión (normalize-lyrics --encoding y convert-lyrics --to)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TargetEncoding:
    """Codificación de destino de un archivo de letra."""
    codec: str
    bom: bytes = b""
    name: str = ""

    @property
    def label(self) -> str:
        return encoding_label(self.codec) + (" con BOM" if self.bom else "")


class EncodingOptionError(ValueError):
    """Nombre de codificación desconocido o no válido para texto."""


def parse_target_encoding(value: str) -> TargetEncoding | None:
    """
    "keep" -> None (conservar); "utf8" -> UTF-8 sin BOM; "utf8-bom" -> UTF-8
    con BOM; cualquier otro nombre de códec de texto de Python
    ("cp1252", "shift_jis", "utf-16"...).
    """
    key = value.strip().lower()
    if key == "keep":
        return None
    if key in ("utf8", "utf-8"):
        return TargetEncoding("utf-8", b"", "utf8")
    if key in ("utf8-bom", "utf-8-bom", "utf-8-sig"):
        return TargetEncoding("utf-8", codecs.BOM_UTF8, "utf8-bom")
    try:
        info = codecs.lookup(key)
    except LookupError as exc:
        raise EncodingOptionError(f"Codificación desconocida: {value}") from exc
    if not getattr(info, "_is_text_encoding", True):
        raise EncodingOptionError(f"{value} no es una codificación de texto.")
    return TargetEncoding(info.name, b"", key)


class UnencodableError(Exception):
    """El texto tiene caracteres que no existen en la codificación de destino."""

    def __init__(self, target: TargetEncoding, chars: list[str], count: int):
        self.target = target
        self.chars = chars
        self.count = count
        sample = " ".join(f"«{char}» ({unicode_name(char)})" for char in chars[:5])
        more = f" y {len(chars) - 5} más" if len(chars) > 5 else ""
        super().__init__(
            f"{count} caracteres no se pueden representar en {target.label}: {sample}{more}")


def encode_text(text: str, target: TargetEncoding) -> bytes:
    """
    Codifica `text` en la codificación de destino.

    Nunca sustituye caracteres: si alguno no se puede representar, lanza
    UnencodableError con la lista completa.
    """
    try:
        return target.bom + text.encode(target.codec)
    except UnicodeEncodeError:
        pass
    bad: dict[str, None] = {}
    count = 0
    for char in text:
        try:
            char.encode(target.codec)
        except UnicodeEncodeError:
            bad.setdefault(char)
            count += 1
    raise UnencodableError(target, list(bad), count)


# --------------------------------------------------------------------------
# Mojibake
# --------------------------------------------------------------------------

# Un carácter de Latin-1 que suele ser el primer byte de UTF-8 (Ã, Â, â...)
# seguido de caracteres que en Windows-1252 son bytes de continuación.
_MOJIBAKE_RE = re.compile(
    "[Â-ô]"
    "[\u0080-¿ŒœŠšŸŽžƒˆ˜"
    "–—‘-„†-•…‰‹›€™]{1,3}"
)


def find_mojibake(text: str, limit: int = 3) -> list[tuple[str, str]]:
    """
    Fragmentos que parecen UTF-8 leído como Windows-1252 ("CanciÃ³n").

    Retorna [(fragmento, cómo se leería)]; no modifica nada.
    """
    found = []
    for match in _MOJIBAKE_RE.finditer(text):
        fragment = match.group()
        for codec in ("cp1252", "latin-1"):
            try:
                fixed = fragment.encode(codec).decode("utf-8")
            except UnicodeError:
                continue
            if not fixed.isascii():
                found.append((fragment, fixed))
                break
        if len(found) >= limit:
            break
    return found


# --------------------------------------------------------------------------
# Vista de diferencias
# --------------------------------------------------------------------------

def unicode_name(char: str) -> str:
    return f"U+{ord(char):04X} {unicodedata.name(char, '')}".strip()


def visible(text: str) -> str:
    """Muestra los caracteres invisibles o de control como ⟨U+200B⟩."""
    out = []
    for char in text:
        category = unicodedata.category(char)
        if char != "\t" and (category in ("Cf", "Cc", "Zl", "Zp") or char in " 　"):
            out.append(f"⟨U+{ord(char):04X}⟩")
        else:
            out.append(char)
    return "".join(out)


def diff_lines(original: str, new: str, context: int = 1) -> list[str]:
    """Diferencias unificadas por línea (sin las dos líneas de título)."""
    lines = list(difflib.unified_diff(
        [visible(line) for line in line_contents(original)],
        [visible(line) for line in line_contents(new)],
        "original", "nuevo", lineterm="", n=context,
    ))
    return lines[2:]
