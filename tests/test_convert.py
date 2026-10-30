"""
Pruebas de la etapa ④: convert-lyrics.

Todo sobre copias de la biblioteca de tools/generar_casos.py (fixture
`casos`) o archivos creados con sus funciones. Lo que depende del sistema
(diario, desconexión, reanudación) se ejecuta en los modos "posix" y
"windows", como en la etapa ③.
"""

import codecs
import shutil
from pathlib import Path

import pytest

from choconostle import backup
from choconostle.cli import app
from choconostle.config import BACKUP_DIR_NAME
from choconostle.converter import ConversionAbort, LyricsConverter
from choconostle.normalizer import STATUS_CHANGE, STATUS_SKIPPED, STATUS_UNCHANGED
from choconostle.rawtags.id3 import open_id3, parse_tag, syncsafe
from choconostle.scanner import scan_directory
from conftest import load_generator
from test_run import PATH_MODES, Unplug, eio, files, runner, win_error

CODIF = "01_codificaciones"


@pytest.fixture(scope="module")
def original(casos):
    return files(casos)


def plan(root: Path, **options):
    converter = LyricsConverter(**options)
    scan = scan_directory(root)
    changes = list(converter.plan_tracks(scan.tracks, scan.orphan_lyrics))
    keyed = {}
    for change in changes:
        key = change.path.relative_to(root).as_posix() + ("" if change.kind == "file" else f" [{change.label}]")
        keyed[key] = change
    return keyed


def convert(root: Path, *args, apply=True):
    return runner.invoke(app, ["convert-lyrics", str(root), "--no-progress", *args, *(["--apply"] if apply else [])],
                         env={"COLUMNS": "220"})


# --------------------------------------------------------------------------
# Archivos .lrc/.txt: --to y --eol
# --------------------------------------------------------------------------

def test_defaults_utf8_and_lf(casos):
    changes = plan(casos)
    utf16 = changes[f"{CODIF}/03 utf16 LE con BOM.lrc"]
    assert utf16.status == STATUS_CHANGE and utf16.new_bytes.startswith(b"[ti:Canci\xc3\xb3n")
    assert "UTF-16 LE -> UTF-8" in utf16.details and "quita BOM" in utf16.details
    bom = changes[f"{CODIF}/02 utf8 con BOM.lrc"]
    assert bom.new_bytes == bom.original_bytes[3:]
    crlf = changes["02_saltos_de_linea/02 CRLF.lrc"]
    assert b"\r" not in crlf.new_bytes and crlf.new_bytes == crlf.original_bytes.replace(b"\r\n", b"\n")
    mixed = changes["02_saltos_de_linea/04 mixto sin salto final.lrc"]
    assert b"\r" not in mixed.new_bytes and not mixed.new_bytes.endswith(b"\n")  # no se agrega salto final
    assert "saltos de línea mixtos (CRLF, LF, CR) -> LF" in mixed.details
    for name in ("01 utf8 sin BOM", "12 utf8 multiescritura", "13 ascii puro"):
        assert changes[f"{CODIF}/{name}.lrc"].status == STATUS_UNCHANGED, name
    japanese = changes[f"{CODIF}/08 shift-jis japones.lrc"]
    assert japanese.new_bytes.decode("utf-8") == japanese.original_bytes.decode("shift_jis")
    # Por defecto las incrustadas no se tocan.
    assert not [c for c in changes.values() if c.kind == "embedded"]


def test_eol_crlf_and_keep(casos):
    crlf = plan(casos, eol="crlf")
    lf_file = crlf[f"{CODIF}/01 utf8 sin BOM.lrc"]
    assert lf_file.new_bytes == lf_file.original_bytes.replace(b"\n", b"\r\n")
    keep = plan(casos, eol="keep")
    mixed = keep["02_saltos_de_linea/04 mixto sin salto final.lrc"]
    assert mixed.status == STATUS_UNCHANGED  # ya es UTF-8 (ASCII) y los saltos se conservan
    utf16 = keep[f"{CODIF}/03 utf16 LE con BOM.lrc"]
    assert utf16.new_bytes == utf16.original_bytes[2:].decode("utf-16-le").encode("utf-8")


