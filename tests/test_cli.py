import json

from typer.testing import CliRunner

from builders import make_flac
from choconostle.cli import app
from choconostle.config import APP_VERSION

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert APP_VERSION in result.output


def test_scan_writes_json(tmp_path):
    library = tmp_path / "lib"
    make_flac(library / "[2019] Álbum" / "01.flac")
    (library / "[2019] Álbum" / "01.lrc").write_text("[ar:x]\n[00:01.00]Hola", encoding="utf-8")
    output = tmp_path / "reporte.json"

    result = runner.invoke(app, ["scan", str(library), "--json", str(output), "--no-progress"])
    assert result.exit_code == 0, result.output
    assert "Resumen" in result.output
    assert "[2019] Álbum/01.lrc" in result.output

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["tracks"] == 1
    assert report["tracks"][0]["lyrics"][0]["headers"] == ["ar"]


def test_scan_missing_folder(tmp_path):
    result = runner.invoke(app, ["scan", str(tmp_path / "no-existe")])
    assert result.exit_code == 2


def _library_with_headers(tmp_path):
    library = tmp_path / "lib"
    make_flac(library / "a" / "01.flac", tags={"TITLE": "Uno", "LYRICS": "[ti:Uno]\n[00:01.00]a\n[00:02.00]b\n[00:03.00]c"})
    (library / "a" / "01.lrc").write_text("[ar:x]\n[00:01.00]a\n[00:02.00]b\n[00:03.00]c\n", encoding="utf-8")
    return library


def test_normalize_requires_one_mode(tmp_path):
    library = _library_with_headers(tmp_path)
    assert runner.invoke(app, ["normalize-lyrics", str(library)]).exit_code == 2
    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--standardize-headers"])
    assert result.exit_code == 2


def test_normalize_simulation_then_apply_then_revert(tmp_path):
    library = _library_with_headers(tmp_path)
    lrc = library / "a" / "01.lrc"
    original = lrc.read_bytes()

    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--no-progress"])
    assert result.exit_code == 0, result.output
    assert "SIMULACIÓN" in result.output
    assert lrc.read_bytes() == original

    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--apply",
                                 "--no-progress"])
    assert result.exit_code == 0, result.output
    assert lrc.read_text(encoding="utf-8") == "[00:01.00]a\n[00:02.00]b\n[00:03.00]c\n"
    backups = list((library / "ChoconostleLRCTool_back").iterdir())
    assert len(backups) == 1

    result = runner.invoke(app, ["revert", str(backups[0])])
    assert result.exit_code == 0, result.output
    assert lrc.read_bytes() == original


def test_revert_missing_manifest(tmp_path):
    result = runner.invoke(app, ["revert", str(tmp_path)])
    assert result.exit_code == 2


def test_scan_reports_nearly_empty(tmp_path):
    library = tmp_path / "lib"
    make_flac(library / "01.flac")
    (library / "01.lrc").write_text("[ar:x]\n[00:00.00]Instrumental\n", encoding="utf-8")
    result = runner.invoke(app, ["scan", str(library), "--no-progress"])
    assert "Letras casi vacías (1)" in result.output


def test_help_shows_header_brackets():
    result = runner.invoke(app, ["normalize-lyrics", "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    for text in ("[ar:]", "[ti:]", "[lr:]", "[hash:]", "[offset:]", "[length:]", "[xtrack:7]"):
        assert text in result.output, text
