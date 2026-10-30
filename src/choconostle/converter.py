"""
converter.py

Conversión explícita de letras (comando convert-lyrics).

- Archivos .lrc/.txt: codificación de destino (--to, por defecto UTF-8
  sin BOM), saltos de línea (--eol, por defecto LF) y sustituciones de
  caracteres (--replace-char / --replace-map).
- Letras incrustadas: solo cambian con --replace-char/--replace-map (el
  texto) o --id3-encoding (la codificación de los frames de letra ID3).
  --to y --eol nunca las tocan.

Reglas de seguridad:
- La codificación de origen tiene que ser segura: BOM, UTF-8 válido o
  UTF-16, una detección fiable de charset-normalizer, un empate resuelto
  con --prefer-encoding, o --source-encoding para archivos de 8 bits. Si
  no, el archivo se omite.
- Nunca se sustituyen caracteres por "?": si el destino no puede
  representar alguno, el archivo se omite (--on-unencodable skip) o se
  detiene todo antes de aplicar (error).
- Las sustituciones nunca tocan las marcas de tiempo.
- No se repara el mojibake: solo se avisa.

Usa el mismo sistema de ejecución que normalize-lyrics (run.py): plan en
disco, diario, respaldo, --resume y revert.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

from pathlib import Path

from choconostle.embedded import Slot, open_editor
from choconostle.models.lyrics import SOURCE_EXTERNAL
from choconostle.models.track import Track
from choconostle.normalizer import (
    KIND_EMBEDDED, KIND_FILE, STATUS_CHANGE, STATUS_ERROR, STATUS_SKIPPED, STATUS_UNCHANGED, LyricsChange,
    distinct_labels, plan_file_edit,
)
from choconostle.rawtags import Unsupported
from choconostle.rawtags.writer import file_signature
from choconostle.textio import (
    EOL_KEEP, EOL_LF, LyricsDecodeError, UnencodableError, apply_replacements, convert_eol, decode_lyrics,
    describe_rule, encode_text, encoding_label, eol_summary, find_mojibake, parse_target_encoding,
)

COMMAND = "convert-lyrics"
ON_UNENCODABLE_SKIP = "skip"
ON_UNENCODABLE_ERROR = "error"

ID3_ENCODINGS = {"latin1": 0, "utf16": 1, "utf8": 3}
ID3_ENCODING_NAMES = {0: "Latin-1", 1: "UTF-16", 2: "UTF-16 BE", 3: "UTF-8"}


WIDE_UNICODE_WARNING = ("Destino UTF-16/UTF-32: casi ningún reproductor lee letras .lrc/.txt en esa "
                        "codificación; se recomienda UTF-8.")


def wide_unicode(codec: str) -> bool:
    """True para UTF-16 y UTF-32 (cualquier orden de bytes)."""
    return codec.replace("_", "-").lower().startswith(("utf-16", "utf-32"))


class ConversionAbort(Exception):
    """--on-unencodable error: un archivo no se puede convertir; no se aplica nada."""


class LyricsConverter:
    """Planea la conversión de letras; run.py la aplica con respaldo."""

    command = COMMAND

    def __init__(
        self,
        to: str = "utf8",
        eol: str = EOL_LF,
        source_encoding: str | None = None,
        prefer_encoding: str | None = None,
        replacements: list | None = None,
        id3_encoding: str | None = None,
        on_unencodable: str = ON_UNENCODABLE_SKIP,
        allow_full_rewrite: bool = False,
    ):
        self.to = to
        self.target = parse_target_encoding(to)
        if self.target is None:
            raise ValueError("--to keep no tiene sentido en convert-lyrics: indica una codificación.")
        self.eol = eol
        self.source_encoding = source_encoding
        self.prefer_encoding = prefer_encoding
        self.replacements = [tuple(rule) for rule in (replacements or [])]
        if id3_encoding is not None and id3_encoding not in ID3_ENCODINGS:
            raise ValueError(f"--id3-encoding desconocida: {id3_encoding}")
        self.id3_encoding = id3_encoding
        self.on_unencodable = on_unencodable
        self.allow_full_rewrite = allow_full_rewrite

    # -- opciones (estado.json, --resume) ---------------------------------

    def options(self) -> dict:
        return {"to": self.to, "eol": self.eol, "source_encoding": self.source_encoding,
                "prefer_encoding": self.prefer_encoding, "replacements": [list(r) for r in self.replacements],
                "id3_encoding": self.id3_encoding, "on_unencodable": self.on_unencodable,
                "allow_full_rewrite": self.allow_full_rewrite}

    @classmethod
    def from_options(cls, options: dict) -> "LyricsConverter":
        return cls(options["to"], options["eol"], options["source_encoding"], options["prefer_encoding"],
                   options["replacements"], options["id3_encoding"], options["on_unencodable"],
                   options["allow_full_rewrite"])

    @property
    def touches_embedded(self) -> bool:
        return bool(self.replacements) or self.id3_encoding is not None

    # -- plan -----------------------------------------------------------------

    def plan_tracks(self, tracks: list[Track], orphan_lyrics: list):
        seen: set[Path] = set()
        for track in tracks:
            if track.error:
                continue
            for lyrics in track.lyrics:
                if lyrics.source != SOURCE_EXTERNAL:
                    continue
                path = Path(lyrics.location)
                if path not in seen:
                    seen.add(path)
                    yield self._plan_file(path, track)
            if self.touches_embedded and any(lyr.source != SOURCE_EXTERNAL for lyr in track.lyrics):
                yield from self._plan_embedded(track)
        for lyrics in orphan_lyrics:
            path = Path(lyrics.location)
            if path not in seen:
                seen.add(path)
                yield self._plan_file(path, None)

    def plan_one_file(self, path: Path, _headers=None) -> LyricsChange:
        return self._plan_file(Path(path), None)

    # -- archivos -----------------------------------------------------------

    def _source_text(self, data: bytes, change: LyricsChange) -> str | None:
        """Texto real del archivo, o None (y el cambio queda omitido) si el origen no es seguro."""
        decoded = decode_lyrics(data, self.prefer_encoding)
        if decoded.exact:
            change.source_encoding = f"{decoded.label} (fiable)"
            return decoded.text
        detection = decoded.detection
        if self.source_encoding:
            try:
                text = data.decode(self.source_encoding)
            except (UnicodeDecodeError, LookupError):
                change.status = STATUS_SKIPPED
                change.message = f"El archivo no es {encoding_label(self.source_encoding)} válido (--source-encoding)."
                return None
            if text.encode(self.source_encoding) != data:
                change.status = STATUS_SKIPPED
                change.message = f"{encoding_label(self.source_encoding)} no reproduce los bytes del archivo."
                return None
            change.source_encoding = (f"{encoding_label(self.source_encoding)} (indicada con --source-encoding; "
                                      f"detección: {decoded.label})")
            return text
        if detection is not None and detection.confident:
            change.source_encoding = decoded.label if detection.tie_broken else f"{decoded.label} (fiable)"
            return data.decode(detection.encoding)
        change.status = STATUS_SKIPPED
        hint = "--source-encoding" + (" o --prefer-encoding" if detection and detection.candidates else "")
        change.message = f"Codificación de origen no fiable ({decoded.label}): no se convierte. Usa {hint}."
        change.source_encoding = f"{decoded.label} (no fiable)"
        return None

    def _plan_file(self, path: Path, track: Track | None) -> LyricsChange:
        change = LyricsChange(kind=KIND_FILE, path=path, track=track, label=path.name)
        try:
            data = path.read_bytes()
            change.original_mtime = path.stat().st_mtime
        except OSError as exc:
            change.status = STATUS_ERROR
            change.message = f"No se pudo leer: {exc.strerror or exc}"
            return change
        change.original_bytes = data
        try:
            text = self._source_text(data, change)
        except LyricsDecodeError as exc:
            change.status = STATUS_ERROR
            change.message = f"{exc} No se modifica."
            return change
        if text is None:
            return change
        change.original_text = change.new_text = text
        mojibake = find_mojibake(text)
        if mojibake:
            sample = ", ".join(f"«{bad}» → «{good}»" for bad, good in mojibake)
            change.warnings.append(f"Posible mojibake ({sample}); no se corrige.")

        new_text, counts = apply_replacements(text, self.replacements)
        new_text = convert_eol(new_text, self.eol)
        try:
            new_bytes = encode_text(new_text, self.target)
        except UnencodableError as exc:
            if self.on_unencodable == ON_UNENCODABLE_ERROR:
                raise ConversionAbort(f"{path}: {exc}") from exc
            change.status = STATUS_SKIPPED
            change.message = f"No se convierte: {exc}."
            return change

        change.new_text = new_text
        change.new_bytes = new_bytes
        if wide_unicode(self.target.codec):
            change.warnings.append(WIDE_UNICODE_WARNING)
        change.details = self._file_details(data, text, new_text, counts)
        change.status = STATUS_CHANGE if new_bytes != data else STATUS_UNCHANGED
        if change.status == STATUS_UNCHANGED:
            change.details = []
        return change

    def _file_details(self, data: bytes, text: str, new_text: str, counts: list[int]) -> list[str]:
        details = []
        decoded = decode_lyrics(data, self.prefer_encoding)
        source = (decoded.codec if decoded.exact else (self.source_encoding or
                  (decoded.detection.encoding if decoded.detection else None)))
        source_label = encoding_label("ascii" if decoded.exact and decoded.codec == "utf-8" and text.isascii()
                                      else source)
        if encoding_label(source) != encoding_label(self.target.codec):
            details.append(f"{source_label} -> {self.target.label}")
        if decoded.bom and not self.target.bom:
            details.append("quita BOM")
        elif self.target.bom and not decoded.bom:
            details.append("agrega BOM")
        if self.eol != EOL_KEEP:
            before, after = eol_summary(text), eol_summary(new_text)
            if before != after and before != "-":
                details.append(f"saltos de línea {before} -> {after}")
        details += [f"{describe_rule(rule)} ×{count}" for rule, count in zip(self.replacements, counts) if count]
        return details

    # -- letras incrustadas -------------------------------------------------

    def _plan_embedded(self, track: Track) -> list[LyricsChange]:
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
        version = getattr(getattr(editor, "layout", None), "version", None)
        for slot, label in zip(slots, distinct_labels(slots)):
            change = LyricsChange(kind=KIND_EMBEDDED, path=path, track=track, label=label, slot=slot,
                                  original_value=slot.value)
            self._plan_slot(change, slot, version)
            changes.append(change)
        plan_file_edit(editor, signature, [c for c in changes if c.status == STATUS_CHANGE],
                       self.allow_full_rewrite)
        return changes

    def _plan_slot(self, change: LyricsChange, slot: Slot, id3_version) -> None:
        if slot.is_sylt:
            entries = list(slot.value)
            change.original_text = "\n".join(text for text, _time in entries)
            counts = [0] * len(self.replacements)
            new_entries = []
            for text, time in entries:
                new, found = apply_replacements(text, self.replacements)
                counts = [a + b for a, b in zip(counts, found)]
                new_entries.append((new, time))
            change.new_value = new_entries
            change.new_text = "\n".join(text for text, _time in new_entries)
        else:
            change.original_text = slot.value or ""
            change.new_value, counts = apply_replacements(slot.value or "", self.replacements)
            change.new_text = change.new_value
        change.details = [f"{describe_rule(rule)} ×{count}" for rule, count in zip(self.replacements, counts)
                          if count]
        changed = change.new_value != slot.value

        if self.id3_encoding is not None and slot.tag_format == "id3":
            wanted = ID3_ENCODINGS[self.id3_encoding]
            if slot.id3_encoding != wanted:
                if wanted == 3 and id3_version is not None and id3_version < 4:
                    change.status = STATUS_SKIPPED
                    change.skip_reason = "id3_utf8_needs_v24"
                    change.message = "UTF-8 en ID3 solo es válido en ID3v2.4; el tag es v2.3 y no se cambia de versión."
                    change.details = []
                    return
                if wanted == 0 and not _fits_latin1(change.new_value):
                    message = "el texto no cabe en Latin-1 (--id3-encoding latin1)"
                    if self.on_unencodable == ON_UNENCODABLE_ERROR:
                        raise ConversionAbort(f"{change.path} [{change.label}]: {message}")
                    change.status = STATUS_SKIPPED
                    change.skip_reason = "id3_unencodable"
                    change.message = f"No se convierte: {message}."
                    change.details = []
                    return
                change.new_encoding = wanted
                change.details.append(f"codificación ID3 {ID3_ENCODING_NAMES.get(slot.id3_encoding, '?')} -> "
                                      f"{ID3_ENCODING_NAMES[wanted]}")
                changed = True
        change.status = STATUS_CHANGE if changed else STATUS_UNCHANGED
        if not changed:
            change.details = []


def _fits_latin1(value) -> bool:
    texts = [text for text, _time in value] if isinstance(value, list) else [value]
    try:
        for text in texts:
            text.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return True