def test_target_that_cannot_represent_characters_is_skipped(casos):
    changes = plan(casos, to="cp1252")
    japanese = changes[f"{CODIF}/14 japones utf8.lrc"]
    assert japanese.status == STATUS_SKIPPED and "no se pueden representar" in japanese.message
    assert japanese.new_bytes is None  # nunca se escribe con "?"
    spanish = changes[f"{CODIF}/01 utf8 sin BOM.lrc"]
    assert spanish.new_bytes == spanish.original_bytes.decode("utf-8").encode("cp1252")


def test_on_unencodable_error_stops_before_modifying(biblioteca):
    before = files(biblioteca)
    with pytest.raises(ConversionAbort):
        plan(biblioteca, to="cp1252", on_unencodable="error")
    result = convert(biblioteca, "--to", "cp1252", "--on-unencodable", "error")
    assert result.exit_code == 2 and "--on-unencodable error" in result.output
    assert files(biblioteca) == before
    assert not (biblioteca / BACKUP_DIR_NAME).exists() or not list((biblioteca / BACKUP_DIR_NAME).iterdir())


# --------------------------------------------------------------------------
# Codificación de origen: detección, --prefer-encoding, --source-encoding
# --------------------------------------------------------------------------

def test_ambiguous_source_and_prefer_encoding(casos):
    name = f"{CODIF}/06 windows-1252 espanol.lrc"
    original = (casos / name).read_bytes()
    plain = plan(casos)[name]
    assert plain.status == STATUS_SKIPPED and "--prefer-encoding" in plain.message
    preferred = plan(casos, prefer_encoding="cp1252")[name]
    assert preferred.status == STATUS_CHANGE
    assert preferred.new_bytes.decode("utf-8") == original.decode("cp1252")  # "ñandú", no "ńandú"
    assert "desempatada con --prefer-encoding" in preferred.source_encoding
    # Una preferencia que no está entre los empatados no impone nada.
    assert plan(casos, prefer_encoding="cp1251")[name].status == STATUS_SKIPPED
    # Una detección fiable no cambia por --prefer-encoding.
    japanese = plan(casos, prefer_encoding="cp1252")[f"{CODIF}/08 shift-jis japones.lrc"]
    assert japanese.new_bytes.decode("utf-8") == (casos / f"{CODIF}/08 shift-jis japones.lrc").read_bytes().decode("shift_jis")


def test_source_encoding_only_for_8bit_files(casos):
    changes = plan(casos, source_encoding="cp1252")
    spanish = changes[f"{CODIF}/06 windows-1252 espanol.lrc"]
    assert spanish.status == STATUS_CHANGE and "--source-encoding" in spanish.source_encoding
    # Un archivo UTF-8 válido nunca se reinterpreta: el mojibake solo se avisa.
    mojibake = changes[f"{CODIF}/07 mojibake utf8 leido como 1252.lrc"]
    assert mojibake.status == STATUS_UNCHANGED
    assert any("mojibake" in warning for warning in mojibake.warnings)
    # Bytes inválidos para la codificación indicada: se omite.
    bad = plan(casos, source_encoding="ascii")[f"{CODIF}/06 windows-1252 espanol.lrc"]
    assert bad.status == STATUS_SKIPPED and "no es" in bad.message


# --------------------------------------------------------------------------
# Sustituciones
# --------------------------------------------------------------------------

def test_replacements_never_touch_timestamps(casos, tmp_path):
    changes = plan(casos, replacements=[("0", "O"), ("ó", "o"), (":", ";")])
    change = changes["03_cabeceras/03 offset positivo +500.lrc"]
    text = change.new_bytes.decode("utf-8")
    assert "[00:01.00]" in text and "[offset;+5OO]" in text  # la cabecera es texto; la marca no
    assert "[ti;Offset]" in text
    assert any("«ó» → «o»" in detail for detail in change.details)
    words = changes["05_palabra_por_palabra/01 enhanced A2 con cabeceras.lrc"].new_bytes.decode()
    assert "<00:01.40>es" in words and "[00:01.00]" in words


def test_replace_map_and_rule_validation(biblioteca, tmp_path):
    rules = tmp_path / "reglas.txt"
    rules.write_text("# comentarios y líneas vacías se ignoran\n\nó=o\ná\ta\n\\u00f1=n\n", encoding="utf-8")
    result = convert(biblioteca, "--replace-map", str(rules), "--only", CODIF, apply=False)
    assert result.exit_code == 0, result.output
    assert "Sustituciones: «ó» → «o», «á» → «a», «ñ» → «n»" in result.output
    for bad in ["sin-igual", "=x", "a=[", "a=<"]:
        result = convert(biblioteca, "--replace-char", bad, apply=False)
        assert result.exit_code == 2, bad


