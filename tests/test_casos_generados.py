"""
Pruebas con la biblioteca de casos de tools/generar_casos.py (ver
tools/CASOS.md).

La biblioteca se genera una vez en una carpeta temporal (necesita
ffmpeg); cada prueba que modifica archivos trabaja sobre una copia.
"""

import codecs
import subprocess
from pathlib import Path

import mutagen
import pytest
from mutagen.id3 import ID3
from typer.testing import CliRunner

from choconostle import backup
from choconostle.cli import app
from choconostle.config import BACKUP_DIR_NAME
from choconostle.normalizer import (
    MODE_STRIP, OFFSET_SUM, STATUS_CHANGE, STATUS_DECISION, STATUS_ERROR, STATUS_SKIPPED,
    STATUS_UNCHANGED, LyricsNormalizer,
)
from choconostle.scanner import scan_directory
from choconostle.textio import decode_lyrics, encoding_family, split_lines

def plan(root, **options):
    normalizer = LyricsNormalizer(MODE_STRIP, **options)
    changes = normalizer.plan(scan_directory(root))
    return normalizer, changes


def by_key(changes, root):
    """{"carpeta/archivo": cambio} para archivos y {"carpeta/archivo [ETIQUETA]": cambio} para incrustadas."""
    result = {}
    for change in changes:
        key = change.path.relative_to(root).as_posix()
        if change.kind != "file":
            key += f" [{change.label}]"
            if key in result:  # dos campos con la misma etiqueta (LYRICS x2, USLT eng/spa)
                key += f" {change.slot.key} #{change.slot.index + 1}"
        assert key not in result, key
        result[key] = change
    return result


@pytest.fixture(scope="module")
def plan_casos(casos):
    _normalizer, changes = plan(casos)
    return by_key(changes, casos)


def view_lines(data: bytes):
    decoded = decode_lyrics(data)
    return decoded.bom, split_lines(decoded.text)


def is_subsequence(small, big) -> bool:
    iterator = iter(big)
    return all(any(item == other for other in iterator) for item in small)


def audio_hash(path: Path) -> str:
    """Hash del audio decodificado (independiente de las etiquetas)."""
    output = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-f", "hash", "-"],
        check=True, capture_output=True, text=True,
    ).stdout
    return output.strip()


def tags_state(path: Path):
    audio = mutagen.File(path)
    if audio is None or audio.tags is None:
        return None
    if isinstance(audio.tags, ID3):
        return audio.tags.version, sorted((key, repr(frame)) for key, frame in audio.tags.items())
    return sorted((key, repr(value)) for key, value in audio.tags.items())


def files_state(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file() and BACKUP_DIR_NAME not in path.parts}


# --------------------------------------------------------------------------
# Biblioteca generada
# --------------------------------------------------------------------------

def test_case_13_is_pure_ascii(casos):
    data = (casos / "01_codificaciones" / "13 ascii puro.lrc").read_bytes()
    assert data.isascii()
    assert b"[ti:" in data


def test_no_errors_in_plan(plan_casos):
    errors = {key: change.message for key, change in plan_casos.items() if change.status == STATUS_ERROR}
    assert errors == {}


def test_file_changes_only_remove_whole_lines(plan_casos):
    """Sin offset, cada archivo nuevo es el original menos líneas completas, con el mismo BOM."""
    checked = 0
    for key, change in plan_casos.items():
        if change.kind != "file" or change.status != STATUS_CHANGE or "offset" in "".join(change.details):
            continue
        old_bom, old_lines = view_lines(change.original_bytes)
        new_bom, new_lines = view_lines(change.new_bytes)
        assert new_bom == old_bom, key
        assert len(new_lines) < len(old_lines), key
        assert is_subsequence(new_lines, old_lines), key
        checked += 1
    assert checked > 50


@pytest.mark.parametrize("name", ["03 CR solo", "04 mixto sin salto final", "02 CRLF"])
def test_newlines_preserved(plan_casos, name):
    change = plan_casos[f"02_saltos_de_linea/{name}.lrc"]
    assert change.status == STATUS_CHANGE
    _bom, old_lines = view_lines(change.original_bytes)
    _bom, new_lines = view_lines(change.new_bytes)
    kept = [line for line in old_lines if line in new_lines]
    assert [eol for _content, eol in new_lines] == [eol for _content, eol in kept]
    if name.startswith("04"):
        assert not change.new_bytes.endswith((b"\n", b"\r"))  # no se agrega salto final


