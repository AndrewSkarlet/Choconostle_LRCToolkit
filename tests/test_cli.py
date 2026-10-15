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
