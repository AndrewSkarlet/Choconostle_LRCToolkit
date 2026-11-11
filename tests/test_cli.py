import json
import pytest

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


# --- Banner de bienvenida ----------------------------------------------------

import subprocess
import sys

from choconostle import cli
from choconostle.config import APP_CODENAME, APP_NAME


def _banner_check(output: str) -> None:
    lines = [line for line in output.splitlines() if line.startswith(("+", "|"))]
    assert lines, output
    assert all(line.isascii() and len(line) <= 40 for line in lines)
    text = " ".join(line.strip("|+- ") for line in lines)
    assert APP_NAME in text and APP_VERSION in text and f"({APP_CODENAME})" in text
    for name in ["scan", "normalize-lyrics", "convert-lyrics", "revert", "recover", "clean-backups",
                 "fix-gallery", "welcome", "version"]:
        assert f"| {name}" in output.replace("|   ", "| "), name
    assert "--apply" in text


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.delenv(cli.BANNER_ENV, raising=False)


def test_banner_without_arguments(tty):
    result = runner.invoke(app, [])
    assert result.exit_code == 0, result.output
    _banner_check(result.output)
    result = runner.invoke(app, ["welcome"])
    assert result.exit_code == 0, result.output
    _banner_check(result.output)


def test_banner_hidden_with_option_or_variable(tty):
    for args, env in [(["--no-banner"], {}), (["--no-banner", "welcome"], {}), (["welcome", "--no-banner"], {}),
                      ([], {cli.BANNER_ENV: "1"})]:
        result = runner.invoke(app, args, env=env)
        assert result.exit_code == 0, result.output
        assert "+------" not in result.output
        assert "Usage" in result.output  # muestra la ayuda en su lugar


def test_banner_not_in_other_commands(tty):
    result = runner.invoke(app, ["version"])
    assert "+------" not in result.output


def test_banner_not_shown_when_redirected():
    # Salida real redirigida a un tubo (no es una terminal interactiva).
    import os
    from pathlib import Path
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = {**os.environ, "COLUMNS": "100", "PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", "")}
    env.pop(cli.BANNER_ENV, None)
    result = subprocess.run([sys.executable, "-m", "choconostle"], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert "+------" not in result.stdout
    assert "Usage" in result.stdout


def test_banner_lines_ascii_and_narrow():
    assert all(line.isascii() and len(line) <= 40 for line in cli.banner_lines())


def test_banner_lists_every_command_in_help():
    """El banner lista todos los comandos que muestra la ayuda."""
    import typer.main
    names = set(typer.main.get_command(app).commands)
    assert names == set(cli.BANNER_COMMANDS)


# --- Línea de progreso sin restos ---------------------------------------------

@pytest.mark.parametrize("width", [60, 80, 120])
def test_progress_line_never_leaves_leftovers(width):
    """
    Cada actualización ocupa el ancho completo (rellena con espacios) y no se
    parte en dos filas, así que un nombre corto tapa del todo al anterior aunque
    la consola no borre la línea (algunas consolas de Windows).
    """
    import io
    import re

    from rich.console import Console

    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=True, width=width, color_system=None)
    progress = cli._RunProgress(console, enabled=True)
    progress.start("Revirtiendo", 30)
    long_name = "03_cabeceras/" + "nombre muy largo " * 8 + "Before After).lrc"
    progress.tick(0, long_name)
    progress.progress.refresh()
    progress.tick(1, "x.lrc")
    progress.progress.refresh()
    progress.stop()
    frames = [re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", frame).rstrip("\r\n")
              for frame in re.split(r"\r\x1b\[2K", buffer.getvalue())[1:]]
    frames = [frame for frame in frames if frame]
    assert len(frames) >= 2
    for frame in frames:
        assert "\n" not in frame and len(frame) == width, repr(frame)
    last = frames[-1]
    assert "Before" not in last and "muy largo" not in last
    assert ("x.lrc" if width >= 80 else "x") in last


def test_progress_shows_only_file_name():
    import io

    from rich.console import Console

    console = Console(file=io.StringIO(), force_terminal=True, width=200, color_system=None)
    progress = cli._RunProgress(console, enabled=True)
    progress.start("Revirtiendo", 1)
    progress.tick(0, "Artista\\Álbum/01 canción.lrc")
    assert progress.progress.tasks[0].fields["name"] == "01 canción.lrc"
    progress.stop()


def test_progress_disabled_does_nothing():
    import io

    from rich.console import Console

    buffer = io.StringIO()
    progress = cli._RunProgress(Console(file=buffer, force_terminal=True), enabled=False)
    progress.start("Revirtiendo", 3)
    progress.tick(1, "a.lrc")
    progress.step("verificando")
    progress.stop()
    assert buffer.getvalue() == ""