def test_replacements_in_embedded_lyrics_and_revert(biblioteca, original):
    result = convert(biblioteca, "--replace-char", "ó=o", "--only", "10_incrustadas")
    assert result.exit_code == 0, result.output
    from mutagen.flac import FLAC
    lyrics = FLAC(biblioteca / "10_incrustadas/01 FLAC LYRICS con cabeceras.flac")["LYRICS"][0]
    assert "ó" not in lyrics and "Cancion" in lyrics and "[00:01.00]" in lyrics
    uslt = open_id3(biblioteca / "10_incrustadas/20 MP3 v2.4 USLT utf8.mp3").slots()[0].value
    assert "ó" not in uslt and "[00:01.00]" in uslt
    folder = next((biblioteca / BACKUP_DIR_NAME).iterdir())
    backup.revert(folder)
    assert files(biblioteca) == original


# --------------------------------------------------------------------------
# --id3-encoding
# --------------------------------------------------------------------------

def test_id3_encoding_rules(casos):
    utf8 = plan(casos, id3_encoding="utf8")
    v23 = utf8["10_incrustadas/21 MP3 v2.3 USLT utf16.mp3 [USLT]"]
    assert v23.status == STATUS_SKIPPED and v23.skip_reason == "id3_utf8_needs_v24"
    latin1 = plan(casos, id3_encoding="latin1")
    already = latin1["10_incrustadas/22 MP3 v2.3 USLT latin1.mp3 [USLT]"]
    assert already.status == STATUS_UNCHANGED
    converted = latin1["10_incrustadas/20 MP3 v2.4 USLT utf8.mp3 [USLT]"]
    assert converted.status == STATUS_CHANGE and converted.new_encoding == 0


def test_id3_latin1_skips_characters_that_do_not_fit(tmp_path):
    gen = load_generator()
    root = tmp_path / "lib"
    japanese = gen.synced(gen.JA, ["[ti:テスト曲]", ""])
    gen.make_mp3(root / "jp.mp3", gen.basic_id3("jp") + [gen.USLT(japanese, enc=gen.ENC_UTF16)], 3)
    change = plan(root, id3_encoding="latin1")["jp.mp3 [USLT]"]
    assert change.status == STATUS_SKIPPED and change.skip_reason == "id3_unencodable"
    with pytest.raises(ConversionAbort):
        plan(root, id3_encoding="latin1", on_unencodable="error")


def test_id3_utf16_needs_full_rewrite_and_reverts_identical(biblioteca, original):
    target = "10_incrustadas/22 MP3 v2.3 USLT latin1.mp3"
    result = convert(biblioteca, "--id3-encoding", "utf16", "--only", "10_incrustadas", "--diff", apply=False)
    assert "Necesitarían reescritura completa" in result.output and "MP3:" in result.output
    assert "se omiten sin --allow-full-rewrite" in result.output
    result = convert(biblioteca, "--id3-encoding", "utf16", "--allow-full-rewrite", "--only", "10_incrustadas")
    assert result.exit_code == 0, result.output
    editor = open_id3(biblioteca / target)
    assert editor.layout.version == 3  # no se cambia la versión del tag
    uslt = next(f for f in editor.layout.frames if f.frame_id == "USLT")
    assert uslt.lyric.encoding == 1 and uslt.lyric.values[0][1] == codecs.BOM_UTF16_LE
    data = original[target]
    old_frames = {f.frame_id: f.raw for f in parse_tag(data[:10 + syncsafe(data[6:10])]).frames}
    for frame in editor.layout.frames:
        if frame.frame_id != "USLT":
            assert frame.raw == old_frames[frame.frame_id], frame.frame_id  # el resto, byte a byte
    folder = next((biblioteca / BACKUP_DIR_NAME).iterdir())
    results = backup.revert(folder)
    assert {r.status for r in results} == {backup.REVERT_RESTORED}
    assert files(biblioteca) == original