def test_invisible_characters(plan_casos):
    change = plan_casos["02_saltos_de_linea/07 caracteres invisibles.lrc"]
    text = change.new_bytes.decode("utf-8")
    assert "[ti:" not in text and "[ar:" not in text
    assert "Uno​" in text and "Cuatro﻿" in text


@pytest.mark.parametrize("name,codec,family", [
    ("08 shift-jis japones", "shift_jis", "Shift-JIS"), ("09 gbk chino", "gbk", "GB"),
    ("10 euc-kr coreano", "euc_kr", "EUC-KR"), ("11 windows-1251 ruso", "cp1251", None),
])
def test_8bit_encodings_keep_bytes(plan_casos, name, codec, family):
    """
    La codificación detectada puede ser otro miembro de la familia
    compatible (cp949 por EUC-KR, cp932 por Shift-JIS, gb18030 por GBK),
    según la versión de charset-normalizer. Lo que importa: la familia es
    la correcta, decodificar y recodificar da los mismos bytes, el texto es
    el que se escribió y la vista no es aproximada.
    """
    change = plan_casos[f"01_codificaciones/{name}.lrc"]
    assert change.status == STATUS_CHANGE
    detected = decode_lyrics(change.original_bytes).detection.encoding
    if family is None:
        assert codecs.lookup(detected).name == codecs.lookup(codec).name
    else:
        assert encoding_family(detected) == family, detected
    data = change.original_bytes
    assert data.decode(detected).encode(detected) == data
    assert data.decode(detected) == data.decode(codec)
    assert not change.approximate, change.source_encoding
    assert change.new_bytes in change.original_bytes  # se quitaron solo líneas del inicio


def test_ambiguous_and_invalid_bytes_are_marked_approximate(plan_casos):
    for name in ("06 windows-1252 espanol", "17 utf8 con bytes invalidos"):
        change = plan_casos[f"01_codificaciones/{name}.lrc"]
        assert change.status == STATUS_CHANGE
        assert change.approximate
        assert change.new_bytes in change.original_bytes


def test_mojibake_warns_without_changing(plan_casos):
    change = plan_casos["01_codificaciones/07 mojibake utf8 leido como 1252.lrc"]
    assert any("mojibake" in warning for warning in change.warnings)
    assert "CanciÃ³n".encode() not in change.new_bytes  # solo estaba en [ti:]
    assert "lÃ".encode() in change.new_bytes  # el texto de la letra no se corrige


def test_header_cases(plan_casos):
    every = plan_casos["03_cabeceras/02 todas las conocidas.lrc"]
    assert b"[" in every.new_bytes and not any(
        line.startswith("[") and not line[1].isdigit()
        for line in every.new_bytes.decode().splitlines())
    assert "[lr:]" in every.details[0]

    unknown = plan_casos["03_cabeceras/17 cabecera desconocida.lrc"]
    assert b"[xtrack:7]" in unknown.new_bytes and b"[hash:" not in unknown.new_bytes
    assert unknown.unknown_headers == ["xtrack"]

    spaces = plan_casos["03_cabeceras/10 espacios dentro.lrc"]
    assert b"[ ti : Con espacios ]" in spaces.new_bytes
    assert b"[ar:" not in spaces.new_bytes and b"[al:" not in spaces.new_bytes

    sections = plan_casos["03_cabeceras/13 corchetes que no son cabeceras.lrc"]
    assert b"[Coro: Artista Invitado]" in sections.new_bytes and b"[ti:" not in sections.new_bytes

    brackets = plan_casos["03_cabeceras/18 valor con corchetes y dos puntos.lrc"]
    assert brackets.new_bytes.startswith(b"[00:01.00]")

    only_headers = plan_casos["03_cabeceras/15 solo cabeceras.lrc"]
    assert only_headers.status == STATUS_SKIPPED and "vacía" in only_headers.message


def test_offset_cases(plan_casos):
    plus = plan_casos["03_cabeceras/03 offset positivo +500.lrc"]
    assert plus.new_bytes.startswith(b"[00:00.50]Esta")
    minus = plan_casos["03_cabeceras/04 offset negativo -300.lrc"]
    assert minus.new_bytes.startswith(b"[00:01.30]Esta")
    unsigned = plan_casos["03_cabeceras/05 offset sin signo 250.lrc"]
    assert unsigned.new_bytes.startswith(b"[00:00.75]Esta")
    negative = plan_casos["03_cabeceras/06 offset que deja negativo.lrc"]
    assert negative.new_bytes.startswith(b"[00:00.00]Esta")
    assert any("00:00" in warning for warning in negative.warnings)
    words = plan_casos["05_palabra_por_palabra/03 enhanced con offset.lrc"]
    assert words.new_bytes.startswith(b"[00:00.50]<00:00.50>Esta <00:00.90>es")

    for name, reason in [("07 offset invalido", "inválido"), ("08 dos offsets", "--offset-policy")]:
        change = plan_casos[f"03_cabeceras/{name}.lrc"]
        assert change.status == STATUS_DECISION and reason in change.message