def test_elapsed_time_in_summaries_and_log(tmp_path):
    from choconostle.config import BACKUP_DIR_NAME
    library = _library_with_headers(tmp_path)
    for args in (["normalize-lyrics", "--strip-headers", "--diff"], ["convert-lyrics", "--eol", "crlf"],
                 ["fix-gallery"]):
        result = runner.invoke(app, [args[0], str(library), "--no-progress", *args[1:]])
        assert result.exit_code == 0, result.output
        assert "Tiempo total: " in result.output, args

    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--apply", "--no-progress"])
    assert result.exit_code == 0, result.output
    assert "Tiempo total: " in result.output
    folder = next((library / BACKUP_DIR_NAME).iterdir())
    assert "Tiempo total: " in (folder / "registro.txt").read_text(encoding="utf-8")

    result = runner.invoke(app, ["revert", str(folder), "--no-progress"])
    assert result.exit_code == 0, result.output
    assert "Tiempo total: " in result.output
    log = (folder / "registro.txt").read_text(encoding="utf-8")
    assert log.count("Tiempo total: ") == 2 and "(revert del " in log
    assert "Tiempo total: " in next(folder.glob("revert_*.txt")).read_text(encoding="utf-8")


def test_elapsed_time_also_when_ending_with_error(tmp_path):
    library = _library_with_headers(tmp_path)
    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--only", "no-existe",
                                 "--no-progress"])
    assert result.exit_code == 2
    assert result.output.count("Tiempo total: ") == 1


def test_format_elapsed():
    from choconostle.utils import format_elapsed
    assert format_elapsed(2.34) == "2,3 s"
    assert format_elapsed(125) == "2 min 05 s"
    assert format_elapsed(3725) == "1 h 02 min 05 s"


# --------------------------------------------------------------------------
# Vista compacta (--compact, --full, CHOCONOSTLE_COMPACT, ancho < 70) y --export
# --------------------------------------------------------------------------

@pytest.fixture
def terminal(monkeypatch):
    """Simula el ancho de la terminal (None: no se puede leer, como con la salida redirigida)."""
    import os
    from choconostle import cli
    monkeypatch.delenv("COLUMNS", raising=False)
    monkeypatch.delenv(cli.COMPACT_ENV, raising=False)

    def set_width(width):
        def size(*_args):
            if width is None:
                raise OSError(6, "The handle is invalid")  # WinError 6 en Windows, ENOTTY en posix
            return os.terminal_size((width, 24))
        monkeypatch.setattr(os, "get_terminal_size", size)
    return set_width


def test_view_choice(terminal, monkeypatch, paths_mode):
    from choconostle.cli import COMPACT_ENV, choose_compact
    terminal(69)
    assert choose_compact(False, False) is True
    assert choose_compact(False, True) is False
    terminal(70)
    assert choose_compact(False, False) is False
    assert choose_compact(True, False) is True
    terminal(None)  # ancho ilegible: vista completa
    assert choose_compact(False, False) is False
    monkeypatch.setenv(COMPACT_ENV, "1")
    assert choose_compact(False, False) is True
    assert choose_compact(False, True) is False
    terminal(200)
    assert choose_compact(False, False) is True
    monkeypatch.setenv(COMPACT_ENV, "0")
    terminal(40)
    assert choose_compact(False, False) is False
    monkeypatch.delenv(COMPACT_ENV)
    monkeypatch.setenv("COLUMNS", "60")
    assert choose_compact(False, False) is True
    with pytest.raises(ValueError):
        choose_compact(True, True)


def test_compact_and_full_together_is_an_error(tmp_path):
    library = _library_with_headers(tmp_path)
    for command in (["normalize-lyrics", str(library), "--strip-headers"], ["convert-lyrics", str(library)],
                    ["revert", str(library), "--latest"], ["clean-backups", str(library), "--older-than", "1"],
                    ["fix-gallery", str(library)]):
        result = runner.invoke(app, [*command, "--compact", "--full", "--no-progress"])
        assert result.exit_code == 2 and "no se pueden usar juntas" in result.output, command


def _library_with_unknown(tmp_path):
    library = _library_with_headers(tmp_path)
    (library / "a" / "02.lrc").write_text("[xtrack:7]\n[ar:x]\n[00:01.00]a\n[00:02.00]b\n[00:03.00]c\n",
                                          encoding="utf-8")
    return library


