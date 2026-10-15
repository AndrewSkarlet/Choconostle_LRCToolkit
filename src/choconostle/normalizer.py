"""
normalizer.py

Fase 2: normalización de letras (comando normalize-lyrics).

Dos modos:
- strip: quita las cabeceras LRC ([ar:], [ti:], [by:], [offset:]...).
  Si hay [offset:], lo aplica a cada marca de tiempo antes de quitarlo.
- standardize: deja solo un conjunto fijo de cabeceras (ar, ti, al,
  length) con datos tomados de las etiquetas de la canción. Si falta un
  dato, esa cabecera no se escribe.

Se aplica a todas las copias de la letra: archivo .lrc/.txt y etiquetas
incrustadas. Las letras casi vacías se marcan y no se modifican.

Responsabilidades:
- Transformar el texto de una letra (normalize_text).
- Codificar los archivos de letra (encode_lyrics_file).
- Planear los cambios de una biblioteca y aplicarlos con respaldo
  (LyricsNormalizer).

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import codecs
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from choconostle import lrc
from choconostle.backup import ITEM_APPLIED, ITEM_FAILED, BackupSession
from choconostle.config import NEARLY_EMPTY_MAX_LINES, STANDARD_HEADERS
from choconostle.embedded import EmbeddedError, EmbeddedLyrics, Slot
from choconostle.models.lyrics import SOURCE_EXTERNAL
from choconostle.models.track import Track
from choconostle.scanner import LibraryScan
from choconostle.utils import plural, write_file_atomic

MODE_STRIP = "strip"
MODE_STANDARDIZE = "standardize"

ENCODING_UTF8 = "utf8"
ENCODING_UTF8_BOM = "utf8-bom"
ENCODING_KEEP = "keep"

KIND_FILE = "file"
KIND_EMBEDDED = "embedded"

STATUS_CHANGE = "change"
STATUS_UNCHANGED = "unchanged"
STATUS_NEARLY_EMPTY = "nearly_empty"
STATUS_SKIPPED = "skipped"
STATUS_ERROR = "error"

_BOM_BY_ENCODING = {
    "utf-8": codecs.BOM_UTF8,
    "utf-16-le": codecs.BOM_UTF16_LE,
    "utf-16-be": codecs.BOM_UTF16_BE,
    "utf-32-le": codecs.BOM_UTF32_LE,
    "utf-32-be": codecs.BOM_UTF32_BE,
}

# Codificaciones adivinadas (sin BOM ni UTF válido): no hay certeza de que
# la detección sea correcta.
_GUESSED_ENCODINGS = {"cp1252", "latin-1"}

# Signos no ASCII habituales en letras en español, portugués, francés...
_LATIN_PUNCTUATION = set("¡¿«»°ºª·–—‘’“”…€´¨")

_TIMESTAMP_PART_RE = re.compile(r"([\[<])(\d{1,3}):(\d{1,2})(?:([.:,])(\d{1,3}))?([\]>])")


# --------------------------------------------------------------------------
# Transformación del texto
# --------------------------------------------------------------------------

@dataclass
class TextResult:
    text: str
    synced: bool = False
    nearly_empty: bool = False
    content_lines: int = 0
    removed_headers: list[str] = field(default_factory=list)
    written_headers: list[str] = field(default_factory=list)
    offset_ms: int | None = None
    shifted: int = 0
    clamped: int = 0
    removed_bom: bool = False
    newline: str = "LF"
    """Saltos de línea originales: "LF", "CRLF" o "CR"."""
    warnings: list[str] = field(default_factory=list)


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
    en 0.

    Retorna (línea, marcas_modificadas, marcas_recortadas_a_cero).
    """
    leading = lrc.TIMESTAMP_RE.match(line)
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

    # Marcas al inicio [mm:ss.xx] y marcas por palabra <mm:ss.xx> del resto.
    head = _TIMESTAMP_PART_RE.sub(replace, line[:leading.end()])
    tail = re.sub(lrc.WORD_TIMESTAMP_RE.pattern,
                  lambda m: _TIMESTAMP_PART_RE.sub(replace, m.group(0)),
                  line[leading.end():])
    return head + tail, shifted, clamped


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


