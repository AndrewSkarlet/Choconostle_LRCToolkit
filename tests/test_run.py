"""
Pruebas de la etapa ③: ejecución en dos pasadas, diario, --resume,
espacio, desconexión, archivos modificados y clean-backups.

Todo se hace sobre copias de la biblioteca de tools/generar_casos.py
(fixture `casos` de conftest.py).
"""

import errno
import json
import os
import shutil
import stat
from collections import namedtuple
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from choconostle import backup
from choconostle import run as runs
from choconostle.cli import app
from choconostle.config import BACKUP_DIR_NAME
from choconostle.normalizer import MODE_STRIP, LyricsNormalizer
from choconostle.rawtags import writer
from choconostle.utils import long_path
from conftest import load_generator

ONLY = ["02_saltos_de_linea", "03_cabeceras", "10_incrustadas"]
LRC = "03_cabeceras/01 estandar ti ar by.lrc"
TARGETS = {
    "lrc": LRC,
    "mp3": "10_incrustadas/21 MP3 v2.3 USLT utf16.mp3",
    "flac": "10_incrustadas/01 FLAC LYRICS con cabeceras.flac",
    "m4a": "10_incrustadas/41 M4A ALAC lyr.m4a",
    "opus": "10_incrustadas/42 OPUS LYRICS.opus",
}
runner = CliRunner()


class Crash(BaseException):
    """Corte de luz: nada se ejecuta después."""


def files(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and BACKUP_DIR_NAME not in p.parts}


def start(root: Path, **options):
    normalizer = LyricsNormalizer(MODE_STRIP, allow_full_rewrite=True, **options)
    execution = runs.Run.create(root, "normalize-lyrics", dict(normalizer.options(), verify="full"))
    runs.plan_library(execution, normalizer, root, ONLY)
    return normalizer, execution


def finish(root: Path, normalizer, execution):
    execution = runs.Run(execution.folder)
    assert runs.resume_check(execution, root, normalizer) == []
    summary = runs.apply_run(execution, normalizer, root, resume=True)
    assert summary.stopped is None
    assert runs.Run(execution.folder).phase == runs.STATE_COMPLETED
    return execution


@pytest.fixture(scope="module")
def original(casos):
    return files(casos)


@pytest.fixture(scope="module")
def reference(casos, tmp_path_factory):
    """Estado de la biblioteca tras aplicar sin interrupciones."""
    root = tmp_path_factory.mktemp("ref") / "lib"
    shutil.copytree(casos, root)
    normalizer, execution = start(root)
    summary = runs.apply_run(execution, normalizer, root)
    assert summary.stopped is None and summary.failed == 0
    return files(root)


def crash_at(monkeypatch, step: str, target: str):
    fired = {"done": False}

    def checkpoint(name, record):
        if name == step and not fired["done"] and record["path"] == target:
            fired["done"] = True
            raise Crash()
    monkeypatch.setattr(runs, "checkpoint", checkpoint)
    return fired


# --------------------------------------------------------------------------
# Plan en disco
# --------------------------------------------------------------------------

def test_plan_and_diary_on_disk(biblioteca, reference, original):
    normalizer, execution = start(biblioteca)
    assert execution.phase == runs.STATE_PLANNED
    assert execution.plan_complete()
    assert files(biblioteca) == original  # planificar no toca nada
    totals = execution.state["totals"]
    assert totals["entries"] > 20 and totals["needed"] > runs.SPACE_MARGIN
    summary = runs.apply_run(execution, normalizer, biblioteca)
    assert summary.applied == totals["entries"] and summary.failed == 0
    intents, done = execution.outcome()
    assert set(intents) == set(done) and len(done) == totals["entries"]
    assert files(biblioteca) == reference
    log = (execution.folder / runs.LOG_NAME).read_text(encoding="utf-8")
    assert log.count("=" * 72) == totals["entries"] and "Resultado:" in log


def test_simulation_leaves_nothing(biblioteca, original):
    result = runner.invoke(app, ["normalize-lyrics", str(biblioteca), "--strip-headers", "--no-progress"])
    assert result.exit_code == 0, result.output
    assert not (biblioteca / BACKUP_DIR_NAME).exists()
    assert files(biblioteca) == original


