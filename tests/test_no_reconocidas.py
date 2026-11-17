"""
Carpetas de ChoconostleLRCTool_back que no son respaldos de este programa
(por ejemplo, de versiones no públicas con manifiesto.json): clean-backups
las lista con su ruta y una nota para borrarlas a mano, y nunca las borra;
revert y recover no las aceptan.
"""

import json
import os
import time

import pytest
from typer.testing import CliRunner

from builders import make_flac
from choconostle.cli import app
from choconostle.config import BACKUP_DIR_NAME

runner = CliRunner()


@pytest.fixture
def library(tmp_path):
    lib = tmp_path / "lib"
    make_flac(lib / "a" / "01.flac", tags={"TITLE": "Uno"})
    base = lib / BACKUP_DIR_NAME
    old = base / "2020-01-01_00-00-00"
    old.mkdir(parents=True)
    (old / "manifiesto.json").write_text(json.dumps({"manifest_version": 1, "created_at": "2020-01-01T00:00:00",
                                                     "items": []}), encoding="utf-8")
    other = base / "copias varias"
    other.mkdir()
    (other / "nota.txt").write_text("x", encoding="utf-8")
    past = time.time() - 400 * 86400
    for folder in (old, other):
        os.utime(folder, (past, past))
    return lib, old, other


@pytest.mark.parametrize("view", ["--full", "--compact"])
@pytest.mark.parametrize("apply", [False, True])
def test_clean_backups_lists_unrecognized_and_never_deletes_them(library, view, apply):
    lib, old, other = library
    args = ["clean-backups", str(lib), "--older-than", "0", "--no-progress", "--no-input", view]
    result = runner.invoke(app, args + (["--apply"] if apply else []), env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert "Carpetas no reconocidas (2)" in result.output and "puedes borrarlas a mano" in result.output
    assert f"  {old}" in lines and f"  {other}" in lines  # ruta completa, en una línea para copiar
    assert "versión antigua (manifiesto.json)" in result.output
    assert "no reconocidas 2" in result.output
    assert old.is_dir() and other.is_dir()


def test_revert_and_recover_reject_old_manifest_folders(library):
    _lib, old, _other = library
    for command in (["revert", str(old), "--no-progress", "--no-input"], ["recover", str(old)]):
        result = runner.invoke(app, command)
        assert result.exit_code == 2, result.output
        assert "No se encontró estado.json" in " ".join(result.output.split())
