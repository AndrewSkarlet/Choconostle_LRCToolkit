"""
Pruebas de la etapa ⑤: lo que faltaba de la tabla de cobertura
(tests/COBERTURA.md) para convert-lyrics, revert y clean-backups.

Todo se ejecuta en los modos "posix" y "windows" (fixture paths_mode o el
parámetro `paths` del simulador Unplug) sobre copias de la biblioteca de
tools/generar_casos.py.
"""

import errno
import os
import shutil
from collections import namedtuple
from pathlib import Path

import pytest

from choconostle import backup
from choconostle import run as runs
from choconostle.cli import app
from choconostle.config import BACKUP_DIR_NAME
from choconostle.converter import LyricsConverter
from choconostle.rawtags import writer
from test_run import (
    LRC, ONLY, PATH_MODES, TARGETS, Crash, Unplug, _age, crash_at, eio, files, runner, start, win_error,
)

ONLY_ARGS = sum((["--only", folder] for folder in ONLY), [])
CONVERT_ARGS = ["--replace-char", "ó=o", "--allow-full-rewrite"]
CONVERT_TARGETS = {kind: TARGETS[kind] for kind in ("lrc", "mp3", "flac", "opus")}


def start_convert(root: Path):
    converter = LyricsConverter(replacements=[("ó", "o")], allow_full_rewrite=True)
    execution = runs.Run.create(root, "convert-lyrics", dict(converter.options(), verify="auto"))
    runs.plan_library(execution, converter, root, ONLY)
    return converter, execution


def finish(root: Path, processor, execution):
    execution = runs.Run(execution.folder)
    assert runs.resume_check(execution, root, processor) == []
    summary = runs.apply_run(execution, processor, root, resume=True)
    assert summary.stopped is None, summary.stopped
    return execution


def cli(*args):
    args = [*map(str, args)]
    if args[0] in ("normalize-lyrics", "convert-lyrics"):
        args.append("--no-progress")
    return runner.invoke(app, args, env={"COLUMNS": "220"})


def convert_cli(root, *extra):
    return cli("convert-lyrics", root, *CONVERT_ARGS, "--apply", *ONLY_ARGS, *extra)


def only_folder(root: Path) -> Path:
    return next(folder for folder in (root / BACKUP_DIR_NAME).iterdir() if folder.is_dir())