# --------------------------------------------------------------------------
# Interrupción en cada paso del diario
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kind", list(TARGETS))
@pytest.mark.parametrize("step", ["start", "backup", "intent", "written", "done"])
def test_crash_at_each_step_then_resume(biblioteca, reference, original, monkeypatch, kind, step):
    normalizer, execution = start(biblioteca)
    fired = crash_at(monkeypatch, step, TARGETS[kind])
    with pytest.raises(Crash):
        runs.apply_run(execution, normalizer, biblioteca)
    assert fired["done"]
    monkeypatch.undo()
    assert runs.Run(execution.folder).phase == runs.STATE_APPLYING  # quedó a medias
    finish(biblioteca, normalizer, execution)
    assert files(biblioteca) == reference
    results = backup.revert(execution.folder)
    assert {r.status for r in results} == {backup.REVERT_RESTORED}
    assert files(biblioteca) == original


@pytest.mark.parametrize("kind", ["mp3", "flac", "m4a"])
def test_crash_mid_byte_write_then_resume(biblioteca, reference, original, monkeypatch, kind):
    normalizer, execution = start(biblioteca)
    target = biblioteca / TARGETS[kind]
    real_write = writer._write

    def torn(handle, data):
        if Path(handle.name).name == target.name:
            handle.write(data[:10])
            handle.flush()
            raise Crash()
        real_write(handle, data)
    monkeypatch.setattr(writer, "_write", torn)
    with pytest.raises(Crash):
        runs.apply_run(execution, normalizer, biblioteca)
    monkeypatch.undo()
    assert target.read_bytes() != original[TARGETS[kind]]  # a medias
    finish(biblioteca, normalizer, execution)
    assert files(biblioteca) == reference
    backup.revert(execution.folder)
    assert files(biblioteca) == original


# --------------------------------------------------------------------------
# --resume solo si todo es coherente
# --------------------------------------------------------------------------

def _crashed(biblioteca, monkeypatch, step, target=LRC):
    normalizer, execution = start(biblioteca)
    crash_at(monkeypatch, step, target)
    with pytest.raises(Crash):
        runs.apply_run(execution, normalizer, biblioteca)
    monkeypatch.undo()
    return normalizer, runs.Run(execution.folder)


def _refuses(biblioteca, normalizer, execution, words):
    before = files(biblioteca)
    problems = runs.resume_check(execution, biblioteca, normalizer)
    assert problems and any(words in problem for problem in problems), problems
    assert files(biblioteca) == before  # no se tocó nada
    result = runner.invoke(app, ["normalize-lyrics", str(biblioteca), "--resume", str(execution.folder),
                                 "--no-progress"])
    assert result.exit_code == 2 and "No se puede reanudar" in result.output
    assert files(biblioteca) == before


def test_resume_refuses_file_changed_after_interrupted_write(biblioteca, monkeypatch):
    normalizer, execution = _crashed(biblioteca, monkeypatch, "written")
    (biblioteca / LRC).write_bytes(b"editado por otro programa\n")
    _refuses(biblioteca, normalizer, execution, "cambió fuera de la herramienta")


def test_resume_refuses_missing_backup_copy(biblioteca, monkeypatch):
    normalizer, execution = _crashed(biblioteca, monkeypatch, "intent")
    intents, _done = execution.outcome()
    copy = next(event["copy"] for event in intents.values() if "copy" in event and LRC.split("/")[-1] in event["copy"])
    (execution.folder / copy).unlink()
    _refuses(biblioteca, normalizer, execution, "falta la copia de respaldo")


def test_resume_refuses_applied_file_changed_later(biblioteca, monkeypatch):
    normalizer, execution = _crashed(biblioteca, monkeypatch, "start", TARGETS["mp3"])
    (biblioteca / LRC).write_bytes(b"otra cosa\n")  # ya estaba aplicado
    _refuses(biblioteca, normalizer, execution, "ya se había aplicado")


def test_resume_refuses_completed_or_unfinished_plan(biblioteca, tmp_path):
    normalizer, execution = start(biblioteca)
    runs.apply_run(execution, normalizer, biblioteca)
    _refuses(biblioteca, normalizer, runs.Run(execution.folder), "nada que reanudar")
    planning = runs.Run.create(biblioteca, "normalize-lyrics", normalizer.options())
    _refuses(biblioteca, normalizer, planning, "la planificación no terminó")
    other = tmp_path / "otra"
    other.mkdir()
    assert any("no pertenece" in p for p in runs.resume_check(runs.Run(execution.folder), other, normalizer))