def test_compact_simulation_apply_and_revert(tmp_path):
    from choconostle.config import BACKUP_DIR_NAME
    library = _library_with_unknown(tmp_path)
    env = {"CHOCONOSTLE_COMPACT": "1"}
    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--no-progress"], env=env)
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Cambios que se aplicarían" not in out and "a/02.lrc" not in out
    assert "Resumen (" in out and "a modificar" in out and "con desconocidos" in out
    assert "--export ARCHIVO" in " ".join(out.split()) and "Tiempo total: " in out  # el texto puede partirse
    assert "Para aplicar, repite el comando con --apply. Antes se guardará un respaldo en:" in out
    assert str(library / BACKUP_DIR_NAME) in out.splitlines()

    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--apply", "--no-progress"],
                           env=env)
    assert result.exit_code == 0, result.output
    folder = next((library / BACKUP_DIR_NAME).iterdir())
    lines = result.output.splitlines()
    assert "Respaldo guardado en:" in lines and str(folder) in lines
    assert f'choconostle revert "{folder}"' in lines  # comando para copiar, en una sola línea

    (library / "a" / "01.lrc").write_text("cambiado después\n", encoding="utf-8")
    result = runner.invoke(app, ["revert", str(folder), "--no-progress"], env=env)
    assert result.exit_code == 1
    assert any(line.strip().startswith("a/01.lrc: ") for line in result.output.splitlines())  # conflicto completo
    assert "Resumen: " in result.output and "Tiempo total: " in result.output and str(folder) in result.output


def test_full_view_keeps_lists_and_adds_final_block(tmp_path):
    library = _library_with_unknown(tmp_path)
    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--no-progress", "--full"],
                           env={"CHOCONOSTLE_COMPACT": "1"})
    assert result.exit_code == 0, result.output
    assert "Cambios que se aplicarían" in result.output and "a/02.lrc" in result.output
    tail = result.output[result.output.index("Resumen ("):]
    assert "Tiempo total: " in tail and "Para aplicar, repite el comando con --apply." in tail


def test_export_in_simulation(tmp_path):
    library = _library_with_unknown(tmp_path)
    target = tmp_path / "lista.txt"
    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--no-progress",
                                 "--compact", "--export", str(target)])
    assert result.exit_code == 0, result.output
    assert str(target) in result.output.splitlines()
    text = target.read_text(encoding="utf-8")
    assert "a/01.flac" in text and "01.lrc" in text and "a/02.lrc" in text  # archivos
    assert "[xtrack:]" in text  # cabeceras desconocidas
    assert "- [ar:x]" in text or "-[ar:x]" in text  # diferencias
    assert not (library / "a" / "01.lrc").read_text(encoding="utf-8").startswith("[00")  # no se modificó

    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--export",
                                 str(tmp_path / "no-existe" / "x.txt")])
    assert result.exit_code == 2


def test_compact_clean_backups_and_fix_gallery(tmp_path):
    library = _library_with_headers(tmp_path)
    (library / "a" / "cover.jpg").write_bytes(b"\xff\xd8\xff")
    env = {"CHOCONOSTLE_COMPACT": "1"}
    result = runner.invoke(app, ["fix-gallery", str(library), "--no-progress"], env=env)
    assert result.exit_code == 0, result.output
    assert "Se crearían" not in result.output and "Resumen: " in result.output
    assert "Tiempo total: " in result.output and "(se guardará en):" in result.output
    assert "Para aplicarlo, repite el comando con --apply." in result.output
    result = runner.invoke(app, ["clean-backups", str(library), "--older-than", "1", "--no-progress"], env=env)
    assert result.exit_code == 0, result.output
    assert "Resumen: " in result.output and "Tiempo total: " in result.output and "Respaldos en:" in result.output


@pytest.mark.parametrize("width", [40, 69])
def test_compact_progress_is_one_short_line(width):
    import io
    import re

    from rich.console import Console

    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=True, width=width, color_system=None)
    progress = cli._RunProgress(console, enabled=True, compact=True)
    progress.start_apply(340)
    progress.tick(12, "03_cabeceras/" + "nombre muy largo " * 8 + ".lrc")
    progress.step("Verificando audio", "x.flac")
    progress.progress.refresh()
    progress.stop()
    frames = [re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", frame).rstrip("\r\n")
              for frame in re.split(r"\r\x1b\[2K", buffer.getvalue())[1:]]
    frames = [frame.rstrip() for frame in frames if frame.strip()]
    assert frames
    for frame in frames:
        assert "\n" not in frame and len(frame) <= 40, repr(frame)
        assert "/340 · 0:00:0" in frame and "restante" not in frame and "muy largo" not in frame and "x.flac" not in frame


def test_compact_progress_respects_no_progress_and_redirection(tmp_path):
    import io

    from rich.console import Console

    buffer = io.StringIO()
    progress = cli._RunProgress(Console(file=buffer, force_terminal=True), enabled=False, compact=True)
    progress.start_apply(3)
    progress.tick(1, "a.lrc")
    progress.stop()
    assert buffer.getvalue() == ""
    # Salida redirigida (no es una terminal): el comando no anima el progreso aunque no haya --no-progress.
    library = _library_with_headers(tmp_path)
    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--compact"])
    assert result.exit_code == 0 and "Planificando" not in result.output