def _format_length(duration: float | None) -> str | None:
    if not duration:
        return None
    total = int(round(duration))
    return f"{total // 60:02d}:{total % 60:02d}"


def normalize_text(text: str, mode: str, headers: list[tuple[str, str]]) -> TextResult:
    """
    Normaliza el texto de una letra.

    - Las letras casi vacías no se modifican (nearly_empty=True).
    - Las letras sin marcas de tiempo solo cambian si tienen cabeceras.
    - Los saltos de línea se convierten a LF.
    """
    result = TextResult(text=text)
    if text.startswith("﻿"):
        text = text[1:]
        result.removed_bom = True
    if "\r\n" in text:
        result.newline = "CRLF"
    elif "\r" in text:
        result.newline = "CR"
    trailing_newline = text.endswith(("\n", "\r"))

    lines = text.splitlines()
    header_lines: dict[int, str] = {}
    for index, line in enumerate(lines):
        timestamp = lrc.TIMESTAMP_RE.match(line)
        if timestamp:
            result.synced = True
            if lrc.has_text_after_timestamps(line, timestamp):
                result.content_lines += 1
            continue
        name = lrc.header_name(line)
        if name:
            header_lines[index] = name
            if name == "offset":
                value = lrc.header_value(line)
                try:
                    result.offset_ms = int(value.replace(" ", ""))
                except ValueError:
                    result.warnings.append(f"[offset:{value}] no es un número; no se aplicó.")
            continue
        if line.strip():
            result.content_lines += 1

    if result.content_lines <= NEARLY_EMPTY_MAX_LINES:
        result.nearly_empty = True
        result.text = text if not result.removed_bom else "﻿" + text
        result.removed_bom = False
        return result

    rewrite = bool(header_lines) or (mode == MODE_STANDARDIZE and result.synced)
    if rewrite:
        body = [line for index, line in enumerate(lines) if index not in header_lines]
        if result.offset_ms and result.synced:
            shifted_body = []
            for line in body:
                line, shifted, clamped = shift_line(line, result.offset_ms)
                result.shifted += shifted
                result.clamped += clamped
                shifted_body.append(line)
            body = shifted_body
        while body and not body[0].strip():
            body.pop(0)
        result.removed_headers = [header_lines[index] for index in sorted(header_lines)]
        if mode == MODE_STANDARDIZE:
            block = [f"[{name}:{value}]" for name, value in headers]
            result.written_headers = [name for name, _value in headers]
            body = block + body
        lines = body

    new_text = "\n".join(lines)
    if trailing_newline and new_text:
        new_text += "\n"
    result.text = new_text
    return result


# --------------------------------------------------------------------------
# Codificación de archivos
# --------------------------------------------------------------------------

class LyricsEncodingError(Exception):
    """El texto no se puede guardar en la codificación pedida."""


def looks_like_latin_text(text: str) -> bool:
    """
    True si un texto decodificado como Windows-1252/Latin-1 parece texto
    real en un idioma latino (y no un archivo en otra codificación, como
    Shift-JIS o GBK, leído mal).
    """
    run = 0
    for char in text:
        if ord(char) < 128:
            run = 0
            continue
        run += 1
        if run >= 3:
            return False
        if char in _LATIN_PUNCTUATION:
            continue
        if not unicodedata.category(char).startswith("L"):
            return False
        if not ("À" <= char <= "ſ"):
            return False
    return True