def test_flac_full_rewrite_counted_before_applying(tmp_path):
    gen = load_generator()
    root = tmp_path / "lib"
    flac = root / "largo.flac"
    gen.make_flac(flac, [("TITLE", "x"), ("LYRICS", gen.synced(gen.ES))])
    # Cada "e" se convierte en 1000 caracteres: la letra crece más que el relleno de 8 KB.
    result = convert(root, "--replace-char", "e=" + "E" * 1000, "--diff", apply=False)
    assert result.exit_code == 0, result.output
    assert "Necesitarían reescritura completa" in result.output and "FLAC: 1" in result.output
    assert "reescritura completa, requiere" in result.output


# --------------------------------------------------------------------------
# Diff y reporte
# --------------------------------------------------------------------------

def test_diff_shows_source_encoding_and_reliability(biblioteca):
    result = convert(biblioteca, "--diff", "--only", CODIF, apply=False)
    assert result.exit_code == 0, result.output
    output = result.output
    assert "origen: detectada Shift-JIS (cp932) (fiable)" in output
    assert "08 shift-jis japones.lrc: (detectada Shift-JIS (cp932) (fiable))" in output
    assert "origen: UTF-16 LE con BOM (fiable)" in output
    assert "06 windows-1252 espanol.lrc: Codificación de origen no fiable (codificación ambigua" in output
    assert "Letras incrustadas: no se tocan" in output


def test_unchanged_files_are_not_rewritten(biblioteca):
    path = biblioteca / f"{CODIF}/01 utf8 sin BOM.lrc"
    before = path.stat().st_mtime_ns
    result = convert(biblioteca, "--only", CODIF)
    assert result.exit_code == 0, result.output
    assert path.stat().st_mtime_ns == before


# --------------------------------------------------------------------------
# Mismo sistema de ejecución: --resume, desconexión, revert (posix y windows)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def converted(casos, tmp_path_factory):
    root = tmp_path_factory.mktemp("convref") / "lib"
    shutil.copytree(casos, root)
    result = convert(root, "--replace-char", "ó=o", "--allow-full-rewrite")
    assert result.exit_code == 0, result.output
    return files(root)


@pytest.mark.parametrize("paths", PATH_MODES)
@pytest.mark.parametrize("on,after", [("library", 6), ("diary", 9)])
@pytest.mark.parametrize("error", [eio, lambda: win_error(1167)], ids=["EIO", "WinError1167"])
def test_disconnection_then_resume(biblioteca, converted, monkeypatch, error, on, after, paths):
    original = files(biblioteca)
    unplug = Unplug(monkeypatch, biblioteca, after=after, error=error, paths=paths, on=on)
    result = convert(biblioteca, "--replace-char", "ó=o", "--allow-full-rewrite")
    assert unplug.unplugged
    assert result.exit_code == 3, result.output
    assert "choconostle convert-lyrics" in result.output and "--resume" in result.output
    monkeypatch.undo()
    folder = next((biblioteca / BACKUP_DIR_NAME).iterdir())
    # Reanudar con el comando equivocado no se permite.
    wrong = runner.invoke(app, ["normalize-lyrics", str(biblioteca), "--resume", str(folder), "--no-progress"])
    assert wrong.exit_code == 2 and "convert-lyrics" in wrong.output
    result = runner.invoke(app, ["convert-lyrics", str(biblioteca), "--resume", str(folder), "--no-progress"])
    assert result.exit_code == 0, result.output
    assert files(biblioteca) == converted
    backup.revert(folder)
    assert files(biblioteca) == original


def test_revert_latest_after_convert(biblioteca):
    before = files(biblioteca)
    assert convert(biblioteca, "--only", CODIF).exit_code == 0
    assert files(biblioteca) != before
    result = runner.invoke(app, ["revert", str(biblioteca), "--latest"])
    assert result.exit_code == 0, result.output
    assert files(biblioteca) == before


@pytest.mark.parametrize("target", ["utf-16", "utf-16-le", "utf_32"])
def test_wide_unicode_target_warns(biblioteca, target):
    result = convert(biblioteca, "--to", target, "--diff", "--only", CODIF, apply=False)
    assert result.exit_code == 0, result.output
    assert "AVISO: Destino UTF-16/UTF-32" in result.output
    assert "aviso: Destino UTF-16/UTF-32: casi ningún reproductor" in result.output
    assert "Destino UTF-16" not in convert(biblioteca, "--only", CODIF, apply=False).output