def test_offset_policy_sum_and_strip_unknown(casos):
    _normalizer, changes = plan(casos, offset_policy=OFFSET_SUM, strip_unknown=True)
    changes = by_key(changes, casos)
    both = changes["03_cabeceras/08 dos offsets.lrc"]
    assert both.status == STATUS_CHANGE and "+500 ms" in both.details[-1]
    assert both.new_bytes.startswith(b"[00:00.50]Esta")
    assert changes["03_cabeceras/07 offset invalido.lrc"].status == STATUS_DECISION
    assert b"[xtrack:" not in changes["03_cabeceras/17 cabecera desconocida.lrc"].new_bytes


def test_nearly_empty_cases(casos, plan_casos):
    instrumental = plan_casos["07_casi_vacias/02 instrumental con cabeceras.lrc"]
    assert instrumental.status == STATUS_CHANGE and instrumental.nearly_empty
    assert instrumental.new_bytes == b"[00:00.00]Instrumental\n"
    for name in ("01 solo instrumental", "05 archivo vacio 0 bytes", "06 solo espacios y saltos",
                 "07 solo BOM", "08 marcas sin texto"):
        change = plan_casos[f"07_casi_vacias/{name}.lrc"]
        assert change.status == STATUS_UNCHANGED and change.warnings, name
    embedded = plan_casos["10_incrustadas/11 FLAC casi vacia.flac [LYRICS]"]
    assert embedded.status == STATUS_CHANGE and embedded.nearly_empty

    _normalizer, changes = plan(casos, skip_near_empty=True)
    changes = by_key(changes, casos)
    assert changes["07_casi_vacias/02 instrumental con cabeceras.lrc"].status == STATUS_SKIPPED


def test_embedded_cases(plan_casos):
    bom = plan_casos["10_incrustadas/05 FLAC con BOM dentro del texto.flac [LYRICS]"]
    assert bom.status == STATUS_CHANGE and bom.new_value.startswith("[00:01.00]")
    crlf = plan_casos["10_incrustadas/06 FLAC con CRLF dentro.flac [LYRICS]"]
    assert crlf.new_value.startswith("[00:01.00]") and "\r\n" in crlf.new_value
    assert crlf.new_value.count("\r\n") == crlf.original_value.count("\r\n") - 4
    sylt = plan_casos["10_incrustadas/26 MP3 SYLT con cabecera como entrada.mp3 [SYLT]"]
    assert [text for text, _time in sylt.new_value] == ["Uno", "Dos", "Tres", "Cuatro"]
    assert plan_casos["10_incrustadas/25 MP3 SYLT milisegundos.mp3 [SYLT]"].status == STATUS_UNCHANGED
    offset = plan_casos["10_incrustadas/10 FLAC con offset.flac [LYRICS]"]
    assert offset.new_value.startswith("[00:00.50]")


# --------------------------------------------------------------------------
# --apply y revert sobre toda la biblioteca
# --------------------------------------------------------------------------

def non_lyric_tags(path: Path):
    """Etiquetas que no son letras, leídas con mutagen."""
    from choconostle.tags import LYRICS_KEYS
    state = tags_state(path)
    if state is None:
        return None
    version, items = state if isinstance(state, tuple) else (None, state)

    def is_lyric(key):
        return key.lower() in LYRICS_KEYS or key.startswith(
            ("USLT", "SYLT", "TXXX:LYRICS", "TXXX:UNSYNCEDLYRICS", "\xa9lyr"))
    return version, [(key, value) for key, value in items if not is_lyric(key)]


def test_ogg_requires_full_rewrite_by_default(plan_casos):
    for name in ("42 OPUS LYRICS.opus", "43 OGG Vorbis LYRICS.ogg"):
        change = plan_casos[f"10_incrustadas/{name} [LYRICS]"]
        assert change.status == STATUS_SKIPPED and change.skip_reason == "full_rewrite"
        assert "reescritura completa, requiere" in change.message