def encode_lyrics_file(
    text: str,
    option: str,
    original_encoding: str,
    original_bom: bool,
) -> tuple[bytes, str, bool, list[str]]:
    """
    Codifica el texto de un archivo de letra.

    Retorna (bytes, codificación_final, con_bom, avisos).
    """
    warnings: list[str] = []
    keep = option == ENCODING_KEEP
    if not keep and original_encoding in _GUESSED_ENCODINGS and not looks_like_latin_text(text):
        warnings.append(
            "La codificación no es UTF-8 y no se pudo confirmar cuál es; "
            "se conserva la original para no dañar el texto."
        )
        keep = True

    if keep:
        encoding = "utf-8" if original_encoding == "ascii" else original_encoding
        bom = _BOM_BY_ENCODING.get(encoding, b"") if original_bom else b""
        try:
            data = text.encode(encoding)
        except UnicodeEncodeError as exc:
            raise LyricsEncodingError(
                f"El texto nuevo no cabe en {encoding} ({exc.object[exc.start:exc.end]!r}); "
                "usa --encoding utf8."
            ) from exc
        return bom + data, encoding, bool(bom), warnings

    data = text.encode("utf-8")
    if option == ENCODING_UTF8_BOM:
        return codecs.BOM_UTF8 + data, "utf-8", True, warnings
    return data, "utf-8", False, warnings


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
    message: str | None = None

    # Archivos.
    original_bytes: bytes | None = None
    new_bytes: bytes | None = None
    original_mtime: float | None = None

    # Incrustadas.
    slot: Slot | None = None
    original_value: object = None
    new_value: object = None
    new_id3_encoding: int | None = None

    # Texto (para el registro y la vista previa).
    original_text: str = ""
    new_text: str = ""

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
    if result.shifted:
        sign = "+" if result.offset_ms > 0 else ""
        text = f"aplica offset {sign}{result.offset_ms} ms a {result.shifted} marcas"
        if result.clamped:
            text += f" ({result.clamped} quedan en 00:00)"
        details.append(text)
    if result.removed_bom:
        details.append("quita BOM")
    if result.newline != "LF":
        details.append(f"saltos de línea {result.newline} -> LF")
    return details


_ENCODING_NAMES = {
    "utf-8": "UTF-8", "ascii": "UTF-8", "utf-16-le": "UTF-16 LE", "utf-16-be": "UTF-16 BE",
    "utf-32-le": "UTF-32 LE", "utf-32-be": "UTF-32 BE", "cp1252": "Windows-1252", "latin-1": "Latin-1",
}


