"""
Lo que antes salía como «desconocido» en normalize-lyrics (rc3):

a) etiquetas de sección estilo Genius ([Intro: Artista], [Chorus], [Verso 2]):
   son letra, nunca se listan ni se quitan;
b) [instrumental:true]: se conserva y se cuenta aparte;
c) datos extendidos de SpotiFLAC ([x-romaji:...]): se quitan solo en el
   bloque inicial, antes de la primera línea de letra.
"""

import pytest
from typer.testing import CliRunner

from builders import make_flac
from choconostle.cli import app
from choconostle.normalizer import MODE_STANDARDIZE, MODE_STRIP, normalize_sylt, normalize_text

BODY = "[00:01.00]Uno\n[00:02.00]Dos\n[00:03.00]Tres\n"
runner = CliRunner()


def strip(text, **options):
    return normalize_text(text, MODE_STRIP, **options)


SECTIONS = ["[Intro: Pitbull & Lil Jon]", "[Chorus]", "[Verse 1]", "[Verse 2: Artista]", "[Pre-Chorus]",
            "[Post-Chorus]", "[Bridge]", "[Outro]", "[Hook]", "[Refrain]", "[Interlude]", "[Breakdown]",
            "[Drop]", "[Intro]", "[Verso 2]", "[Precoro]", "[Pre-coro: X]", "[Coro]", "[Estribillo]",
            "[Puente]", "[Interludio]", "[CHORUS 3]"]


@pytest.mark.parametrize("label", SECTIONS)
def test_sections_are_lyrics_never_unknown_nor_removed(label):
    text = f"{label}\n{BODY}{label}\n{BODY}"
    for options in ({}, {"strip_unknown": True}):
        result = strip(text, **options)
        assert result.text == text and result.unknown_headers == [] and result.removed_unknown == []
    result = normalize_text(text, MODE_STANDARDIZE, ["[ar:A]"])
    assert result.text == "[ar:A]\n" + text


def test_section_right_after_headers_is_kept():
    text = "[ar:A]\n[ti:T]\n[Intro: Pitbull & Lil Jon]\n" + BODY
    result = strip(text, strip_unknown=True)
    assert result.text == "[Intro: Pitbull & Lil Jon]\n" + BODY
    assert result.removed_headers == ["ar", "ti"] and result.unknown_headers == []


def test_instrumental_is_kept_and_counted():
    result = strip("[ar:A]\n[instrumental:true]\n")
    assert result.text == "[instrumental:true]\n" and result.instrumental
    assert not result.nearly_empty and result.warnings == [] and not result.empty_result
    only = strip("[instrumental:true]\n", strip_unknown=True)
    assert only.text == "[instrumental:true]\n" and not only.changed and only.unknown_headers == []
    assert strip("[Instrumental:TRUE]\n" + BODY).instrumental


X_LINES = "[x-romaji:1000:YWJj]\n[x-romaji-words:1000:ZGVm]\n[x-translation:1000:Z2hp]\n[x-otro:datos]\n"


def test_extended_data_removed_only_in_initial_block():
    text = "[ar:A]\n" + X_LINES + "\n" + BODY
    for result in (strip(text), normalize_text(text, MODE_STANDARDIZE, ["[ar:B]"])):
        assert result.removed_extended == 4 and result.unknown_headers == []
        assert "x-" not in result.text and BODY in result.text


def test_extended_data_after_lyrics_is_never_touched():
    text = BODY + X_LINES
    for options in ({}, {"strip_unknown": True}):
        result = strip(text, **options)
        assert result.text == text and not result.changed
        assert result.removed_extended == 0 and result.kept_extended == 4
    # Una sección también es letra: las x- que vienen después no se quitan.
    text = "[ti:T]\n[Intro]\n" + X_LINES + BODY
    result = strip(text)
    assert result.text == "[Intro]\n" + X_LINES + BODY and result.removed_extended == 0


def test_sylt_sections_instrumental_and_extended():
    entries = [("[ar:A]", 0), ("[x-romaji:0:YQ==]", 0), ("[Chorus]", 0), ("Uno", 1000), ("Dos", 2000),
               ("Tres", 3000), ("[x-translation:0:Yg==]", 4000)]
    result = normalize_sylt(entries, strip_unknown=True)
    assert result.entries == [("[Chorus]", 0), ("Uno", 1000), ("Dos", 2000), ("Tres", 3000),
                              ("[x-translation:0:Yg==]", 4000)]
    assert result.removed_extended == 1 and result.kept_extended == 1 and result.unknown_headers == []
    instrumental = normalize_sylt([("[instrumental:true]", 0)])
    assert instrumental.instrumental and not instrumental.nearly_empty and not instrumental.changed


# --------------------------------------------------------------------------
# Archivos reales: --diff, reporte, scan (pantalla y JSON)
# --------------------------------------------------------------------------

def _library(tmp_path):
    lib = tmp_path / "lib"
    make_flac(lib / "a" / "01.flac", tags={"TITLE": "Uno"})
    (lib / "a" / "01.lrc").write_text("[ar:x]\n" + X_LINES + BODY, encoding="utf-8")
    make_flac(lib / "a" / "02.flac", tags={"TITLE": "Dos"})
    after = BODY + X_LINES  # x- después de la letra: no debe cambiar
    (lib / "a" / "02.lrc").write_text(after, encoding="utf-8")
    make_flac(lib / "a" / "03.flac", tags={"TITLE": "Tres"})
    (lib / "a" / "03.lrc").write_text("[ti:T]\n[Intro: Pitbull & Lil Jon]\n" + BODY, encoding="utf-8")
    make_flac(lib / "a" / "04.flac", tags={"TITLE": "Cuatro"})
    (lib / "a" / "04.lrc").write_text("[instrumental:true]\n", encoding="utf-8")
    return lib, after


def test_normalize_report_counts_and_apply(tmp_path):
    lib, after = _library(tmp_path)
    result = runner.invoke(app, ["normalize-lyrics", str(lib), "--strip-headers", "--diff", "--no-progress"],
                           env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    out = result.output
    assert "quita 4 datos extendidos (SpotiFLAC)" in out
    assert "Instrumentales (se conservan)" in out and "Con datos extendidos (SpotiFLAC)" in out
    assert "Desconocidos" not in out  # ni secciones, ni instrumental, ni x- son desconocidos
    result = runner.invoke(app, ["normalize-lyrics", str(lib), "--strip-headers", "--strip-unknown-headers",
                                 "--apply", "--no-progress"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert (lib / "a" / "01.lrc").read_text(encoding="utf-8") == BODY
    assert (lib / "a" / "02.lrc").read_text(encoding="utf-8") == after
    assert (lib / "a" / "03.lrc").read_text(encoding="utf-8") == "[Intro: Pitbull & Lil Jon]\n" + BODY
    assert (lib / "a" / "04.lrc").read_text(encoding="utf-8") == "[instrumental:true]\n"


def test_scan_counts_instrumentals(tmp_path):
    import json
    lib, _after = _library(tmp_path)
    output = tmp_path / "r.json"
    result = runner.invoke(app, ["scan", str(lib), "--json", str(output), "--no-progress"],
                           env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "Instrumentales (se conservan)" in result.output and "Instrumentales ()" not in result.output
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["lyrics_issues"]["instrumental"] == 1
    assert not any(item["location"].endswith("04.lrc") for item in report["lyrics_nearly_empty"])