def test_apply_then_revert_generated_library(biblioteca):
    """Etapa ②: todo vuelve idéntico byte a byte, también MP3, M4A, WavPack y Ogg."""
    before = files_state(biblioteca)
    normalizer, changes = plan(biblioteca, allow_full_rewrite=True)
    planned = {change.path for change in changes if change.status == STATUS_CHANGE}
    audio_files = {path for path in planned if path.suffix.lower() not in (".lrc", ".txt")}
    assert {path.suffix for path in audio_files} >= {".flac", ".mp3", ".m4a", ".wv", ".opus", ".ogg"}
    audio_before = {path: audio_hash(path) for path in audio_files}
    tags_before = {path: non_lyric_tags(path) for path in audio_files}

    session = normalizer.apply(changes, biblioteca)
    assert all(item["status"] == backup.ITEM_APPLIED for item in session.manifest["items"])
    after = files_state(biblioteca)
    untouched = {key for key in before if biblioteca / key not in planned}
    assert all(after[key] == before[key] for key in untouched)
    for path in audio_files:  # aplicado: audio y etiquetas ajenas a la letra intactos
        assert audio_hash(path) == audio_before[path], path.name
        assert non_lyric_tags(path) == tags_before[path], path.name
    # El respaldo no contiene audio.
    assert not [p for p in session.folder.rglob("*") if p.suffix.lower() in
                (".flac", ".mp3", ".m4a", ".wv", ".opus", ".ogg", ".wav")]
    assert not list(session.folder.glob("pendiente/*"))

    # Una segunda pasada no encuentra nada que cambiar.
    _normalizer, again = plan(biblioteca, allow_full_rewrite=True)
    assert [change for change in again if change.status == STATUS_CHANGE] == []

    results = backup.revert(session.folder)
    assert {result.status for result in results} == {backup.REVERT_RESTORED}
    assert all(not result.message for result in results)
    assert files_state(biblioteca) == before


def test_cli_diff_shows_everything_and_log(biblioteca):
    runner = CliRunner()
    result = runner.invoke(app, ["normalize-lyrics", str(biblioteca), "--strip-headers", "--diff",
                                 "--no-progress"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "... y" not in result.output
    assert "Desconocidos / requieren decisión" in result.output
    assert "08 dos offsets.lrc" in result.output
    assert "⟨U+200B⟩[ti:Invisible]" in result.output

    result = runner.invoke(app, ["normalize-lyrics", str(biblioteca), "--strip-headers", "--apply",
                                 "--no-progress"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    log = next((biblioteca / BACKUP_DIR_NAME).glob("*/registro.txt")).read_text(encoding="utf-8")
    assert "⟨U+200B⟩[ti:Invisible]" in log
    assert "Vista aproximada" in log
    assert "detectada Shift-JIS" in log
    assert "-[ti:テスト曲]" in log


def test_encoding_option_shares_conversion(biblioteca):
    _normalizer, changes = plan(biblioteca, encoding="utf8")
    changes = by_key(changes, biblioteca)
    japanese = changes["01_codificaciones/08 shift-jis japones.lrc"]
    assert japanese.status == STATUS_CHANGE
    assert japanese.new_bytes.decode("utf-8").startswith("[00:01.00]これはテスト")
    ambiguous = changes["01_codificaciones/06 windows-1252 espanol.lrc"]
    assert ambiguous.status == STATUS_SKIPPED and "--source-encoding" in ambiguous.message
    utf16 = changes["01_codificaciones/03 utf16 LE con BOM.lrc"]
    assert utf16.new_bytes.startswith(b"[00:01.00]") and "UTF-16 LE -> UTF-8" in utf16.details

    _normalizer, changes = plan(biblioteca, encoding="cp1252")
    changes = by_key(changes, biblioteca)
    japanese = changes["01_codificaciones/14 japones utf8.lrc"]
    assert japanese.status == STATUS_SKIPPED and "no se pueden representar" in japanese.message
    assert "?" not in japanese.message.split(":")[0]


def test_invalid_encoding_option(biblioteca):
    result = CliRunner().invoke(app, ["normalize-lyrics", str(biblioteca), "--strip-headers",
                                      "--encoding", "no-existe"])
    assert result.exit_code == 2


def test_cli_strip_unknown_shows_removed_lines_in_diff(biblioteca):
    result = CliRunner().invoke(app, [
        "normalize-lyrics", str(biblioteca), "--strip-headers", "--strip-unknown-headers", "--diff",
        "--no-progress", "--only", "03_cabeceras"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "quita desconocidas [xtrack:]" in result.output
    assert "-[xtrack:7]" in result.output
    # [Coro: Artista Invitado] va después de la primera línea de letra: no se toca.
    assert "-[00:04.50][Coro: Artista Invitado]" not in result.output
    assert "Cabeceras desconocidas del inicio: se quitan" in result.output