class LyricsNormalizer:
    """Planea y aplica la normalización de letras de una biblioteca."""

    def __init__(self, mode: str, encoding: str = ENCODING_UTF8):
        if mode not in (MODE_STRIP, MODE_STANDARDIZE):
            raise ValueError(f"Modo desconocido: {mode}")
        if encoding not in (ENCODING_UTF8, ENCODING_UTF8_BOM, ENCODING_KEEP):
            raise ValueError(f"Codificación desconocida: {encoding}")
        self.mode = mode
        self.encoding = encoding

    # ------------------------------------------------------------------

    def plan(self, scan: LibraryScan, tracks: list[Track] | None = None,
             orphan_lyrics: list | None = None) -> list[LyricsChange]:
        """
        Calcula los cambios sin modificar nada.

        `tracks` y `orphan_lyrics` permiten limitar el plan (opción --only);
        por defecto se usa todo el escaneo.
        """
        tracks = scan.tracks if tracks is None else tracks
        orphan_lyrics = scan.orphan_lyrics if orphan_lyrics is None else orphan_lyrics
        changes: list[LyricsChange] = []
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
                changes.append(self._plan_file(path, track, headers))
            if any(lyr.source != SOURCE_EXTERNAL for lyr in track.lyrics):
                changes.extend(self._plan_embedded(track, headers))

        for lyrics in orphan_lyrics:
            path = Path(lyrics.location)
            if path in seen_files:
                continue
            seen_files.add(path)
            if self.mode == MODE_STANDARDIZE:
                changes.append(LyricsChange(
                    kind=KIND_FILE, path=path, track=None, label=path.name,
                    status=STATUS_SKIPPED,
                    message="Sin canción asociada: no hay etiquetas para estandarizar.",
                ))
            else:
                changes.append(self._plan_file(path, None, []))
        return changes

    def _plan_file(self, path: Path, track: Track | None, headers) -> LyricsChange:
        change = LyricsChange(kind=KIND_FILE, path=path, track=track, label=path.name)
        try:
            data = path.read_bytes()
            change.original_mtime = path.stat().st_mtime
        except OSError as exc:
            change.status = STATUS_ERROR
            change.message = f"No se pudo leer: {exc.strerror or exc}"
            return change
        change.original_bytes = data

        text, encoding, has_bom = lrc.decode_bytes(data)
        # Solo se modifica un archivo si se puede volver a codificar igual:
        # garantiza que no hubo bytes inválidos que se perderían.
        check_encoding = "utf-8" if encoding == "ascii" else encoding
        check_bom = _BOM_BY_ENCODING.get(check_encoding, b"") if has_bom else b""
        try:
            roundtrip = check_bom + text.encode(check_encoding)
        except UnicodeEncodeError:
            roundtrip = None
        if roundtrip != data:
            change.status = STATUS_ERROR
            change.message = f"El archivo tiene bytes inválidos para {check_encoding}; no se modifica."
            return change

        result = normalize_text(text, self.mode, headers)
        change.original_text = text
        if result.nearly_empty:
            change.status = STATUS_NEARLY_EMPTY
            change.message = _nearly_empty_message(result)
            return change

        new_text = result.text
        if new_text and not new_text.endswith("\n"):
            new_text += "\n"
        try:
            new_bytes, new_encoding, new_bom, warnings = encode_lyrics_file(
                new_text, self.encoding, encoding, has_bom)
        except LyricsEncodingError as exc:
            change.status = STATUS_ERROR
            change.message = str(exc)
            return change

        change.details = _describe(result)
        # El BOM y la codificación de un archivo los decide --encoding.
        change.details = [detail for detail in change.details if detail != "quita BOM"]
        if has_bom and not new_bom:
            change.details.append("quita BOM")
        elif new_bom and not has_bom:
            change.details.append("agrega BOM")
        if _ENCODING_NAMES.get(encoding, encoding) != _ENCODING_NAMES.get(new_encoding, new_encoding):
            change.details.append(
                f"{_ENCODING_NAMES.get(encoding, encoding)} -> {_ENCODING_NAMES.get(new_encoding, new_encoding)}")
        if text.strip() and not text.endswith(("\n", "\r")):
            change.details.append("agrega salto de línea final")
        change.details += result.warnings + warnings

        change.new_text = new_text
        change.new_bytes = new_bytes
        change.status = STATUS_CHANGE if new_bytes != data else STATUS_UNCHANGED
        if change.status == STATUS_UNCHANGED:
            change.details = result.warnings + warnings
        return change

    def _plan_embedded(self, track: Track, headers) -> list[LyricsChange]:
        try:
            audio = EmbeddedLyrics(track.filepath)
            slots = audio.slots()
        except EmbeddedError as exc:
            return [LyricsChange(kind=KIND_EMBEDDED, path=track.filepath, track=track,
                                 label="(incrustada)", status=STATUS_SKIPPED, message=str(exc))]
        except Exception as exc:  # noqa: BLE001 - un archivo dañado no detiene el plan
            return [LyricsChange(kind=KIND_EMBEDDED, path=track.filepath, track=track,
                                 label="(incrustada)", status=STATUS_ERROR,
                                 message=f"No se pudo leer: {exc}")]

        changes = []
        for slot in slots:
            change = LyricsChange(kind=KIND_EMBEDDED, path=track.filepath, track=track,
                                  label=slot.label, slot=slot, original_value=slot.value)
            if slot.is_sylt:
                self._plan_sylt(change, slot)
            else:
                self._plan_text_slot(change, slot, headers)
            changes.append(change)
        return changes

    def _plan_text_slot(self, change: LyricsChange, slot: Slot, headers) -> None:
        text = slot.value or ""
        result = normalize_text(text, self.mode, headers)
        change.original_text = text
        if result.nearly_empty:
            change.status = STATUS_NEARLY_EMPTY
            change.message = _nearly_empty_message(result)
            return
        change.new_text = result.text
        change.new_value = result.text
        change.details = _describe(result) + result.warnings
        change.status = STATUS_CHANGE if result.text != text else STATUS_UNCHANGED

    def _plan_sylt(self, change: LyricsChange, slot: Slot) -> None:
        """SYLT guarda (texto, tiempo); solo se quitan entradas que sean cabeceras y BOM."""
        entries = list(slot.value)
        change.original_text = "\n".join(text for text, _time in entries)
        content = [text for text, _time in entries if text.strip() and not lrc.header_name(text)]
        if len(content) <= NEARLY_EMPTY_MAX_LINES:
            change.status = STATUS_NEARLY_EMPTY
            change.message = (f"Casi vacía: solo {plural(len(content), 'línea')} con texto."
                              if content else "Vacía (sin líneas con texto).")
            return
        new_entries = []
        removed = []
        removed_bom = False
        for text, time in entries:
            name = lrc.header_name(text)
            if name:
                removed.append(name)
                continue
            if text.startswith("﻿"):
                text = text[1:]
                removed_bom = True
            new_entries.append((text, time))
        if removed:
            change.details.append("quita " + " ".join(f"[{name}:]" for name in dict.fromkeys(removed)))
        if removed_bom:
            change.details.append("quita BOM")
        change.new_value = new_entries
        change.new_text = "\n".join(text for text, _time in new_entries)
        change.status = STATUS_CHANGE if new_entries != entries else STATUS_UNCHANGED


    # ------------------------------------------------------------------

    def apply(self, changes: list[LyricsChange], root: Path) -> BackupSession | None:
        """
        Aplica los cambios planeados (status == STATUS_CHANGE).

        Antes de tocar nada guarda los originales y el manifiesto en la
        carpeta de respaldo. Retorna la sesión de respaldo, o None si no
        había nada que cambiar.
        """
        selected = [change for change in changes if change.status == STATUS_CHANGE]
        if not selected:
            return None

        session = BackupSession(root, self.mode, self.encoding)
        items = [session.add(change) for change in selected]
        session.save_manifest()

        embedded: dict[Path, list[tuple[LyricsChange, dict]]] = {}
        for change, item in zip(selected, items):
            if change.kind == KIND_FILE:
                self._apply_file(change, item)
            else:
                embedded.setdefault(change.path, []).append((change, item))

        for path, pairs in embedded.items():
            self._apply_embedded(path, pairs)

        session.save_manifest()
        session.write_log()
        return session

    @staticmethod
    def _apply_file(change: LyricsChange, item: dict) -> None:
        try:
            if change.path.read_bytes() != change.original_bytes:
                raise RuntimeError("el archivo cambió desde que se planearon los cambios")
            write_file_atomic(change.path, change.new_bytes)
        except (OSError, RuntimeError) as exc:
            item["status"] = ITEM_FAILED
            item["error"] = str(exc)
            return
        item["status"] = ITEM_APPLIED

    @staticmethod
    def _apply_embedded(path: Path, pairs: list[tuple[LyricsChange, dict]]) -> None:
        def fail(targets, message):
            for _change, item in targets:
                item["status"] = ITEM_FAILED
                item["error"] = message

        try:
            audio = EmbeddedLyrics(path)
        except Exception as exc:  # noqa: BLE001
            fail(pairs, f"no se pudo abrir: {exc}")
            return

        ready = []
        for change, item in pairs:
            ref = change.slot.ref()
            current = audio.get(ref)
            if current is None or current.value != change.original_value:
                fail([(change, item)], "la etiqueta cambió desde que se planearon los cambios")
                continue
            try:
                audio.set(ref, change.new_value)
            except Exception as exc:  # noqa: BLE001
                fail([(change, item)], f"no se pudo modificar: {exc}")
                continue
            ready.append((change, item))

        if not ready:
            return
        try:
            audio.save()
        except Exception as exc:  # noqa: BLE001
            fail(ready, f"no se pudo guardar: {exc}")
            return
        for _change, item in ready:
            item["status"] = ITEM_APPLIED


def _nearly_empty_message(result: TextResult) -> str:
    if result.content_lines == 0:
        return "Vacía (sin líneas con texto)."
    return f"Casi vacía: solo {plural(result.content_lines, 'línea')} con texto."
