"""
Huella del audio en el plan: un cambio externo entre planificar y aplicar
se detecta aunque el tamaño y la fecha de modificación no cambien.

En Android (Termux) dos escrituras seguidas pueden quedar con la misma
st_mtime_ns; aquí se simula restaurando la fecha con os.utime, así que las
pruebas no dependen de la resolución de mtime del sistema de archivos.

Con la verificación por defecto (auto/quick) la huella es el hash del
tamaño, el primer y el último MB del audio: un cambio en el medio de un
archivo de más de 2 MB NO se detecta. Con --verify full el plan guarda
también el hash de todo el audio y sí se detecta.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from choconostle import run as runs
from choconostle.cli import app
from choconostle.rawtags.id3 import syncsafe
from conftest import load_generator
from test_run import runner

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="se necesita ffmpeg")
MB = 1 << 20

COMMANDS = {
    "normalize": ["normalize-lyrics", "--strip-headers"],
    "convert": ["convert-lyrics", "--replace-char", "ó=o"],
}


@pytest.fixture(scope="module")
def gen():
    return load_generator()


def build(gen, root: Path, kind: str) -> Path:
    """Un archivo con letra incrustada con cabeceras y acentos (cambia con los dos comandos)."""
    lyrics = gen.synced(gen.ES, gen.HDR_STD)
    if kind == "ogg":
        path = root / "a.ogg"
        gen.make_other(path, ["-c:a", "libvorbis", "-q:a", "0"], {"TITLE": "a", "LYRICS": lyrics})
        return path
    path = root / "a.mp3"
    gen.make_mp3(path, [gen.T("TIT2", "a"), gen.USLT(lyrics)])
    if kind == "mp3-big":  # más de 2 MB de audio: el medio queda fuera de la muestra
        data = path.read_bytes()
        start = audio_start(path)
        audio = data[start:]
        path.write_bytes(data[:start] + audio * (3 * MB // len(audio) + 1))
    return path


def audio_start(path: Path) -> int:
    data = path.read_bytes()
    return 10 + syncsafe(data[6:10]) if data[:3] == b"ID3" else 0


def tamper_before_apply(monkeypatch, path: Path, position) -> dict:
    """Cambia un byte del archivo justo antes de aplicar, con el mismo tamaño y la misma fecha."""
    seen = {}
    real = runs.apply_run

    def wrapped(*args, **kwargs):
        info = os.stat(path)
        data = bytearray(path.read_bytes())
        index = position(path, len(data))
        data[index] ^= 0xFF
        path.write_bytes(bytes(data))
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        assert os.stat(path).st_mtime_ns == info.st_mtime_ns and os.stat(path).st_size == info.st_size
        seen["data"] = bytes(data)
        return real(*args, **kwargs)
    monkeypatch.setattr(runs, "apply_run", wrapped)
    return seen


def last_byte(_path, size):
    return size - 1


def middle_byte(path, size):
    start = audio_start(path)
    return start + (size - start) // 2


def invoke(root: Path, command: str, *extra):
    args = [COMMANDS[command][0], str(root), "--no-progress", "--apply", *COMMANDS[command][1:], *extra]
    return runner.invoke(app, args, env={"COLUMNS": "220"})


@needs_ffmpeg
@pytest.mark.parametrize("command", sorted(COMMANDS))
@pytest.mark.parametrize("kind", ["mp3", "ogg", "mp3-big"])
def test_change_after_planning_is_detected_with_same_mtime(gen, tmp_path, monkeypatch, command, kind):
    root = tmp_path / "lib"
    path = build(gen, root, kind)
    if kind != "mp3-big":
        assert path.stat().st_size < 2 * MB  # el archivo entero cabe en la muestra
    seen = tamper_before_apply(monkeypatch, path, last_byte)
    result = invoke(root, command, *(["--allow-full-rewrite"] if kind == "ogg" else []))
    assert result.exit_code == 1, result.output
    assert "cambió" in result.output
    assert path.read_bytes() == seen["data"]  # no se tocó


@needs_ffmpeg
@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_change_in_the_middle_needs_verify_full(gen, tmp_path, monkeypatch, command):
    # Por defecto (auto/quick) la huella solo cubre el primer y el último MB:
    # un cambio en el medio del audio no se detecta y la letra se escribe.
    root = tmp_path / "default"
    path = build(gen, root, "mp3-big")
    seen = tamper_before_apply(monkeypatch, path, middle_byte)
    result = invoke(root, command)
    assert result.exit_code == 0, result.output
    start = audio_start(path)
    assert path.read_bytes()[start:] == seen["data"][audio_start_of(seen["data"]):]

    # Con --verify full el plan guarda el hash de todo el audio: se detecta.
    root = tmp_path / "full"
    path = build(gen, root, "mp3-big")
    seen = tamper_before_apply(monkeypatch, path, middle_byte)
    result = invoke(root, command, "--verify", "full")
    assert result.exit_code == 1, result.output
    assert "el audio cambió" in result.output
    assert path.read_bytes() == seen["data"]


def audio_start_of(data: bytes) -> int:
    return 10 + syncsafe(data[6:10])


@needs_ffmpeg
def test_plan_records_fingerprint_by_verify_mode(gen, tmp_path):
    from choconostle.normalizer import MODE_STRIP, LyricsNormalizer
    from choconostle.scanner import scan_directory
    root = tmp_path / "lib"
    build(gen, root, "mp3")
    for verify, keys in (("auto", {"start", "length", "sample"}), ("full", {"start", "length", "sample", "sha256"})):
        normalizer = LyricsNormalizer(MODE_STRIP)
        normalizer.verify = verify
        changes = [c for c in normalizer.plan(scan_directory(root)) if c.file_plan]
        assert set(changes[0].file_plan["audio"]) == keys


@needs_ffmpeg
def test_resume_rc1_plan_without_fingerprint_warns(gen, tmp_path):
    from choconostle.normalizer import MODE_STRIP, LyricsNormalizer
    root = tmp_path / "lib"
    path = build(gen, root, "mp3")
    normalizer = LyricsNormalizer(MODE_STRIP)
    execution = runs.Run.create(root, "normalize-lyrics", dict(normalizer.options(), verify="auto"))
    runs.plan_library(execution, normalizer, root)
    plan = execution.folder / runs.PLAN_NAME
    records = [json.loads(line) for line in plan.read_text(encoding="utf-8").splitlines() if line.strip()]
    for record in records:  # como un plan de la rc1
        if record.get("plan"):
            del record["plan"]["audio"]
    plan.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    before = path.read_bytes()
    result = runner.invoke(app, ["normalize-lyrics", str(root), "--resume", str(execution.folder), "--no-progress"],
                           env={"COLUMNS": "220"})
    assert result.exit_code == 0, result.output
    assert "versión anterior" in result.output and "protección anterior" in result.output
    assert path.read_bytes() != before  # se aplicó con la protección anterior
