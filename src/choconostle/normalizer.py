"""
normalizer.py

Normalización de letras (comando normalize-lyrics).

Dos modos:
- strip: quita las cabeceras LRC conocidas ([ar:], [ti:], [by:],
  [offset:]...). Si hay un único [offset:] válido, lo aplica a cada marca
  de tiempo antes de quitarlo.
- standardize: deja solo un conjunto fijo de cabeceras (ar, ti, al,
  length) con datos tomados de las etiquetas de la canción. Si falta un
  dato, esa cabecera no se escribe.

Se aplica a todas las copias de la letra: archivo .lrc/.txt y etiquetas
incrustadas.

Principio: solo cambia lo que se pidió. Las líneas que no son cabeceras
se conservan byte por byte (codificación, BOM, saltos de línea mixtos,
caracteres invisibles), salvo las marcas de tiempo al aplicar un offset.
Si algo no se puede hacer con seguridad (varios offsets, offset
inválido), el archivo no se toca y se lista para revisión.

Autor: AndrewSkarlet
Licencia: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from choconostle import lrc
from choconostle.config import NEARLY_EMPTY_MAX_LINES, STANDARD_HEADERS
from choconostle.embedded import Slot, open_editor
from choconostle.rawtags import MODE_FULL, REASONS, Unsupported, apply_patches, sha256
from choconostle.rawtags.ogg import OggEditor
from choconostle.rawtags.writer import Journal, file_signature, required_space
from choconostle.models.lyrics import SOURCE_EXTERNAL
from choconostle.models.track import Track
from choconostle.scanner import LibraryScan
from choconostle.textio import (
    LyricsDecodeError, TargetEncoding, UnencodableError, decode_lyrics, encode_text,
    encoding_label, find_mojibake, parse_target_encoding, split_lines, strip_invisible_prefix,
)
from choconostle.utils import format_size, plural

MODE_STRIP = "strip"
MODE_STANDARDIZE = "standardize"

ENCODING_KEEP = "keep"
ENCODING_UTF8 = "utf8"
ENCODING_UTF8_BOM = "utf8-bom"

OFFSET_SKIP = "skip"
OFFSET_FIRST = "first"
OFFSET_LAST = "last"
OFFSET_SUM = "sum"
OFFSET_POLICIES = (OFFSET_SKIP, OFFSET_FIRST, OFFSET_LAST, OFFSET_SUM)

KIND_FILE = "file"
KIND_EMBEDDED = "embedded"

STATUS_CHANGE = "change"
STATUS_UNCHANGED = "unchanged"
STATUS_DECISION = "decision"
"""No se tocó: requiere una decisión del usuario (offsets)."""
STATUS_SKIPPED = "skipped"
STATUS_ERROR = "error"

_TIMESTAMP_PART_RE = re.compile(r"([\[<])(\d{1,3}):(\d{1,2})(?:([.:,])(\d{1,3}))?([\]>])", re.ASCII)
_INLINE_TIMESTAMP_RE = re.compile(r"\[\d{1,3}:\d{1,2}(?:[.:,]\d{1,3})?\]", re.ASCII)
_OFFSET_VALUE_RE = re.compile(r"([+-]?)\s*(\d+)", re.ASCII)

# Clases de línea.
_SYNCED = "synced"
_HEADER = "header"
_UNKNOWN = "unknown"
_BLANK = "blank"
_TEXT = "text"


# --------------------------------------------------------------------------
# Marcas de tiempo
# --------------------------------------------------------------------------

def _format_timestamp(match: re.Match, total_ms: int) -> str:
    """Reescribe una marca de tiempo con el mismo estilo que la original."""
    opening, minutes_text, _seconds, separator, fraction, closing = match.groups()
    digits = len(fraction) if fraction else 0
    if digits == 0 and total_ms % 1000:
        separator, digits = ".", 2
    unit = 10 ** (3 - digits) if digits else 1000
    units = round(total_ms / unit)
    per_second = 1000 // unit
    seconds_total, frac_value = divmod(units, per_second)
    minutes, seconds = divmod(seconds_total, 60)
    text = f"{opening}{minutes:0{max(2, len(minutes_text))}d}:{seconds:02d}"
    if digits:
        text += f"{separator}{frac_value:0{digits}d}"
    return text + closing


def _timestamp_ms(match: re.Match) -> int:
    _opening, minutes, seconds, _separator, fraction, _closing = match.groups()
    total = (int(minutes) * 60 + int(seconds)) * 1000
    if fraction:
        total += int(fraction) * 10 ** (3 - len(fraction))
    return total


def shift_line(line: str, offset_ms: int) -> tuple[str, int, int]:
    """
    Aplica un [offset:] a las marcas de tiempo de una línea sincronizada.

    Según el formato LRC, un offset positivo adelanta la letra (aparece
    antes): nuevo_tiempo = tiempo - offset. Los tiempos negativos quedan
    en 0. Se ajustan las marcas del inicio [mm:ss.xx] y las marcas por
    palabra <mm:ss.xx>; los corchetes dentro del texto no se tocan.

    Retorna (línea, marcas_modificadas, marcas_recortadas_a_cero).
    """
    prefix, core = strip_invisible_prefix(line)
    leading = lrc.TIMESTAMP_RE.match(core)
    if not leading:
        return line, 0, 0
    shifted = clamped = 0

    def replace(match: re.Match) -> str:
        nonlocal shifted, clamped
        new_ms = _timestamp_ms(match) - offset_ms
        if new_ms < 0:
            new_ms = 0
            clamped += 1
        shifted += 1
        return _format_timestamp(match, new_ms)

    head = _TIMESTAMP_PART_RE.sub(replace, core[:leading.end()])
    tail = lrc.WORD_TIMESTAMP_RE.sub(lambda m: _TIMESTAMP_PART_RE.sub(replace, m.group(0)),
                                     core[leading.end():])
    return prefix + head + tail, shifted, clamped


def _offset_problem(line: str) -> str | None:
    """Motivo por el que no se puede aplicar un offset a esta línea, o None."""
    _prefix, core = strip_invisible_prefix(line)
    leading = lrc.TIMESTAMP_RE.match(core)
    if not leading:
        return None
    rest = core[leading.end():]
    tokens = list(_TIMESTAMP_PART_RE.finditer(core[:leading.end()]))
    tokens += [part for word in lrc.WORD_TIMESTAMP_RE.finditer(rest)
               for part in _TIMESTAMP_PART_RE.finditer(word.group())]
    for token in tokens:
        if int(token.group(3)) >= 60:
            return f"marca de tiempo inválida {token.group()}"
    if _INLINE_TIMESTAMP_RE.search(lrc.WORD_TIMESTAMP_RE.sub("", rest)):
        return "marcas [mm:ss] dentro del texto (estilo QQ o texto entre corchetes)"
    return None


def parse_offset(value: str) -> int | None:
    """"+500" -> 500; "-300" -> -300; "250" -> 250; "medio segundo" -> None."""
    match = _OFFSET_VALUE_RE.fullmatch(value.strip())
    if not match:
        return None
    number = int(match.group(2))
    return -number if match.group(1) == "-" else number


# --------------------------------------------------------------------------
# Cabeceras estándar
# --------------------------------------------------------------------------

def build_headers(track: Track | None) -> list[tuple[str, str]]:
    """
    Cabeceras estándar (ar, ti, al, length) a partir de las etiquetas.

    Nunca se inventan datos: si falta una etiqueta, no hay cabecera.
    """
    if track is None:
        return []
    values = {
        "ar": track.artist,
        "ti": track.title,
        "al": track.album,
        "length": _format_length(track.duration),
    }
    headers = []
    for name in STANDARD_HEADERS:
        value = values.get(name)
        if value:
            # Un salto de línea dentro de una etiqueta rompería el LRC.
            value = " ".join(str(value).split())
            headers.append((name, value))
    return headers


def header_lines(headers: list[tuple[str, str]]) -> list[str]:
    return [f"[{name}:{value}]" for name, value in headers]


def _format_length(duration: float | None) -> str | None:
    if not duration:
        return None
    total = int(round(duration))
    return f"{total // 60:02d}:{total % 60:02d}"


# --------------------------------------------------------------------------
# Transformación del texto
# --------------------------------------------------------------------------

@dataclass
class TextResult:
    text: str
    changed: bool = False
    synced: bool = False
    content_lines: int = 0
    nearly_empty: bool = False
    empty_result: bool = False
    """Al quitar las cabeceras no quedaría letra: no se escribe."""
    removed_headers: list[str] = field(default_factory=list)
    removed_unknown: list[str] = field(default_factory=list)
    unknown_headers: list[str] = field(default_factory=list)
    """Cabeceras desconocidas que se conservan ([xtrack:]...)."""
    written_headers: list[str] = field(default_factory=list)
    offsets: list[str] = field(default_factory=list)
    """Valores de todas las cabeceras [offset:], tal como aparecen."""
    offset_ms: int | None = None
    """Offset aplicado."""
    shifted: int = 0
    clamped: int = 0
    decision: str | None = None
    """Si no es None, el texto no se modificó y requiere revisión."""
    warnings: list[str] = field(default_factory=list)
    entries: list | None = None
    """SYLT: entradas (texto, tiempo) resultantes."""


def normalize_text(
    text: str,
    mode: str,
    block: list[str] | None = None,
    strip_unknown: bool = False,
    offset_policy: str = OFFSET_SKIP,
) -> TextResult:
    """
    Normaliza el texto de una letra.

    - Separa líneas solo por CRLF, CR y LF y conserva cada delimitador.
    - Quita las cabeceras conocidas (en cualquier posición) y, con
      strip_unknown, las líneas [palabra:valor] del bloque inicial.
    - Quita las líneas vacías que quedan al inicio justo después de las
      cabeceras retiradas.
    - `block`: líneas de cabecera ya formateadas que se escriben al inicio
      (solo modo standardize).
    """
    result = TextResult(text=text)
    lines = split_lines(text)
    kinds: list[str] = []
    names: list[str | None] = []
    in_initial_block = True

    for content, _eol in lines:
        _prefix, core = strip_invisible_prefix(content)
        timestamp = lrc.TIMESTAMP_RE.match(core)
        name = None
        if timestamp:
            kind = _SYNCED
            result.synced = True
            if lrc.has_text_after_timestamps(core, timestamp):
                result.content_lines += 1
        elif lrc.header_name(content):
            kind = _HEADER
            name = lrc.header_name(content)
        elif in_initial_block and lrc.header_key(content):
            kind = _UNKNOWN
            name = lrc.header_key(content)
        elif not content.strip(" \t"):
            kind = _BLANK
        else:
            kind = _TEXT
            result.content_lines += 1
        if kind in (_SYNCED, _TEXT):
            in_initial_block = False
        kinds.append(kind)
        names.append(name)

    result.nearly_empty = result.content_lines <= NEARLY_EMPTY_MAX_LINES
    if result.content_lines == 0:
        result.warnings.append("Vacía (sin líneas con texto).")
    elif result.nearly_empty:
        result.warnings.append(f"Casi vacía: solo {plural(result.content_lines, 'línea')} con texto.")

    # Offsets: solo uno válido se aplica; el resto requiere decisión.
    offset_values = [lrc.header_value(content) for (content, _eol), kind, name
                     in zip(lines, kinds, names) if kind == _HEADER and name == "offset"]
    result.offsets = offset_values
    parsed = [parse_offset(value) for value in offset_values]
    if any(value is None for value in parsed):
        invalid = ", ".join(f"[offset:{value}]" for value, number in zip(offset_values, parsed) if number is None)
        result.decision = f"offset inválido {invalid}: no se puede interpretar; corrígelo a mano."
        return result
    if len(parsed) >= 2:
        if offset_policy == OFFSET_SKIP:
            values = ", ".join(offset_values)
            result.decision = (f"{len(parsed)} cabeceras [offset:] ({values}); "
                               "elige --offset-policy first, last o sum.")
            return result
        chosen = {OFFSET_FIRST: parsed[0], OFFSET_LAST: parsed[-1], OFFSET_SUM: sum(parsed)}[offset_policy]
    else:
        chosen = parsed[0] if parsed else None

    if chosen:
        for (content, _eol), kind in zip(lines, kinds):
            if kind == _SYNCED:
                problem = _offset_problem(content)
                if problem:
                    result.decision = f"no se puede aplicar [offset:{chosen}]: {problem}."
                    return result

    # Líneas que se quitan.
    remove: set[int] = set()
    after_removed = False
    kept_in_block = False
    seen_content = False
    for index, kind in enumerate(kinds):
        if kind == _HEADER:
            remove.add(index)
            result.removed_headers.append(names[index])
            after_removed = True
        elif kind == _UNKNOWN:
            if strip_unknown:
                remove.add(index)
                result.removed_unknown.append(names[index])
                after_removed = True
            else:
                result.unknown_headers.append(names[index])
                kept_in_block = True
        elif kind == _BLANK:
            if after_removed and not kept_in_block and not seen_content:
                remove.add(index)
        else:
            kept_in_block = seen_content = True

    new_lines: list[tuple[str, str]] = []
    for index, ((content, eol), kind) in enumerate(zip(lines, kinds)):
        if index in remove:
            continue
        if kind == _SYNCED and chosen:
            content, shifted, clamped = shift_line(content, chosen)
            result.shifted += shifted
            result.clamped += clamped
        new_lines.append((content, eol))
    if chosen and result.synced:
        result.offset_ms = chosen
    if result.clamped:
        result.warnings.append(f"{plural(result.clamped, 'marca')} quedan en 00:00 por el offset.")

    if mode == MODE_STANDARDIZE and block and (result.synced or remove):
        newline = next((eol for _content, eol in lines if eol), "\n")
        result.written_headers = [lrc.header_name(line) or line for line in block]
        new_lines = [(line, newline) for line in block] + new_lines

    body = [(content, eol) for (content, eol), kind in zip(lines, kinds) if kind in (_SYNCED, _TEXT)]
    result.text = "".join(content + eol for content, eol in new_lines)
    result.changed = result.text != text
    result.empty_result = result.changed and not any(content.strip() for content, _eol in body)
    return result


def normalize_sylt(entries: list, strip_unknown: bool = False) -> TextResult:
    """
    SYLT guarda pares (texto, tiempo) sin marcas en el texto: solo se
    quitan las entradas que son cabeceras.
    """
    texts = [text for text, _time in entries]
    result = TextResult(text="\n".join(texts))
    content = [text for text in texts if text.strip() and not lrc.header_key(text)]
    result.synced = True
    result.content_lines = len(content)
    result.nearly_empty = result.content_lines <= NEARLY_EMPTY_MAX_LINES
    if not content:
        result.warnings.append("Vacía (sin líneas con texto).")
    elif result.nearly_empty:
        result.warnings.append(f"Casi vacía: solo {plural(len(content), 'línea')} con texto.")
    if any(lrc.header_name(text) == "offset" for text in texts):
        result.decision = "SYLT con [offset:]: los tiempos de SYLT no se ajustan automáticamente."
        return result
    kept = []
    in_block = True
    for text, time in entries:
        name = lrc.header_name(text)
        key = lrc.header_key(text)
        if name:
            result.removed_headers.append(name)
            continue
        if key and in_block:
            if strip_unknown:
                result.removed_unknown.append(key)
                continue
            result.unknown_headers.append(key)
        elif text.strip():
            in_block = False
        kept.append((text, time))
    result.changed = kept != list(entries)
    result.empty_result = result.changed and not content
    result.text = "\n".join(text for text, _time in kept)
    result.entries = kept
    return result


# --------------------------------------------------------------------------
# Selección (--only)
# --------------------------------------------------------------------------

class SelectionError(Exception):
    """Un valor de --only no corresponde a ninguna carpeta ni álbum."""


def select(scan: LibraryScan, only: list[str]) -> tuple[list[Track], list]:
    """
    Limita las pistas y letras huérfanas a ciertas carpetas o álbumes.

    Cada valor de `only` puede ser una carpeta (absoluta o relativa a la
    biblioteca) o el nombre de un álbum según sus etiquetas (sin
    distinguir mayúsculas).
    """
    if not only:
        return list(scan.tracks), list(scan.orphan_lyrics)

    folders: list[Path] = []
    albums: set[str] = set()
    for value in only:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = scan.root / candidate
        if candidate.is_dir():
            folders.append(candidate.resolve())
            continue
        name = value.strip().lower()
        if not any((track.album or "").lower() == name for track in scan.tracks):
            raise SelectionError(f"No se encontró una carpeta ni un álbum llamado: {value}")
        albums.add(name)

    def in_folders(path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved == folder or folder in resolved.parents for folder in folders)

    tracks = [
        track for track in scan.tracks
        if in_folders(track.filepath) or (track.album or "").lower() in albums
    ]
    orphans = [lyrics for lyrics in scan.orphan_lyrics if in_folders(Path(lyrics.location))]
    return tracks, orphans


# --------------------------------------------------------------------------
# Plan de cambios
# --------------------------------------------------------------------------

@dataclass
class LyricsChange:
    """Un cambio planeado (o descartado) sobre una copia de la letra."""
    kind: str
    """KIND_FILE o KIND_EMBEDDED."""
    path: Path
    """Archivo de letra, o archivo de audio si la letra está incrustada."""
    track: Track | None
    label: str
    """Nombre del archivo de letra, o etiqueta (LYRICS, USLT...)."""
    status: str = STATUS_UNCHANGED
    details: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    message: str | None = None
    nearly_empty: bool = False
    unknown_headers: list[str] = field(default_factory=list)

    # Archivos.
    original_bytes: bytes | None = None
    new_bytes: bytes | None = None
    original_mtime: float | None = None
    source_encoding: str | None = None
    """Codificación de origen como texto legible ("UTF-8 con BOM", "detectada Shift-JIS"...)."""

    # Incrustadas.
    slot: Slot | None = None
    original_value: object = None
    new_value: object = None
    headers: list = field(default_factory=list)
    """Cabeceras usadas por --standardize-headers (para repetir el cálculo al aplicar)."""
    file_plan: dict | None = None
    """Datos del archivo al planificar: firma, hash de la región, modo de escritura."""
    skip_reason: str | None = None
    """Motivo de omisión (clave de rawtags.REASONS) si no se puede editar."""
    new_encoding: int | None = None
    """ID3: codificación nueva del frame (convert-lyrics --id3-encoding)."""

    # Texto (para el registro y la vista previa).
    original_text: str = ""
    new_text: str = ""
    approximate: bool = False
    """La vista del texto es aproximada (codificación no confirmada)."""

    @property
    def track_path(self) -> Path | None:
        return self.track.filepath if self.track is not None else None


def _describe(result: TextResult) -> list[str]:
    details = []
    if result.written_headers:
        details.append("cabeceras " + " ".join(f"[{name}:]" for name in result.written_headers))
    removed = [name for name in dict.fromkeys(result.removed_headers)
               if name not in result.written_headers]
    if removed:
        details.append("quita " + " ".join(f"[{name}:]" for name in removed))
    if result.removed_unknown:
        details.append("quita desconocidas " + " ".join(
            f"[{name}:]" for name in dict.fromkeys(result.removed_unknown)))
    if result.shifted:
        sign = "+" if result.offset_ms > 0 else ""
        details.append(f"aplica offset {sign}{result.offset_ms} ms a {plural(result.shifted, 'marca')}")
    return details


class LyricsNormalizer:
    """Planea y aplica la normalización de letras de una biblioteca."""

    def __init__(
        self,
        mode: str,
        encoding: str = ENCODING_KEEP,
        strip_unknown: bool = False,
        offset_policy: str = OFFSET_SKIP,
        skip_near_empty: bool = False,
        allow_full_rewrite: bool = False,
    ):
        if mode not in (MODE_STRIP, MODE_STANDARDIZE):
            raise ValueError(f"Modo desconocido: {mode}")
        if offset_policy not in OFFSET_POLICIES:
            raise ValueError(f"Política de offset desconocida: {offset_policy}")
        self.mode = mode
        self.encoding = encoding
        self.target: TargetEncoding | None = parse_target_encoding(encoding)
        self.strip_unknown = strip_unknown
        self.offset_policy = offset_policy
        self.skip_near_empty = skip_near_empty
        self.allow_full_rewrite = allow_full_rewrite

    # ------------------------------------------------------------------

    def plan(self, scan: LibraryScan, tracks: list[Track] | None = None,
             orphan_lyrics: list | None = None) -> list[LyricsChange]:
        """
        Calcula los cambios sin modificar nada (todo en memoria).

        `tracks` y `orphan_lyrics` permiten limitar el plan (opción --only);
        por defecto se usa todo el escaneo. Para bibliotecas grandes, la
        ejecución recorre carpeta por carpeta con plan_tracks() (run.py).
        """
        tracks = scan.tracks if tracks is None else tracks
        orphan_lyrics = scan.orphan_lyrics if orphan_lyrics is None else orphan_lyrics
        return list(self.plan_tracks(tracks, orphan_lyrics))

    def plan_tracks(self, tracks: list[Track], orphan_lyrics: list):
        """Produce los cambios de un grupo de pistas y letras huérfanas (p. ej. una carpeta)."""
        seen_files: set[Path] = set()
        for track in tracks:
            if track.error:
                continue
            headers = build_headers(track)
            external = [Path(lyr.location) for lyr in track.lyrics if lyr.source == SOURCE_EXTERNAL]
            for path in external:
                if path in seen_files:
                    continue
                seen_files.add(path)
                yield self._plan_file(path, track, headers)
            if any(lyr.source != SOURCE_EXTERNAL for lyr in track.lyrics):
                yield from self._plan_embedded(track, headers)

        for lyrics in orphan_lyrics:
            path = Path(lyrics.location)
            if path in seen_files:
                continue
            seen_files.add(path)
            if self.mode == MODE_STANDARDIZE:
                yield LyricsChange(
                    kind=KIND_FILE, path=path, track=None, label=path.name,
                    status=STATUS_SKIPPED,
                    message="Sin canción asociada: no hay etiquetas para estandarizar.",
                )
            else:
                yield self._plan_file(path, None, [])

    def _apply_text_rules(self, change: LyricsChange, result: TextResult) -> bool:
        """
        Estado común de archivos e incrustadas a partir del resultado.

        Retorna True si el cambio puede seguir (hay algo que escribir o
        convertir); False si ya quedó decidido (decisión, omitido...).
        """
        change.warnings += result.warnings
        change.nearly_empty = result.nearly_empty
        change.unknown_headers = list(dict.fromkeys(result.unknown_headers))
        if result.decision:
            change.status = STATUS_DECISION
            change.message = result.decision
            return False
        if self.skip_near_empty and result.nearly_empty:
            change.status = STATUS_SKIPPED
            change.message = "Casi vacía: omitida por --skip-near-empty."
            return False
        if result.empty_result:
            change.status = STATUS_SKIPPED
            change.message = "Quedaría vacía al quitar las cabeceras: no se escribe."
            return False
        change.details = _describe(result)
        return True

    def _plan_file(self, path: Path, track: Track | None, headers) -> LyricsChange:
        change = LyricsChange(kind=KIND_FILE, path=path, track=track, label=path.name, headers=list(headers))
        try:
            data = path.read_bytes()
            change.original_mtime = path.stat().st_mtime
        except OSError as exc:
            change.status = STATUS_ERROR
            change.message = f"No se pudo leer: {exc.strerror or exc}"
            return change
        change.original_bytes = data

        try:
            decoded = decode_lyrics(data)
        except LyricsDecodeError as exc:
            change.status = STATUS_ERROR
            change.message = f"{exc} No se modifica."
            return change
        change.source_encoding = decoded.label
        change.original_text, change.approximate = decoded.display(decoded.text)
        change.new_text = change.original_text
        if change.approximate:
            change.warnings.append(f"Vista aproximada: {decoded.label}.")
        mojibake = [] if change.approximate else find_mojibake(change.original_text)
        if mojibake:
            sample = ", ".join(f"«{bad}» → «{good}»" for bad, good in mojibake)
            change.warnings.append(f"Posible mojibake ({sample}); no se corrige.")

        block: list[str] = []
        if self.mode == MODE_STANDARDIZE:
            block, problem = self._block_for(decoded, header_lines(headers))
            if problem:
                change.status = STATUS_SKIPPED
                change.message = problem
                return change

        result = normalize_text(decoded.text, self.mode, block, self.strip_unknown, self.offset_policy)
        if not self._apply_text_rules(change, result):
            return change

        new_view = result.text
        if self.target is None:
            new_bytes = decoded.encode(new_view)
            change.new_text = decoded.display(new_view)[0]
        else:
            real = decoded.real_text(new_view)
            if real is None:
                change.status = STATUS_SKIPPED
                change.message = (f"No se convierte: {decoded.label}. "
                                  "Indica la codificación con convert-lyrics --source-encoding.")
                change.details = []
                return change
            try:
                new_bytes = encode_text(real, self.target)
            except UnencodableError as exc:
                change.status = STATUS_SKIPPED
                change.message = f"No se convierte: {exc}."
                change.details = []
                return change
            change.new_text = real
            source = decoded.source_encoding
            if encoding_label(source) != encoding_label(self.target.codec):
                change.details.append(f"{encoding_label(source)} -> {encoding_label(self.target.codec)}")
            if decoded.bom and not self.target.bom:
                change.details.append("quita BOM")
            elif self.target.bom and not decoded.bom:
                change.details.append("agrega BOM")

        change.new_bytes = new_bytes
        change.status = STATUS_CHANGE if new_bytes != data else STATUS_UNCHANGED
        if change.status == STATUS_UNCHANGED:
            change.details = []
        return change

    @staticmethod
    def _block_for(decoded, lines: list[str]) -> tuple[list[str], str | None]:
        """
        Cabeceras nuevas en el "espacio" de texto del archivo.

        En un archivo de 8 bits cuya codificación no se confirmó, solo se
        pueden escribir cabeceras ASCII.
        """
        if decoded.exact:
            return lines, None
        block = []
        for line in lines:
            if line.isascii():
                block.append(line)
                continue
            encoding = decoded.source_encoding
            if encoding is None:
                return [], (f"No se pueden escribir cabeceras con caracteres no ASCII: {decoded.label}. "
                            "Convierte primero con convert-lyrics --source-encoding.")
            try:
                block.append(line.encode(encoding).decode(decoded.codec))
            except UnicodeEncodeError:
                return [], f"La cabecera {line} no se puede representar en {encoding_label(encoding)}."
        return block, None

    def _plan_embedded(self, track: Track, headers) -> list[LyricsChange]:
        path = track.filepath

        def single(status, message, reason=None):
            return [LyricsChange(kind=KIND_EMBEDDED, path=path, track=track, label="(incrustada)",
                                 status=status, message=message, skip_reason=reason)]
        try:
            editor = open_editor(path)
            if editor is None:
                return []
            signature = file_signature(path)
            slots = editor.slots()
        except Unsupported as exc:
            return single(STATUS_SKIPPED, str(exc), exc.reason)
        except Exception as exc:  # noqa: BLE001 - un archivo dañado no detiene el plan
            return single(STATUS_ERROR, f"No se pudo leer: {exc}")

        changes = []
        for slot, label in zip(slots, distinct_labels(slots)):
            change = LyricsChange(kind=KIND_EMBEDDED, path=path, track=track,
                                  label=label, slot=slot, original_value=slot.value)
            if slot.is_sylt:
                self._plan_sylt(change, slot)
            else:
                self._plan_text_slot(change, slot, headers)
            changes.append(change)
        self._plan_file_edit(editor, signature, [c for c in changes if c.status == STATUS_CHANGE])
        return changes

    def _plan_file_edit(self, editor, signature, changed: list[LyricsChange]) -> None:
        plan_file_edit(editor, signature, changed, self.allow_full_rewrite)

    def _plan_text_slot(self, change: LyricsChange, slot: Slot, headers) -> None:
        text = slot.value or ""
        change.original_text = change.new_text = text
        block = header_lines(headers) if self.mode == MODE_STANDARDIZE else []
        result = normalize_text(text, self.mode, block, self.strip_unknown, self.offset_policy)
        if not self._apply_text_rules(change, result):
            return
        change.new_text = result.text
        change.new_value = result.text
        change.status = STATUS_CHANGE if result.changed else STATUS_UNCHANGED
        if not result.changed:
            change.details = []

    def _plan_sylt(self, change: LyricsChange, slot: Slot) -> None:
        entries = list(slot.value)
        change.original_text = change.new_text = "\n".join(text for text, _time in entries)
        result = normalize_sylt(entries, self.strip_unknown)
        if not self._apply_text_rules(change, result):
            return
        change.new_value = result.entries
        change.new_text = result.text
        change.status = STATUS_CHANGE if result.changed else STATUS_UNCHANGED
        if not result.changed:
            change.details = []

    # ------------------------------------------------------------------

    def options(self) -> dict:
        """Opciones de la ejecución (se guardan en estado.json para --resume)."""
        return {"mode": self.mode, "encoding": self.encoding, "strip_unknown_headers": self.strip_unknown,
                "offset_policy": self.offset_policy, "skip_near_empty": self.skip_near_empty,
                "allow_full_rewrite": self.allow_full_rewrite}

    @classmethod
    def from_options(cls, options: dict) -> "LyricsNormalizer":
        return cls(options["mode"], options["encoding"], options["strip_unknown_headers"],
                   options["offset_policy"], options["skip_near_empty"], options["allow_full_rewrite"])

    def plan_one_file(self, path: Path, headers) -> LyricsChange:
        """Recalcula el cambio de un archivo de letra (al aplicar un plan guardado)."""
        return self._plan_file(Path(path), None, [tuple(pair) for pair in headers])

    def apply(self, changes: list[LyricsChange], root: Path, verify: str = "auto"):
        """
        Aplica los cambios planeados (status == STATUS_CHANGE) creando una
        ejecución en disco (run.py): plan, diario y respaldo. Retorna la
        ejecución, o None si no había nada que cambiar.
        """
        from choconostle import run as runs
        pending = pending_sessions(root)
        if pending:
            raise PendingWritesError(pending)
        if not any(change.status == STATUS_CHANGE for change in changes):
            return None
        execution = runs.Run.create(root, "normalize-lyrics", dict(self.options(), verify=verify))
        runs.plan_from_changes(execution, changes, root)
        runs.apply_run(execution, self, root, verify=verify)
        return execution


def plan_file_edit(editor, signature, changed: list[LyricsChange], allow_full_rewrite: bool) -> None:
    """
    Comprueba que la edición byte a byte de las letras `changed` de un
    archivo es posible y segura, y cómo se escribirá (en su sitio, al
    final o reescritura completa). Si no se puede, marca las letras como
    omitidas con el motivo. Compartida por normalize-lyrics y convert-lyrics.
    """
    if not changed:
        return

    def skip(reason, message):
        for change in changed:
            change.status = STATUS_SKIPPED
            change.skip_reason = reason
            change.message = message
            change.details = []

    values = {(c.slot.key, c.slot.index): c.new_value for c in changed}
    encodings = {c.slot.key: c.new_encoding for c in changed if c.new_encoding is not None}
    try:
        edit = editor.build(values, encodings)
        if not isinstance(editor, OggEditor):
            problems = editor.verify(apply_patches(editor.region, edit.patches), edit.expected, edit.encodings)
            if problems:
                raise Unsupported("id3_frame_format", "la edición no sería segura: " + "; ".join(problems))
    except Unsupported as exc:
        skip(exc.reason, str(exc))
        return
    note = edit.note
    if edit.mode == MODE_FULL:
        size_after = signature[0] + edit.new_len - edit.old_len
        note = (f"reescritura completa, requiere {format_size(required_space(size_after))} libres"
                + (f" ({edit.note})" if edit.note else ""))
        if not allow_full_rewrite:
            skip("full_rewrite", f"{note}. Usa --allow-full-rewrite para aplicarla.")
            return
    plan = {"signature": list(signature), "mode": edit.mode,
            "region_sha": None if isinstance(editor, OggEditor) else sha256(editor.region)}
    for change in changed:
        change.file_plan = plan
        if note:
            change.details.append(note)


def distinct_labels(slots: list[Slot]) -> list[str]:
    """
    Etiquetas para mostrar, distintas entre sí aunque el archivo tenga
    varias letras del mismo tipo: "USLT [eng]" y "USLT [spa]", "LYRICS #1"
    y "LYRICS #2", "TXXX:LYRICS #1" y "#2" (valores de un mismo TXXX).
    """
    counts: dict[str, int] = {}
    for slot in slots:
        counts[slot.label] = counts.get(slot.label, 0) + 1
    labels = []
    for slot in slots:
        label = slot.label
        identity = slot.key.split("#")[0].split(":")
        if counts[label] > 1 and slot.tag_format == "id3" and label in ("USLT", "SYLT") and len(identity) >= 3:
            lang, desc = identity[1], ":".join(identity[2:])
            label = f"{label} [{lang}{': ' + desc if desc else ''}]"
        labels.append(label)
    totals: dict[str, int] = {}
    for label in labels:
        totals[label] = totals.get(label, 0) + 1
    seen: dict[str, int] = {}
    result = []
    for label in labels:
        if totals[label] > 1:
            seen[label] = seen.get(label, 0) + 1
            result.append(f"{label} #{seen[label]}")
        else:
            result.append(label)
    return result


class PendingWritesError(Exception):
    """Hay escrituras interrumpidas sin resolver en alguna carpeta de respaldo."""

    def __init__(self, folders: list[Path]):
        self.folders = folders
        names = ", ".join(str(folder) for folder in folders)
        super().__init__(f"Hay escrituras interrumpidas sin resolver en: {names}. "
                         "Ejecuta primero choconostle recover <carpeta> (o revert).")


def pending_sessions(root: Path) -> list[Path]:
    """Carpetas de respaldo con escrituras interrumpidas (diario no vacío)."""
    from choconostle.config import BACKUP_DIR_NAME
    base = Path(root) / BACKUP_DIR_NAME
    if not base.is_dir():
        return []
    return [folder for folder in sorted(base.iterdir())
            if folder.is_dir() and Journal(folder).pending()]


def skip_reason_label(reason: str | None) -> str:
    return REASONS.get(reason, reason or "otro motivo")