def failing_on_call(real, number: int, error):
    """Envuelve una función para que la llamada número `number` falle con `error()`."""
    calls = {"n": 0}

    def wrapper(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == number:
            raise error()
        return real(*args, **kwargs)
    return wrapper


def no_space():
    return OSError(errno.ENOSPC, "No space left on device (simulado)")


SPACE_ERRORS = [no_space, lambda: win_error(112)]
SPACE_IDS = ["ENOSPC", "WinError112"]


@pytest.fixture(scope="module")
def conv_reference(casos, tmp_path_factory):
    root = tmp_path_factory.mktemp("convref5") / "lib"
    shutil.copytree(casos, root)
    converter, execution = start_convert(root)
    summary = runs.apply_run(execution, converter, root)
    assert summary.stopped is None and summary.failed == 0
    return files(root)


# --------------------------------------------------------------------------
# convert-lyrics
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kind", list(CONVERT_TARGETS))
@pytest.mark.parametrize("step", ["start", "backup", "intent", "written", "done"])
def test_convert_crash_at_each_step(biblioteca, conv_reference, original, monkeypatch, paths_mode, kind, step):
    converter, execution = start_convert(biblioteca)
    fired = crash_at(monkeypatch, step, CONVERT_TARGETS[kind])
    with pytest.raises(Crash):
        runs.apply_run(execution, converter, biblioteca)
    assert fired["done"]
    monkeypatch.undo()
    finish(biblioteca, converter, execution)
    assert files(biblioteca) == conv_reference
    backup.revert(execution.folder)
    assert files(biblioteca) == original


@pytest.mark.parametrize("kind", ["mp3", "flac", "m4a"])
def test_convert_crash_mid_byte_write(biblioteca, conv_reference, original, monkeypatch, paths_mode, kind):
    converter, execution = start_convert(biblioteca)
    target = biblioteca / TARGETS[kind]
    real = writer._write

    def torn(handle, data):
        if Path(handle.name).name == target.name:
            handle.write(data[:10])
            raise Crash()
        real(handle, data)
    monkeypatch.setattr(writer, "_write", torn)
    with pytest.raises(Crash):
        runs.apply_run(execution, converter, biblioteca)
    monkeypatch.undo()
    finish(biblioteca, converter, execution)
    assert files(biblioteca) == conv_reference
    backup.revert(execution.folder)
    assert files(biblioteca) == original


@pytest.mark.parametrize("paths", PATH_MODES)
def test_convert_drive_letter_disappears(biblioteca, conv_reference, monkeypatch, paths):
    converter, execution = start_convert(biblioteca)
    Unplug(monkeypatch, biblioteca, after=3, error=lambda: win_error(3), paths=paths)
    summary = runs.apply_run(execution, converter, biblioteca)
    assert summary.stop_kind == "device"
    monkeypatch.undo()
    finish(biblioteca, converter, execution)
    assert files(biblioteca) == conv_reference


def test_convert_access_denied_is_not_a_disconnection(biblioteca, monkeypatch, paths_mode):
    monkeypatch.setattr(runs, "write_file_atomic", failing_on_call(runs.write_file_atomic, 2, lambda: win_error(5)))
    result = convert_cli(biblioteca)
    assert result.exit_code == 1, result.output
    execution = runs.Run(only_folder(biblioteca))
    assert execution.phase == runs.STATE_COMPLETED
    failed = [item for item in execution.manifest["items"] if item["status"] == "failed"]
    assert len(failed) == 1 and "WinError 5" in failed[0]["error"]


def test_convert_no_space_before_applying(biblioteca, conv_reference, original, monkeypatch, paths_mode):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(runs.shutil, "disk_usage", lambda _path: usage(10**9, 10**9 - 1000, 1000))
    result = convert_cli(biblioteca)
    assert result.exit_code == 2 and "Espacio libre insuficiente" in result.output
    assert "choconostle convert-lyrics" in result.output and "--resume" in result.output
    assert files(biblioteca) == original
    monkeypatch.undo()
    result = cli("convert-lyrics", biblioteca, "--resume", only_folder(biblioteca))
    assert result.exit_code == 0, result.output
    assert files(biblioteca) == conv_reference


@pytest.mark.parametrize("command", ["normalize-lyrics", "convert-lyrics"])
@pytest.mark.parametrize("error", SPACE_ERRORS, ids=SPACE_IDS)
def test_space_runs_out_mid_run(biblioteca, reference, conv_reference, monkeypatch, paths_mode, command, error):
    """Sin espacio a mitad (ENOSPC en Linux, WinError 112 en Windows), en un .lrc y en un FLAC."""
    processor, execution = start(biblioteca) if command == "normalize-lyrics" else start_convert(biblioteca)
    expected = reference if command == "normalize-lyrics" else conv_reference
    monkeypatch.setattr(runs, "write_file_atomic", failing_on_call(runs.write_file_atomic, 3, error))
    summary = runs.apply_run(execution, processor, biblioteca)
    assert summary.stop_kind == "space"
    monkeypatch.undo()
    # Ahora a mitad de una escritura de bytes (FLAC).
    target = biblioteca / TARGETS["flac"]
    real = writer._write
    fired = {"n": 0}

    def full(handle, data):
        if Path(handle.name).name == target.name and not fired["n"]:
            fired["n"] = 1
            handle.write(data[:10])
            raise error()
        real(handle, data)
    monkeypatch.setattr(writer, "_write", full)
    execution = runs.Run(execution.folder)
    assert runs.resume_check(execution, biblioteca, processor) == []
    summary = runs.apply_run(execution, processor, biblioteca, resume=True)
    assert summary.stop_kind == "space" and fired["n"]
    monkeypatch.undo()
    finish(biblioteca, processor, execution)
    assert files(biblioteca) == expected


def test_convert_files_modified_between_plan_and_apply(biblioteca, conv_reference, paths_mode):
    converter, execution = start_convert(biblioteca)
    lrc = biblioteca / LRC
    lrc.write_bytes(lrc.read_bytes() + "[00:20.00]Línea agregada por otro programa\n".encode())
    flac = biblioteca / TARGETS["flac"]
    data = bytearray(flac.read_bytes())
    data[-1] ^= 0xFF
    flac.write_bytes(bytes(data))
    modified = {LRC: lrc.read_bytes(), TARGETS["flac"]: flac.read_bytes()}
    summary = runs.apply_run(execution, converter, biblioteca)
    assert summary.failed == 2 and summary.stopped is None
    items = {item["path"]: item for item in execution.manifest["items"]}
    for path in modified:
        assert items[path]["status"] == "failed" and "cambió" in items[path]["error"]
    for path, content in files(biblioteca).items():
        assert content == modified.get(path, conv_reference[path]), path


def test_convert_resume_refuses_incomplete_or_foreign_backup(biblioteca, tmp_path, monkeypatch, paths_mode):
    converter, execution = start_convert(biblioteca)
    crash_at(monkeypatch, "intent", LRC)
    with pytest.raises(Crash):
        runs.apply_run(execution, converter, biblioteca)
    monkeypatch.undo()
    execution = runs.Run(execution.folder)
    intents, _done = execution.outcome()
    copy = next(event["copy"] for event in intents.values() if "copy" in event)
    (execution.folder / copy).unlink()
    before = files(biblioteca)
    result = cli("convert-lyrics", biblioteca, "--resume", execution.folder)
    assert result.exit_code == 2 and "falta la copia de respaldo" in result.output
    assert files(biblioteca) == before
    other = tmp_path / "otra biblioteca"
    other.mkdir()
    result = cli("convert-lyrics", other, "--resume", execution.folder)
    assert result.exit_code == 2 and "no pertenece a esta biblioteca" in result.output
    # Completada: nada que reanudar.
    done_converter, done_run = start_convert(tmp_path / "x" if False else biblioteca)
    shutil.rmtree(execution.folder)  # quitar la ejecución dañada
    runs.apply_run(done_run, done_converter, biblioteca)
    result = cli("convert-lyrics", biblioteca, "--resume", done_run.folder)
    assert result.exit_code == 2 and "nada que reanudar" in result.output


# --------------------------------------------------------------------------
# revert
# --------------------------------------------------------------------------

@pytest.fixture
def applied(biblioteca):
    """Biblioteca con normalize-lyrics aplicado (subconjunto ONLY)."""
    normalizer, execution = start(biblioteca)
    summary = runs.apply_run(execution, normalizer, biblioteca)
    assert summary.failed == 0 and summary.stopped is None
    return biblioteca, execution.folder


@pytest.mark.parametrize("kind", ["lrc", "mp3", "flac"])
def test_revert_interrupted_then_rerun(applied, original, monkeypatch, paths_mode, kind):
    root, folder = applied
    target = root / TARGETS[kind]
    if kind == "lrc":
        def crash(path, data):
            if Path(path).name == target.name:
                raise Crash()
            return real_atomic(path, data)
        real_atomic = backup.write_file_atomic
        monkeypatch.setattr(backup, "write_file_atomic", crash)
    else:
        real = writer._write

        def crash(handle, data):
            if Path(handle.name).name == target.name:
                handle.write(data[:10])
                raise Crash()
            real(handle, data)
        monkeypatch.setattr(writer, "_write", crash)
    with pytest.raises(Crash):
        backup.revert(folder)
    monkeypatch.undo()
    results = backup.revert(folder)  # recupera lo que quedó a medias y termina
    assert {r.status for r in results} <= {backup.REVERT_RESTORED, backup.REVERT_ALREADY}
    assert files(root) == original


@pytest.mark.parametrize("paths", PATH_MODES)
@pytest.mark.parametrize("error", [eio, lambda: win_error(1167), lambda: win_error(3)],
                         ids=["EIO", "WinError1167", "WinError3"])
def test_revert_disconnection_then_rerun(applied, original, monkeypatch, error, paths):
    root, folder = applied
    unplug = Unplug(monkeypatch, root, after=4, error=error, paths=paths)
    result = cli("revert", folder)
    assert unplug.unplugged
    assert result.exit_code == 3, result.output
    assert "Vuelve a ejecutar" in result.output and f'choconostle revert "{folder}"' in result.output.splitlines()
    monkeypatch.undo()
    result = cli("revert", folder)
    assert result.exit_code == 0, result.output
    assert files(root) == original


def test_revert_access_denied_only_fails_that_file(applied, original, monkeypatch, paths_mode):
    root, folder = applied
    monkeypatch.setattr(backup, "write_file_atomic",
                        failing_on_call(backup.write_file_atomic, 2, lambda: win_error(5)))
    result = cli("revert", folder)
    assert result.exit_code == 1, result.output
    assert "ERROR" in result.output or "Errores" in result.output
    monkeypatch.undo()
    result = cli("revert", folder)
    assert result.exit_code == 0, result.output
    assert files(root) == original


@pytest.mark.parametrize("error", SPACE_ERRORS, ids=SPACE_IDS)
def test_revert_space(applied, original, monkeypatch, paths_mode, error):
    root, folder = applied
    after_apply = files(root)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(runs.shutil, "disk_usage", lambda _path: usage(10**9, 10**9 - 1000, 1000))
    result = cli("revert", folder)
    assert result.exit_code == 2 and "Espacio libre insuficiente para revertir" in result.output
    assert files(root) == after_apply  # no se tocó nada
    monkeypatch.undo()
    monkeypatch.setattr(backup, "write_file_atomic", failing_on_call(backup.write_file_atomic, 3, error))
    result = cli("revert", folder)
    assert result.exit_code == 3 and "Vuelve a ejecutar" in result.output, result.output
    monkeypatch.undo()
    assert cli("revert", folder).exit_code == 0
    assert files(root) == original


def test_revert_conflict_after_convert(biblioteca, original, paths_mode):
    converter, execution = start_convert(biblioteca)
    runs.apply_run(execution, converter, biblioteca)
    lrc = biblioteca / LRC
    lrc.write_bytes(b"editado a mano\n")
    from mutagen.flac import FLAC
    audio = FLAC(biblioteca / TARGETS["flac"])
    audio["TITLE"] = "Editado"
    audio.save()
    edited = {LRC: lrc.read_bytes(), TARGETS["flac"]: (biblioteca / TARGETS["flac"]).read_bytes()}
    results = backup.revert(execution.folder)
    conflicts = {r.item["path"] for r in results if r.status == backup.REVERT_CONFLICT}
    assert conflicts == set(edited)
    for path, content in files(biblioteca).items():
        assert content == edited.get(path, original[path]), path


def test_revert_with_incomplete_backup(applied, original, paths_mode):
    root, folder = applied
    execution = runs.Run(folder)
    intents, _done = execution.outcome()
    copy = next(e for e in intents.values() if "copy" in e and Path(LRC).name in e["copy"])
    (folder / copy["copy"]).unlink()
    flac_patches = next(e for e in intents.values()
                        if e.get("patches") and Path(TARGETS["flac"]).name in e["patches"])
    (folder / flac_patches["patches"]).unlink()
    result = cli("revert", folder)
    assert result.exit_code == 1, result.output
    restored = files(root)
    for path, content in restored.items():
        if path in (LRC, TARGETS["flac"]):
            assert content != original[path], path  # no se pudo restaurar: queda aplicado
        else:
            assert content == original[path], path


# --------------------------------------------------------------------------
# clean-backups
# --------------------------------------------------------------------------

def old_runs(root: Path, count: int) -> list[Path]:
    folders = []
    for _ in range(count):
        normalizer, execution = start(root)
        runs.apply_run(execution, normalizer, root)
        backup.revert(execution.folder)
        _age(execution.folder, 40)
        folders.append(execution.folder)
    return folders


def backups(root: Path) -> set[str]:
    return {folder.name for folder in (root / BACKUP_DIR_NAME).iterdir()}


@pytest.mark.parametrize("paths", PATH_MODES)
@pytest.mark.parametrize("error", [eio, lambda: win_error(1167), lambda: win_error(3)],
                         ids=["EIO", "WinError1167", "WinError3"])
def test_clean_backups_disconnection_then_rerun(biblioteca, monkeypatch, error, paths):
    folders = old_runs(biblioteca, 3)
    normalizer, recent = start(biblioteca)  # reciente y reanudable: nunca se borra
    unplug = Unplug(monkeypatch, biblioteca, after=12, error=error, paths=paths, on="delete")
    result = cli("clean-backups", biblioteca, "--older-than", 30, "--apply")
    assert unplug.unplugged
    assert result.exit_code == 3, result.output
    assert "Vuelve a ejecutar" in result.output
    monkeypatch.undo()
    assert recent.folder.name in backups(biblioteca)
    result = cli("clean-backups", biblioteca, "--older-than", 30, "--apply")
    assert result.exit_code == 0, result.output
    assert backups(biblioteca) == {recent.folder.name}  # las 3 viejas, borradas del todo
    assert not any(folder.exists() for folder in folders)


def test_clean_backups_access_denied_and_crash(biblioteca, monkeypatch, paths_mode):
    folders = old_runs(biblioteca, 3)
    locked = folders[1].name
    real_unlink = os.unlink

    def unlink(path, *args, **kwargs):
        if locked in os.fspath(path):
            raise win_error(5)
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(os, "unlink", unlink)
    result = cli("clean-backups", biblioteca, "--older-than", 30, "--apply")
    assert result.exit_code == 1, result.output
    assert "WinError 5" in result.output
    assert not folders[0].exists() and not folders[2].exists()  # las demás se borraron
    monkeypatch.undo()

    # Corte a mitad del borrado: la próxima ejecución termina de borrar.
    more = old_runs(biblioteca, 1)
    calls = {"n": 0}

    def crash_unlink(path, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise Crash()
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(os, "unlink", crash_unlink)
    with pytest.raises(Crash):
        runs.clean_backups(biblioteca, 30, apply=True)
    monkeypatch.undo()
    remove, _keep = runs.clean_backups(biblioteca, 30)
    assert any("borrado interrumpido" in info.state for info in remove)
    result = cli("clean-backups", biblioteca, "--older-than", 30, "--apply")
    assert result.exit_code == 0, result.output
    assert not (biblioteca / BACKUP_DIR_NAME).exists() or backups(biblioteca) == set()
    assert not more[0].exists()


def test_backup_names_never_collide_with_interrupted_deletions(biblioteca, paths_mode):
    """
    Un borrado interrumpido deja <nombre>.borrando y libera <nombre>; una
    ejecución creada en el mismo segundo no debe reutilizarlo, y si ya
    existe otra carpeta con ese nombre, su borrado usa .borrando-2.
    """
    from datetime import datetime
    base = biblioteca / BACKUP_DIR_NAME
    moment = datetime(2020, 1, 1, 12, 0, 0)
    leftover = base / "2020-01-01_12-00-00.borrando"
    (leftover / "originales").mkdir(parents=True)
    (leftover / "originales" / "resto.lrc").write_text("x", encoding="utf-8")
    created = runs.Run.create(biblioteca, "normalize-lyrics", {}, now=moment)
    assert created.folder.name == "2020-01-01_12-00-00_2"

    # Si de todos modos existe una carpeta con el nombre libre (p. ej. de otra versión), no choca.
    clash = base / "2020-01-01_12-00-00"
    (clash / "originales").mkdir(parents=True)
    (clash / "manifiesto.json").write_text('{"manifest_version": 2, "created_at": "2020-01-01T12:00:00", '
                                           '"items": []}', encoding="utf-8")
    remove, _keep = runs.clean_backups(biblioteca, 30, apply=True)
    assert all(info.deleted for info in remove), [(i.folder, i.error) for i in remove]
    assert not leftover.exists() and not clash.exists()
    assert not list(base.glob("*.borrando*"))


# --- Resumen del paro leído del diario -----------------------------------------

def _drive_gone() -> OSError:
    return OSError(errno.ENOENT, "No such file or directory (unidad quitada, simulado)")


@pytest.mark.parametrize("paths", PATH_MODES)
@pytest.mark.parametrize("error", [_drive_gone, lambda: win_error(21), eio],
                         ids=["ENOENT", "WinError21", "EIO"])
def test_stop_summary_matches_diary(biblioteca, monkeypatch, paths, error):
    """
    Tras una desconexión, el resumen «Aplicadas / Con error / Sin aplicar»
    coincide con los eventos done del diario. Antes, en Windows, Path.exists()
    devolvía False con la SD quitada (WinError 21 o ENOENT), el diario se
    leía como vacío y el resumen decía «Aplicadas 0».
    """
    import re
    unplug = Unplug(monkeypatch, biblioteca, after=8, error=error, paths=paths)
    args = ["normalize-lyrics", str(biblioteca), "--strip-headers", "--apply", "--allow-full-rewrite",
            "--no-progress", *sum((["--only", o] for o in ONLY), [])]
    result = runner.invoke(app, args, env={"COLUMNS": "200"})
    assert unplug.unplugged
    assert result.exit_code == 3, result.output
    monkeypatch.undo()  # se vuelve a conectar para leer el diario
    folder = next((biblioteca / BACKUP_DIR_NAME).iterdir())
    run = runs.Run(folder)
    _intents, done = run.outcome()
    events = list(done.values())
    applied = sum(1 for event in events if event["status"] == runs.APPLIED)
    failed = len(events) - applied
    pending = run.state["totals"]["entries"] - len(events)
    assert applied > 0

    def shown(label):
        match = re.search(rf"{label} \(\w+\):?\s+(\d+)", result.output)
        return int(match.group(1)) if match else 0
    assert shown("Aplicadas") == applied, result.output
    assert shown("Con error") == failed, result.output
    assert shown("Sin aplicar") == pending, result.output


def test_revert_shows_recovery_line_only_when_pending(biblioteca, monkeypatch):
    """«Recuperando escrituras pendientes» solo aparece si hay algo pendiente."""
    args = ["normalize-lyrics", str(biblioteca), "--strip-headers", "--apply", "--no-progress",
            *sum((["--only", o] for o in ONLY), [])]
    assert runner.invoke(app, args).exit_code == 0
    folder = next((biblioteca / BACKUP_DIR_NAME).iterdir())
    started = []

    class Recorder:
        def start(self, description, total, completed=0):
            started.append(description)

        def tick(self, *args):
            pass

    backup.revert(folder, progress=Recorder())
    assert "Recuperando escrituras pendientes" not in started
    assert "Revirtiendo" in started