# --------------------------------------------------------------------------
# Espacio libre
# --------------------------------------------------------------------------

def test_not_enough_space_before_applying(biblioteca, reference, original, monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(runs.shutil, "disk_usage", lambda _path: usage(10**9, 10**9 - 1000, 1000))
    result = runner.invoke(app, ["normalize-lyrics", str(biblioteca), "--strip-headers", "--apply",
                                 "--allow-full-rewrite", "--no-progress", *sum((["--only", o] for o in ONLY), [])])
    assert result.exit_code == 2 and "Espacio libre insuficiente" in result.output
    assert files(biblioteca) == original
    folder = next((biblioteca / BACKUP_DIR_NAME).iterdir())
    assert runs.Run(folder).phase == runs.STATE_PLANNED
    monkeypatch.undo()
    result = runner.invoke(app, ["normalize-lyrics", str(biblioteca), "--resume", str(folder), "--no-progress"])
    assert result.exit_code == 0, result.output
    assert files(biblioteca) == reference


def test_disk_full_mid_run_on_lyrics_file(biblioteca, reference, monkeypatch):
    normalizer, execution = start(biblioteca)
    calls = {"n": 0}
    real = runs.write_file_atomic

    def full(path, data):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError(errno.ENOSPC, "No space left on device")
        real(path, data)
    monkeypatch.setattr(runs, "write_file_atomic", full)
    summary = runs.apply_run(execution, normalizer, biblioteca)
    assert summary.stop_kind == "space" and "espacio" in summary.stopped
    state = runs.Run(execution.folder)
    assert state.phase == runs.STATE_INTERRUPTED
    _intents, done = state.outcome()
    assert len(done) == 2  # dos aplicadas; la tercera no se da por aplicada
    monkeypatch.undo()
    finish(biblioteca, normalizer, execution)
    assert files(biblioteca) == reference


def test_disk_full_mid_byte_write_restores_and_stops(biblioteca, reference, original, monkeypatch):
    normalizer, execution = start(biblioteca)
    target = biblioteca / TARGETS["flac"]
    real_write = writer._write
    fired = {"n": 0}

    def full(handle, data):
        if Path(handle.name).name == target.name and fired["n"] == 0:
            fired["n"] += 1
            handle.write(data[:10])
            raise OSError(errno.ENOSPC, "No space left on device")
        real_write(handle, data)
    monkeypatch.setattr(writer, "_write", full)
    summary = runs.apply_run(execution, normalizer, biblioteca)
    assert summary.stop_kind == "space"
    assert target.read_bytes() == original[TARGETS["flac"]]  # restaurado al instante
    monkeypatch.undo()
    finish(biblioteca, normalizer, execution)
    assert files(biblioteca) == reference


# --------------------------------------------------------------------------
# Desconexión de la unidad (portable: no renombra carpetas)
# --------------------------------------------------------------------------

def win_error(code: int) -> OSError:
    """OSError con winerror, igual en Windows y en Linux (donde se asigna a mano)."""
    exc = OSError(errno.EINVAL, f"[WinError {code}] simulado", None, code)
    if getattr(exc, "winerror", None) != code:
        exc.winerror = code
    return exc


def eio() -> OSError:
    return OSError(errno.EIO, "Input/output error (simulado)")


class Unplug:
    """
    Simula que la unidad de la biblioteca se desconecta: a partir de la
    escritura número `after` sobre un archivo de la biblioteca (no del
    respaldo), toda operación sobre rutas de la biblioteca (abrir, stat,
    listar, escribir, reemplazar, borrar, espacio libre) falla con `error()`.

    `on` elige qué escrituras cuentan para el momento de la desconexión:
    "library" (archivos de letra o audio), "backup" (copias en originales/),
    "diary" (diario.jsonl) o "state" (estado.json).

    `paths` reproduce cómo se comportan os.path.isdir/exists/isfile en cada
    sistema, para que la prueba dé lo mismo en Linux y en Windows:
    - "posix": pasan por os.stat (como en Linux), así que también fallan.
    - "windows": en Windows (Python 3.12+) son funciones en C (nt._path_isdir...)
      que no pasan por os.stat: siguen viendo el sistema de archivos real.
    """

    def __init__(self, monkeypatch, root: Path, after: int, error, paths: str = "posix", on: str = "library"):
        self.root = os.path.normcase(os.path.abspath(root))
        # normcase también aquí: en Windows pasa a minúsculas y, si no, las
        # escrituras del respaldo se contaban como de la biblioteca.
        self.backups = os.path.normcase(os.path.join(self.root, BACKUP_DIR_NAME))
        self.on = on
        self.after = after
        self.error = error
        self.writes = 0
        self.unplugged = False
        import builtins
        import io
        real_stat = os.stat
        for module, name in [(builtins, "open"), (io, "open"), (os, "open"), (os, "stat"), (os, "lstat"),
                             (os, "scandir"), (os, "listdir"), (os, "replace"), (os, "rename"),
                             (os, "unlink"), (os, "remove"), (os, "utime"), (os, "mkdir"),
                             (shutil, "disk_usage")]:
            monkeypatch.setattr(module, name, self._wrap(getattr(module, name), name))
        statter = (lambda path: os.stat(path)) if paths == "posix" else real_stat
        for name, test in [("isdir", stat.S_ISDIR), ("isfile", stat.S_ISREG), ("exists", None),
                           ("lexists", None)]:
            monkeypatch.setattr(os.path, name, self._path_check(statter, test))

    @staticmethod
    def _path_check(statter, test):
        def check(path):
            try:
                result = statter(path)
            except (OSError, ValueError):
                return False
            return True if test is None else test(result.st_mode)
        return check

    def _inside(self, path) -> bool:
        if isinstance(path, int):
            return False
        try:
            text = os.fspath(path)
        except TypeError:
            return False
        if isinstance(text, bytes):
            text = os.fsdecode(text)
        text = text[4:] if text.startswith("\\\\?\\") else text
        text = os.path.normcase(os.path.abspath(text))
        return text == self.root or text.startswith(self.root + os.sep)

    def _wrap(self, real, name):
        def wrapper(*args, **kwargs):
            paths = [arg for arg in args[:2] if not isinstance(arg, (int, dict))] if name in ("replace", "rename") \
                else args[:1]
            if any(self._inside(path) for path in paths):
                if self.unplugged:
                    raise self.error()
                mode = args[1] if len(args) > 1 and isinstance(args[1], str) else kwargs.get("mode", "r")
                writing = name in ("open",) and isinstance(mode, str) and any(c in mode for c in "wax+")
                if writing and self._counts(paths[0]):
                    self.writes += 1
                    if self.writes >= self.after:
                        self.unplugged = True
                        raise self.error()
            return real(*args, **kwargs)
        return wrapper

    def _counts(self, path) -> bool:
        text = os.path.normcase(os.path.abspath(os.fspath(path)))
        in_backups = text.startswith(self.backups + os.sep)
        name = os.path.basename(text)
        if self.on == "library":
            return not in_backups
        if self.on == "backup":
            return in_backups and os.sep + "originales" + os.sep in text
        if self.on == "diary":
            return in_backups and name == runs.DIARY_NAME
        return in_backups and name.startswith(runs.STATE_NAME)


PATH_MODES = ["posix", "windows"]


@pytest.mark.parametrize("paths", PATH_MODES)
@pytest.mark.parametrize("error", [eio, lambda: win_error(1167)], ids=["EIO", "WinError1167"])
def test_device_disconnected_then_resume(biblioteca, reference, original, monkeypatch, error, paths):
    unplug = Unplug(monkeypatch, biblioteca, after=5, error=error, paths=paths)
    args = ["normalize-lyrics", str(biblioteca), "--strip-headers", "--apply", "--allow-full-rewrite",
            "--no-progress", *sum((["--only", o] for o in ONLY), [])]
    result = runner.invoke(app, args, env={"COLUMNS": "200"})
    assert unplug.unplugged
    assert result.exit_code == 3, result.output
    assert "se desconectó la tarjeta SD" in result.output
    assert "--resume" in result.output
    monkeypatch.undo()  # se vuelve a conectar
    folder = next((biblioteca / BACKUP_DIR_NAME).iterdir())
    _intents, done = runs.Run(folder).outcome()
    assert len(done) == 4  # solo las confirmadas antes de la desconexión
    result = runner.invoke(app, ["normalize-lyrics", str(biblioteca), "--resume", str(folder), "--no-progress"])
    assert result.exit_code == 0, result.output
    assert files(biblioteca) == reference
    backup.revert(folder)
    assert files(biblioteca) == original


@pytest.mark.parametrize("paths", PATH_MODES)
@pytest.mark.parametrize("on,after", [("backup", 3), ("diary", 7), ("diary", 8), ("state", 3), ("state", 4)])
@pytest.mark.parametrize("error", [eio, lambda: win_error(1167), lambda: win_error(3)],
                         ids=["EIO", "WinError1167", "WinError3"])
def test_disconnection_while_writing_backup_or_diary(biblioteca, reference, original, monkeypatch,
                                                     error, on, after, paths):
    """
    La unidad se va justo al escribir la copia de respaldo, el diario o el
    estado (no un archivo de la biblioteca). La ejecución debe terminar con
    código 3, indicar --resume, y --resume debe poder continuar.
    """
    unplug = Unplug(monkeypatch, biblioteca, after=after, error=error, paths=paths, on=on)
    args = ["normalize-lyrics", str(biblioteca), "--strip-headers", "--apply", "--allow-full-rewrite",
            "--no-progress", *sum((["--only", o] for o in ONLY), [])]
    result = runner.invoke(app, args, env={"COLUMNS": "200"})
    assert unplug.unplugged
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(result.exception)
    assert result.exit_code == 3, result.output
    assert "--resume" in result.output
    monkeypatch.undo()  # se vuelve a conectar
    folder = next((biblioteca / BACKUP_DIR_NAME).iterdir())
    result = runner.invoke(app, ["normalize-lyrics", str(biblioteca), "--resume", str(folder), "--no-progress"])
    assert result.exit_code == 0, result.output
    assert files(biblioteca) == reference
    backup.revert(folder)
    assert files(biblioteca) == original


@pytest.mark.parametrize("paths", PATH_MODES)
def test_drive_letter_disappears(biblioteca, reference, monkeypatch, paths):
    """La letra de unidad (o el punto de montaje) desaparece: "no se encuentra la ruta"."""
    normalizer, execution = start(biblioteca)
    Unplug(monkeypatch, biblioteca, after=3, error=lambda: win_error(3), paths=paths)  # ERROR_PATH_NOT_FOUND
    summary = runs.apply_run(execution, normalizer, biblioteca)
    assert summary.stop_kind == "device"
    monkeypatch.undo()
    finish(biblioteca, normalizer, execution)
    assert files(biblioteca) == reference


@pytest.mark.parametrize("code", sorted(runs.DEVICE_WINERRORS))
def test_windows_device_errors_stop_the_run(biblioteca, reference, monkeypatch, code):
    assert runs.fatal_kind(win_error(code), biblioteca) == "device"
    normalizer, execution = start(biblioteca)
    calls = {"n": 0}
    real = runs.write_file_atomic

    def failing(path, data):
        calls["n"] += 1
        if calls["n"] == 2:
            raise win_error(code)
        real(path, data)
    monkeypatch.setattr(runs, "write_file_atomic", failing)
    summary = runs.apply_run(execution, normalizer, biblioteca)
    assert summary.stop_kind == "device" and summary.applied == 1
    assert runs.Run(execution.folder).phase == runs.STATE_INTERRUPTED
    monkeypatch.undo()
    finish(biblioteca, normalizer, execution)
    assert files(biblioteca) == reference


def test_access_denied_is_not_a_disconnection(biblioteca, monkeypatch):
    """WinError 5 (acceso denegado) es un fallo de ese archivo: la ejecución sigue."""
    (biblioteca / BACKUP_DIR_NAME).mkdir()  # como durante una ejecución
    assert runs.fatal_kind(win_error(5), biblioteca) is None
    assert runs.fatal_kind(win_error(112), biblioteca) == "space"
    calls = {"n": 0}
    real = runs.write_file_atomic

    def denied(path, data):
        calls["n"] += 1
        if calls["n"] == 2:
            raise win_error(5)
        real(path, data)
    monkeypatch.setattr(runs, "write_file_atomic", denied)
    args = ["normalize-lyrics", str(biblioteca), "--strip-headers", "--apply", "--no-progress",
            *sum((["--only", o] for o in ONLY), [])]
    result = runner.invoke(app, args, env={"COLUMNS": "200"})
    assert result.exit_code == 1, result.output  # un archivo falló; el resto se aplicó
    folder = next(f for f in (biblioteca / BACKUP_DIR_NAME).iterdir() if f.is_dir())
    execution = runs.Run(folder)
    assert execution.phase == runs.STATE_COMPLETED
    failed = [item for item in execution.manifest["items"] if item["status"] == "failed"]
    assert len(failed) == 1 and "WinError 5" in failed[0]["error"]


def test_disconnection_while_planning(biblioteca, original, monkeypatch):
    real_iter = runs.iter_folders

    def iter_and_unplug(*args, **kwargs):
        for number, folder in enumerate(real_iter(*args, **kwargs)):
            if number == 3:
                monkeypatch.setattr(runs, "reachable", lambda *a, **k: False)
            yield folder
    monkeypatch.setattr(runs, "iter_folders", iter_and_unplug)
    result = runner.invoke(app, ["normalize-lyrics", str(biblioteca), "--strip-headers", "--apply",
                                 "--no-progress"], env={"COLUMNS": "200"})
    assert result.exit_code == 3 and "durante la planificación" in result.output
    monkeypatch.undo()
    assert files(biblioteca) == original
    assert not list((biblioteca / BACKUP_DIR_NAME).iterdir())  # sin respaldo: no se aplicó nada


# --------------------------------------------------------------------------
# Archivos modificados entre la planificación y la aplicación
# --------------------------------------------------------------------------

def test_files_modified_between_plan_and_apply(biblioteca, reference):
    normalizer, execution = start(biblioteca)
    lrc = biblioteca / LRC
    lrc.write_bytes(lrc.read_bytes() + b"[00:20.00]Linea agregada por otro programa\n")
    mp3 = biblioteca / TARGETS["mp3"]
    data = bytearray(mp3.read_bytes())
    data[-1] ^= 0xFF
    mp3.write_bytes(bytes(data))
    modified = {LRC: lrc.read_bytes(), TARGETS["mp3"]: mp3.read_bytes()}

    summary = runs.apply_run(execution, normalizer, biblioteca)
    assert summary.failed == 2 and summary.stopped is None
    items = {item["path"]: item for item in execution.manifest["items"]}
    for path in modified:
        assert items[path]["status"] == "failed" and "cambió" in items[path]["error"]
    result = files(biblioteca)
    for path, content in result.items():
        assert content == modified.get(path, reference[path]), path


# --------------------------------------------------------------------------
# clean-backups
# --------------------------------------------------------------------------

def _age(folder: Path, days: int) -> None:
    state_path = folder / runs.STATE_NAME
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["created_at"] = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    state_path.write_text(json.dumps(state), encoding="utf-8")


def test_clean_backups_never_touches_incomplete_runs(biblioteca, monkeypatch):
    normalizer, done_old = start(biblioteca)
    runs.apply_run(done_old, normalizer, biblioteca)
    backup.revert(done_old.folder)
    _age(done_old.folder, 40)

    normalizer, interrupted = start(biblioteca)
    crash_at(monkeypatch, "intent", TARGETS["flac"])
    with pytest.raises(Crash):
        runs.apply_run(interrupted, normalizer, biblioteca)
    monkeypatch.undo()
    _age(interrupted.folder, 40)

    normalizer, planned = start(biblioteca)
    _age(planned.folder, 40)

    v2 = biblioteca / BACKUP_DIR_NAME / "2020-01-01_00-00-00"
    v2.mkdir()
    (v2 / "manifiesto.json").write_text(json.dumps({"manifest_version": 2, "created_at": "2020-01-01T00:00:00",
                                                    "items": [{"status": "applied"}]}), encoding="utf-8")
    torn = biblioteca / BACKUP_DIR_NAME / "2020-01-02_00-00-00"
    torn.mkdir()
    (torn / "manifiesto.json").write_text(json.dumps({"manifest_version": 2, "created_at": "2020-01-02T00:00:00",
                                                      "items": []}), encoding="utf-8")
    (torn / "pendiente").mkdir()
    (torn / "pendiente" / "edit-0001.json").write_text("{}", encoding="utf-8")

    remove, keep = runs.clean_backups(biblioteca, 30)
    assert {info.folder for info in remove} == {done_old.folder, v2}
    reasons = {info.folder: info.keep_reason for info in keep}
    assert "reanudable" in reasons[interrupted.folder]
    assert "reanudable" in reasons[planned.folder]
    assert "interrumpidas" in reasons[torn]
    assert all(info.folder.exists() for info in remove)  # simulación: nada borrado

    result = runner.invoke(app, ["clean-backups", str(biblioteca), "--older-than", "30"])
    assert result.exit_code == 0 and "SIMULACIÓN" in result.output and "--apply" in result.output
    result = runner.invoke(app, ["clean-backups", str(biblioteca), "--older-than", "30", "--apply"])
    assert result.exit_code == 0 and "BORRADOS" in result.output
    assert not done_old.folder.exists() and not v2.exists()
    assert interrupted.folder.exists() and planned.folder.exists() and torn.exists()
    # La ejecución interrumpida se sigue pudiendo reanudar.
    assert runs.resume_check(runs.Run(interrupted.folder), biblioteca, normalizer) == []


# --------------------------------------------------------------------------
# Salida de la CLI
# --------------------------------------------------------------------------

def test_apply_lists_every_song_and_nothing_to_apply(biblioteca):
    args = ["normalize-lyrics", str(biblioteca), "--strip-headers", "--apply", "--no-progress"]
    result = runner.invoke(app, args, env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "... y" not in result.output
    assert "01_codificaciones/16 ruso utf8.flac" in result.output  # mucho más allá de las primeras 20
    result = runner.invoke(app, args, env={"COLUMNS": "200"})
    assert "APLICADO: no había nada que aplicar" in result.output
    assert "SIMULACIÓN" not in result.output
    assert len(list((biblioteca / BACKUP_DIR_NAME).iterdir())) == 1  # no se creó otro respaldo


def test_repeated_lyric_frames_are_kept_apart(tmp_path):
    gen = load_generator()
    root = tmp_path / "lib"
    first = gen.synced(gen.ES, gen.HDR_STD)
    second = gen.synced(gen.RU, ["[ti:Ruso]", ""])
    third = gen.synced(gen.JA, ["[ar:Japonés]", ""])
    mp3 = root / "dos USLT.mp3"
    gen.make_mp3(mp3, gen.basic_id3("x") + [gen.USLT(first, "eng"), gen.USLT(second, "spa"),
                                            gen.USLT(third, "eng")], 4)
    original = mp3.read_bytes()
    result = runner.invoke(app, ["normalize-lyrics", str(root), "--strip-headers", "--apply", "--diff",
                                 "--no-progress"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    for label, removed in (("USLT [eng] #1", "-[ti:Canción de prueba]"), ("USLT [spa]", "-[ti:Ruso]"),
                           ("USLT [eng] #2", "-[ar:Japonés]")):
        assert result.output.count(f"{label}:") == 1, label
        assert removed in result.output
    from choconostle.rawtags.id3 import open_id3
    values = [slot.value for slot in open_id3(mp3).slots()]
    assert values == [first.split("\n", 4)[4], second.split("\n", 2)[2], third.split("\n", 2)[2]]
    folder = next((root / BACKUP_DIR_NAME).iterdir())
    log = (folder / runs.LOG_NAME).read_text(encoding="utf-8")
    assert log.count("USLT [eng] #1:") == log.count("USLT [spa]:") == log.count("USLT [eng] #2:") == 1
    results = backup.revert(folder)
    assert sorted(r.item["label"] for r in results) == ["USLT [eng] #1", "USLT [eng] #2", "USLT [spa]"]
    assert mp3.read_bytes() == original


def test_verify_quick(biblioteca, reference, original):
    normalizer = LyricsNormalizer(MODE_STRIP, allow_full_rewrite=True)
    execution = runs.Run.create(biblioteca, "normalize-lyrics", dict(normalizer.options(), verify="quick"))
    runs.plan_library(execution, normalizer, biblioteca, ONLY)
    summary = runs.apply_run(execution, normalizer, biblioteca, verify="quick")
    assert summary.failed == 0 and files(biblioteca) == reference
    backup.revert(execution.folder)
    assert files(biblioteca) == original


def test_long_paths():
    assert long_path("C:\\Música\\x.lrc", windows=True) == "C:\\Música\\x.lrc"
    deep = "C:\\" + "\\".join(["carpeta muy larga de prueba"] * 10) + "\\canción.lrc"
    assert long_path(deep, windows=True) == "\\\\?\\" + deep
    unc = "\\\\servidor\\música\\" + "x" * 250
    assert long_path(unc, windows=True) == "\\\\?\\UNC\\servidor\\música\\" + "x" * 250
    assert long_path("\\\\?\\" + deep, windows=True) == "\\\\?\\" + deep
    assert long_path("/sdcard/" + "y" * 300, windows=False) == "/sdcard/" + "y" * 300


def test_scan_text_about_nearly_empty(tmp_path):
    library = tmp_path / "lib"
    library.mkdir()
    gen = load_generator()
    gen.song(library, "01", "[ar:x]\n[00:00.00]Instrumental\n")
    result = runner.invoke(app, ["scan", str(library), "--no-progress"], env={"COLUMNS": "200"})
    assert "las procesa con un aviso" in result.output and "no las modifica" not in result.output


# --------------------------------------------------------------------------
# Rutas largas en los mensajes y revert --latest
# --------------------------------------------------------------------------

def test_copyable_lines_are_not_wrapped(tmp_path):
    gen = load_generator()
    library = tmp_path.joinpath(*[f"Carpeta con un nombre bastante largo número {n}" for n in range(6)])
    gen.song(library / "Álbum", "01 Canción", gen.synced(gen.ES, gen.HDR_STD))
    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--apply",
                                 "--no-progress"], env={"COLUMNS": "60"})
    assert result.exit_code == 0, result.output
    folder = next((library / BACKUP_DIR_NAME).iterdir())
    lines = result.output.splitlines()
    assert len(f'choconostle revert "{folder}"') > 300
    assert f'choconostle revert "{folder}"' in lines  # una sola línea, aunque la terminal mida 60
    assert str(folder) in lines


def test_revert_not_found_message(tmp_path):
    missing = tmp_path / "ChoconostleLRCTool_back" / "2026-10-28_03-51"
    result = runner.invoke(app, ["revert", str(missing)], env={"COLUMNS": "60"})
    assert result.exit_code == 2
    assert "No se encontró estado.json" in result.output
    assert "en una sola línea" in result.output
    assert str(missing) in result.output.replace("\n", "") and str(missing) in result.output


def test_revert_library_with_latest(biblioteca, original):
    first = ["normalize-lyrics", str(biblioteca), "--strip-headers", "--apply", "--no-progress",
             "--only", "03_cabeceras"]
    second = ["normalize-lyrics", str(biblioteca), "--strip-headers", "--apply", "--no-progress",
              "--only", "02_saltos_de_linea"]
    assert runner.invoke(app, first).exit_code == 0
    import time
    time.sleep(1.1)  # carpetas con fecha distinta
    assert runner.invoke(app, second).exit_code == 0
    after_both = files(biblioteca)

    result = runner.invoke(app, ["revert", str(biblioteca)], env={"COLUMNS": "200"})
    assert result.exit_code == 2 and "--latest" in result.output and "2 respaldos" in result.output
    assert files(biblioteca) == after_both

    result = runner.invoke(app, ["revert", str(biblioteca), "--latest"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "Respaldo más reciente" in result.output
    now = files(biblioteca)
    for path, data in now.items():
        if path.startswith("02_saltos_de_linea"):
            assert data == original[path], path  # se revirtió la segunda ejecución
        elif path.startswith("03_cabeceras"):
            assert data == after_both[path], path  # la primera sigue aplicada
    # También desde la carpeta de respaldos.
    result = runner.invoke(app, ["revert", str(biblioteca / BACKUP_DIR_NAME), "--latest", "--dry-run"])
    assert result.exit_code == 0 and "Ya estaban como el original" in result.output


def test_diary_survives_a_torn_line(tmp_path):
    """Una línea del diario cortada por la desconexión no se pega al evento siguiente."""
    execution = runs.Run.create(tmp_path, "normalize-lyrics", {})
    execution.event({"event": "intent", "id": 1})
    with open(execution.folder / runs.DIARY_NAME, "a", encoding="utf-8") as handle:
        handle.write('{"event": "done", "id": 1, "sta')  # corte a mitad de línea
    assert [e["event"] for e in execution.events()] == ["intent"]  # lo cortado no cuenta
    execution.event({"event": "done", "id": 1, "status": "applied"})
    intents, done = execution.outcome()
    assert list(intents) == [1] and done[1]["status"] == "applied"
    # Una línea dañada en medio (p. ej. bytes basura) se ignora sin romper la lectura.
    with open(execution.folder / runs.DIARY_NAME, "a", encoding="utf-8") as handle:
        handle.write("\x00\x00basura\n")
    execution.event({"event": "intent", "id": 2})
    assert [e["id"] for e in execution.events()] == [1, 1, 2]
