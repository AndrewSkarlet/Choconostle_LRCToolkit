"""
Interfaz (rc3): formato común de las barras, indicador de --export y la
pregunta «¿Guardar la lista completa?» al terminar una simulación.
"""

import io
import re
from datetime import datetime
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from builders import make_flac
from choconostle import cli
from choconostle.cli import app

runner = CliRunner()


def frames_of(buffer: io.StringIO) -> list[str]:
    frames = [re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", frame).rstrip("\r\n")
              for frame in re.split(r"\r\x1b\[2K", buffer.getvalue())[1:]]
    return [frame.rstrip() for frame in frames if frame.strip()]


@pytest.mark.parametrize("compact", [False, True])
def test_bar_format_step_count_elapsed(compact):
    buffer = io.StringIO()
    progress = cli._RunProgress(Console(file=buffer, force_terminal=True, width=100, color_system=None),
                                enabled=True, compact=compact)
    progress.start_apply(4468)
    progress.tick(1234, "Artista/Álbum/01 canción.lrc")
    progress.progress.refresh()
    progress.step("Verificando audio", "02 otra.flac")
    progress.progress.refresh()
    progress.step("")
    progress.progress.refresh()
    progress.stop()
    frames = frames_of(buffer)
    assert any(re.search(r"Aplicando 1234/4468 · 0:00:0\d", frame) for frame in frames), frames
    assert any("Verificando audio 1234/4468 ·" in frame for frame in frames), frames
    assert not any("restante" in frame for frame in frames)
    names = any("01 canción.lrc" in frame for frame in frames)
    assert names is (not compact)  # el nombre del archivo solo en la vista completa
    assert not any("Artista/" in frame for frame in frames)


def test_every_bar_uses_the_same_columns():
    for compact in (False, True):
        gallery = cli._GalleryProgress(Console(file=io.StringIO(), force_terminal=True), enabled=True,
                                       compact=compact)
        gallery.start("Creando .nomedia", 3)
        run = cli._RunProgress(Console(file=io.StringIO(), force_terminal=True), enabled=True, compact=compact)
        run.start("Revirtiendo", 3)
        kinds = [[type(column).__name__ for column in bar.progress.columns] for bar in (gallery, run)]
        assert kinds[0] == kinds[1] and "TimeRemainingColumn" not in kinds[0]
        gallery.stop()
        run.stop()


def test_export_shows_indicator_while_writing(tmp_path):
    buffer = io.StringIO()
    errors = Console(file=buffer, force_terminal=True, color_system=None)
    target = tmp_path / "lista.txt"
    seen = []

    def render(console):
        seen.append(buffer.getvalue())
        console.print("contenido")
    assert cli._export(cli.View(export=target), errors, render) == target
    assert seen and "Guardando la lista en" in buffer.getvalue()  # se dibuja mientras escribe y se borra
    assert target.read_text(encoding="utf-8").strip() == "contenido"


# --------------------------------------------------------------------------
# Ruta por defecto de la lista
# --------------------------------------------------------------------------

NOW = datetime(2026, 11, 11, 10, 20, 30)


def test_default_export_path_termux_download(tmp_path):
    home = tmp_path / "home"
    download = home / "storage" / "shared" / "Download"
    download.mkdir(parents=True)
    path = cli.default_export_path("normalize-lyrics", tmp_path / "lib", home=home, termux=True, now=NOW)
    assert path == download / "choconostle_normalize-lyrics_2026-11-11_10-20-30.txt"


def test_default_export_path_home_without_shared_storage_or_outside_termux(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    assert cli.default_export_path("revert", None, home=home, termux=True, now=NOW).parent == home
    (home / "storage" / "shared" / "Download").mkdir(parents=True)
    assert cli.default_export_path("revert", None, home=home, termux=False, now=NOW).parent == home


def test_default_export_path_never_inside_library_or_current_folder(tmp_path, monkeypatch):
    import tempfile
    home = tmp_path / "home"
    (home / "Music").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    # La biblioteca es la carpeta personal (o la contiene): se usa la carpeta temporal.
    path = cli.default_export_path("fix-gallery", home, home=home, termux=False, now=NOW)
    assert path.parent == Path(tempfile.gettempdir())
    path = cli.default_export_path("fix-gallery", home / "Music", home=home, termux=False, now=NOW)
    assert path.parent == home and path.parent != Path.cwd()


# --------------------------------------------------------------------------
# «¿Guardar la lista completa? (s/N)»
# --------------------------------------------------------------------------

def _library(tmp_path):
    library = tmp_path / "lib"
    make_flac(library / "a" / "01.flac", tags={"TITLE": "Uno"})
    (library / "a" / "01.lrc").write_text("[ar:x]\n[00:01.00]a\n[00:02.00]b\n[00:03.00]c\n", encoding="utf-8")
    return library


@pytest.fixture
def interactive(monkeypatch, tmp_path):
    target = tmp_path / "out" / "lista.txt"
    target.parent.mkdir()
    monkeypatch.setattr(cli, "_interactive_io", lambda: True)
    monkeypatch.setattr(cli, "default_export_path", lambda command, library=None: target)
    return target


@pytest.mark.parametrize("args", [["normalize-lyrics", "--strip-headers"], ["normalize-lyrics", "--strip-headers",
                                                                           "--diff"],
                                  ["convert-lyrics", "--eol", "crlf"], ["fix-gallery"],
                                  ["clean-backups", "--older-than", "1"]])
def test_asks_after_simulation_and_saves_with_default_path(tmp_path, interactive, args):
    library = _library(tmp_path)
    (library / "a" / "cover.jpg").write_bytes(b"\xff\xd8\xff")
    result = runner.invoke(app, [args[0], str(library), "--no-progress", *args[1:]], input="s\n\n")
    assert result.exit_code == 0, result.output
    assert "¿Guardar la lista completa? (s/N)" in result.output
    assert interactive.is_file() and str(interactive) in result.output
    assert "Tiempo total" in interactive.read_text(encoding="utf-8")


def test_answer_no_saves_nothing(tmp_path, interactive):
    library = _library(tmp_path)
    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--no-progress"], input="\n")
    assert result.exit_code == 0 and "¿Guardar" in result.output and not interactive.exists()


def test_custom_path_is_used(tmp_path, interactive):
    library = _library(tmp_path)
    custom = tmp_path / "otra.txt"
    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--no-progress"],
                           input=f"s\n{custom}\n")
    assert result.exit_code == 0 and custom.is_file() and not interactive.exists()


def test_no_question_with_no_input_export_apply_or_without_terminal(tmp_path, interactive, monkeypatch):
    library = _library(tmp_path)
    base = ["normalize-lyrics", str(library), "--strip-headers", "--no-progress"]
    for extra in (["--no-input"], ["--export", str(tmp_path / "e.txt")]):
        result = runner.invoke(app, [*base, *extra], input="s\n\n")
        assert result.exit_code == 0 and "¿Guardar" not in result.output, extra
    monkeypatch.setattr(cli, "_interactive_io", lambda: False)
    result = runner.invoke(app, base, input="s\n\n")
    assert result.exit_code == 0 and "¿Guardar" not in result.output
    monkeypatch.setattr(cli, "_interactive_io", lambda: True)
    result = runner.invoke(app, [*base, "--apply"], input="s\n\n")
    assert result.exit_code == 0 and "¿Guardar" not in result.output
    assert not interactive.exists()
