"""
Pruebas de la edición byte a byte (etapa ②).

Los archivos se crean con las funciones de tools/generar_casos.py (ver
tools/CASOS.md) en carpetas temporales.
"""

import errno
import importlib.util
import json
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from choconostle import backup
from choconostle.config import BACKUP_DIR_NAME
from choconostle.normalizer import (
    MODE_STANDARDIZE, MODE_STRIP, STATUS_CHANGE, STATUS_SKIPPED, LyricsNormalizer, PendingWritesError,
    pending_sessions,
)
from choconostle.rawtags import id3 as rawid3
from choconostle.rawtags import writer
from choconostle.report import skipped_by_reason
from choconostle.scanner import scan_directory

GENERATOR = Path(__file__).resolve().parents[1] / "tools" / "generar_casos.py"
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="se necesita ffmpeg")


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("generar_casos", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LRC = None


@pytest.fixture(scope="module")
def lyrics(gen):
    return gen.synced(gen.ES, gen.HDR_STD)


# --------------------------------------------------------------------------
# Construcción de archivos
# --------------------------------------------------------------------------

def id3_tag(gen, frames, version=4, padding=256, flags=0, frame_flags=None):
    """Como generar_casos.id3_tag, con relleno y marcas configurables."""
    payload = b""
    for position, frame in enumerate(frames):
        size = gen._syncsafe(len(frame.body)) if version == 4 else struct.pack(">I", len(frame.body))
        marks = (frame_flags or {}).get(position, b"\0\0")
        payload += frame.fid.encode() + size + marks + frame.body
    payload += b"\0" * padding
    return b"ID3" + bytes([version, 0, flags]) + gen._syncsafe(len(payload)) + payload


def make_mp3(gen, path: Path, frames, version=4, padding=256, **options) -> Path:
    gen.make_mp3(path)  # solo audio (sin tag)
    path.write_bytes(id3_tag(gen, frames, version, padding, **options) + path.read_bytes())
    return path


def apic(size: int):
    """Frame APIC con una "portada" de `size` bytes (contenido no comprimible)."""
    import os
    from types import SimpleNamespace
    image = b"\xff\xd8\xff\xe0" + os.urandom(size)
    body = b"\x00image/jpeg\x00\x03\x00" + image
    return SimpleNamespace(fid="APIC", body=body)


def run(root, mode=MODE_STRIP, **options):
    normalizer = LyricsNormalizer(mode, **options)
    changes = normalizer.plan(scan_directory(root))
    return normalizer, changes


def apply(root, mode=MODE_STRIP, **options):
    normalizer, changes = run(root, mode, **options)
    return normalizer.apply(changes, root), changes


def frames_of(path: Path):
    data = path.read_bytes()
    layout = rawid3.parse_tag(data[:10 + rawid3.syncsafe(data[6:10])])
    return layout, data[10 + layout.size:]


def backup_size(session) -> int:
    return sum(p.stat().st_size for p in session.folder.rglob("*") if p.is_file())


# --------------------------------------------------------------------------
# ID3v2.3 y v2.4, portada grande, frames ajenos intactos
# --------------------------------------------------------------------------

@needs_ffmpeg
@pytest.mark.parametrize("version,encoding", [(3, 1), (4, 3), (3, 0)])
def test_id3_versions_keep_other_frames_and_revert_identical(gen, lyrics, tmp_path, version, encoding):
    root = tmp_path / "lib"
    text_encoding = encoding if encoding != 3 or version == 4 else 1
    frames = [gen.T("TIT2", "Título", text_encoding), gen.T("TPE1", "Artista", text_encoding),
              gen.USLT(lyrics, enc=encoding), apic(2_000_000), gen.T("TALB", "Álbum", text_encoding),
              gen.TXXX("COMENTARIO", "no es letra", encoding)]
    mp3 = make_mp3(gen, root / "a" / "cancion.mp3", frames, version)
    original = mp3.read_bytes()
    before, audio_before = frames_of(mp3)

    session, changes = apply(root)
    assert [c.status for c in changes if c.kind == "embedded"] == [STATUS_CHANGE]
    after, audio_after = frames_of(mp3)
    assert after.version == version
    assert audio_after == audio_before  # el audio no se movió
    assert len(mp3.read_bytes()) == len(original)
    for old, new in zip(before.frames, after.frames):
        if old.frame_id != "USLT":
            assert old.raw == new.raw, old.frame_id  # TIT2, TPE1, APIC, TALB, TXXX: byte a byte
    uslt = next(f for f in after.frames if f.frame_id == "USLT")
    assert uslt.lyric.encoding == encoding
    assert uslt.lyric.values[0][0].startswith("[00:01.00]")
    # La portada (2 MB) nunca va al respaldo.
    assert backup_size(session) < 50_000
    assert not list(session.folder.glob("*/pendiente/*"))

    results = backup.revert(session.folder)
    assert {r.status for r in results} == {backup.REVERT_RESTORED}
    assert mp3.read_bytes() == original


@needs_ffmpeg
def test_tag_without_padding(gen, lyrics, tmp_path):
    root = tmp_path / "lib"
    mp3 = make_mp3(gen, root / "sin relleno.mp3", [gen.T("TIT2", "x"), gen.USLT(lyrics)], padding=0)
    original = mp3.read_bytes()
    session, changes = apply(root)
    layout, _audio = frames_of(mp3)
    assert layout.padding > 0  # los bytes liberados pasan a ser relleno
    assert len(mp3.read_bytes()) == len(original)
    assert "relleno ID3 0 ->" in "; ".join(changes[0].details)
    backup.revert(session.folder)
    assert mp3.read_bytes() == original


@needs_ffmpeg
def test_lyrics_longer_than_padding_needs_full_rewrite(gen, tmp_path):
    from typer.testing import CliRunner
    from choconostle.cli import app
    root = tmp_path / "lib"
    body = gen.synced(gen.ES)  # sin cabeceras: --standardize-headers las añade
    mp3 = make_mp3(gen, root / "corto.mp3", [gen.T("TIT2", "Título largo de la canción"),
                                              gen.T("TPE1", "Artista de Prueba"),
                                              gen.T("TALB", "Álbum de Prueba"), gen.USLT(body)], padding=4)
    original = mp3.read_bytes()
    _audio = frames_of(mp3)[1]

    _normalizer, changes = run(root, MODE_STANDARDIZE)
    change = next(c for c in changes if c.kind == "embedded")
    assert change.status == STATUS_SKIPPED and change.skip_reason == "full_rewrite"
    assert "reescritura completa, requiere" in change.message
    result = CliRunner().invoke(app, ["normalize-lyrics", str(root), "--standardize-headers", "--diff",
                                      "--no-progress"], env={"COLUMNS": "200"})
    assert "reescritura completa, requiere" in result.output
    assert "reescritura completa (requiere --allow-full-rewrite)" in result.output

    session, changes = apply(root, MODE_STANDARDIZE, allow_full_rewrite=True)
    assert [c.status for c in changes if c.kind == "embedded"] == [STATUS_CHANGE]
    layout, audio = frames_of(mp3)
    assert audio == _audio and layout.padding == 0
    assert layout.frames[-1].lyric.values[0][0].startswith("[ar:Artista de Prueba]")
    assert not list(root.glob("*.choconostle-tmp"))
    backup.revert(session.folder)
    assert mp3.read_bytes() == original


@needs_ffmpeg
def test_txxx_with_several_values_is_not_joined(gen, lyrics, tmp_path):
    root = tmp_path / "lib"
    second = "[ar:Otro]\n[00:01.00]Uno\n[00:02.00]Dos\n[00:03.00]Tres\n"
    mp3 = make_mp3(gen, root / "txxx.mp3", [gen.T("TIT2", "x"), gen.TXXX("LYRICS", lyrics + "\0" + second)])
    original = mp3.read_bytes()
    _normalizer, changes = run(root)
    labels = [(c.label, c.slot.index) for c in changes if c.kind == "embedded"]
    assert labels == [("TXXX:LYRICS #1", 0), ("TXXX:LYRICS #2", 1)]
    session, _changes = apply(root)
    layout, _audio = frames_of(mp3)
    values = [text for text, _bom in layout.frames[1].lyric.values]
    assert len(values) == 2
    assert values[0].startswith("[00:01.00]Esta") and values[1] == "[00:01.00]Uno\n[00:02.00]Dos\n[00:03.00]Tres\n"
    backup.revert(session.folder)
    assert mp3.read_bytes() == original


# --------------------------------------------------------------------------
# Lo que no se puede editar se omite y se cuenta
# --------------------------------------------------------------------------

def _id3v22(gen, lyrics) -> bytes:
    def frame(fid, body):
        return fid + len(body).to_bytes(3, "big") + body
    payload = frame(b"TT2", b"\x00x") + frame(b"ULT", b"\x00eng\x00" + lyrics.encode("latin-1", "replace"))
    payload += b"\0" * 64
    return b"ID3\x02\x00\x00" + gen._syncsafe(len(payload)) + payload


@needs_ffmpeg
def test_unsupported_id3_is_skipped_and_counted(gen, lyrics, tmp_path):
    root = tmp_path / "lib"
    gen.make_mp3(root / "v22.mp3")
    path = root / "v22.mp3"
    path.write_bytes(_id3v22(gen, lyrics) + path.read_bytes())
    # Unsynchronisation (marca del tag) sin bytes 0xFF que desincronizar.
    make_mp3(gen, root / "unsync.mp3", [gen.T("TIT2", "x"), gen.USLT(lyrics)], flags=0x80)
    # USLT comprimido (zlib + indicador de longitud).
    body = gen.USLT(lyrics).body
    from types import SimpleNamespace
    compressed = SimpleNamespace(fid="USLT", body=len(body).to_bytes(4, "big") + zlib.compress(body))
    make_mp3(gen, root / "comprimido.mp3", [gen.T("TIT2", "x"), compressed],
             frame_flags={1: b"\x00\x09"})
    before = {p.name: p.read_bytes() for p in root.iterdir()}

    _normalizer, changes = run(root)
    reasons = {label: len(paths) for label, paths in skipped_by_reason(changes)}
    assert reasons == {
        "ID3v2.2 (no se edita; mutagen lo convertiría a 2.3/2.4)": 1,
        "ID3 con unsynchronisation": 1,
        "frame de letra comprimido, cifrado o con otras marcas": 1,
    }
    session, _ = apply(root)
    assert session is None
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == before


def _ffmpeg_m4a(path: Path, lyrics_text: str, *extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "anullsrc=r=44100:cl=stereo", "-t", "2", "-map_metadata", "-1",
                    "-c:a", "alac", "-metadata", "title=Título", "-metadata", "artist=Artista",
                    "-metadata", f"lyrics={lyrics_text}", *extra, str(path)], check=True)
    return path


@needs_ffmpeg
def test_m4a_moov_before_mdat(gen, lyrics, tmp_path):
    root = tmp_path / "lib"
    # Se acorta: el free de 8 bytes tras moov absorbe la diferencia.
    shrink = _ffmpeg_m4a(root / "acorta.m4a", lyrics, "-movflags", "+faststart")
    original = shrink.read_bytes()
    session, changes = apply(root)
    assert [c.status for c in changes if c.kind == "embedded"] == [STATUS_CHANGE]
    assert len(shrink.read_bytes()) == len(original)
    backup.revert(session.folder)
    assert shrink.read_bytes() == original
    shutil.rmtree(root / BACKUP_DIR_NAME)

    # Crece (--standardize-headers sobre una letra sin cabeceras) y no hay relleno: se omite.
    shrink.unlink()
    grow = _ffmpeg_m4a(root / "crece.m4a", gen.synced(gen.ES), "-movflags", "+faststart")
    before = grow.read_bytes()
    _normalizer, changes = run(root, MODE_STANDARDIZE)
    change = next(c for c in changes if c.kind == "embedded")
    assert change.status == STATUS_SKIPPED and change.skip_reason == "mp4_no_padding"
    assert {label: len(p) for label, p in skipped_by_reason(changes)} == \
        {"M4A sin relleno (moov antes de mdat)": 1}
    assert grow.read_bytes() == before


# --------------------------------------------------------------------------
# Comprobaciones antes y después de escribir
# --------------------------------------------------------------------------

@needs_ffmpeg
def test_file_changed_between_plan_and_apply(gen, lyrics, tmp_path):
    root = tmp_path / "lib"
    mp3 = make_mp3(gen, root / "a.mp3", [gen.T("TIT2", "x"), gen.USLT(lyrics)])
    normalizer, changes = run(root)
    info = mp3.stat()
    data = bytearray(mp3.read_bytes())
    data[-1] ^= 0xFF  # alguien cambia el archivo (aquí, el último byte de audio)
    mp3.write_bytes(bytes(data))
    # Misma fecha de modificación, como en Android cuando dos escrituras caen en
    # el mismo instante: el cambio se detecta por la huella del audio del plan.
    import os
    os.utime(mp3, ns=(info.st_atime_ns, info.st_mtime_ns))
    session = normalizer.apply(changes, root)
    item = session.manifest["items"][0]
    assert item["status"] == backup.ITEM_FAILED and "cambió" in item["error"]
    assert mp3.read_bytes() == bytes(data)


@needs_ffmpeg
def test_verification_failure_restores_original(gen, lyrics, tmp_path, monkeypatch):
    root = tmp_path / "lib"
    mp3 = make_mp3(gen, root / "a.mp3", [gen.T("TIT2", "x"), gen.USLT(lyrics)])
    original = mp3.read_bytes()
    monkeypatch.setattr(writer, "_check", lambda *args: ["simulado: cambió el audio"])
    session, _ = apply(root)
    item = session.manifest["items"][0]
    assert item["status"] == backup.ITEM_FAILED
    assert "verificación" in item["error"] and "se restauró el original" in item["error"]
    assert mp3.read_bytes() == original
    assert not pending_sessions(root)


# --------------------------------------------------------------------------
# Interrupciones
# --------------------------------------------------------------------------

class SimulatedCrash(BaseException):
    """Corte de luz o desconexión: nada se ejecuta después."""


def _torn_write(exception):
    """Escribe solo los primeros 10 bytes y se corta (el archivo queda a medias)."""
    def write(handle, data):
        handle.write(data[:10])
        handle.flush()
        raise exception
    return write


def _make(gen, lyrics, root: Path, kind: str) -> Path:
    if kind == "mp3":
        return make_mp3(gen, root / "a.mp3", [gen.T("TIT2", "x"), gen.USLT(lyrics), apic(300_000)])
    if kind == "flac":
        path = root / "a.flac"
        gen.make_flac(path, [("TITLE", "x"), ("LYRICS", lyrics)])
        return path
    if kind == "wv":
        path = root / "a.wv"
        gen.make_other(path, ["-c:a", "wavpack"], {"Title": "x", "Lyrics": lyrics})
        return path
    path = root / "a.m4a"
    gen.make_other(path, ["-c:a", "alac"], {"title": "x", "lyrics": lyrics})
    return path


@needs_ffmpeg
@pytest.mark.parametrize("kind", ["mp3", "flac", "wv", "m4a"])
def test_crash_mid_write_then_recover(gen, lyrics, tmp_path, monkeypatch, kind, paths_mode):
    root = tmp_path / "lib"
    path = _make(gen, lyrics, root, kind)
    original = path.read_bytes()
    normalizer, changes = run(root)
    monkeypatch.setattr(writer, "_write", _torn_write(SimulatedCrash()))
    with pytest.raises(SimulatedCrash):
        normalizer.apply(changes, root)
    monkeypatch.undo()
    torn = path.read_bytes()
    expected = [c for c in changes if c.kind == "embedded"][0]
    assert torn != original  # quedó a medias: ni el original...
    from choconostle.embedded import open_editor
    from choconostle.rawtags import Unsupported
    try:  # ...ni el resultado previsto (a menudo ni siquiera se puede leer)
        assert [s.value for s in open_editor(path).slots()] != [expected.new_value]
    except Unsupported:
        pass

    folders = pending_sessions(root)
    assert len(folders) == 1
    with pytest.raises(PendingWritesError):  # no se puede aplicar otra vez sin recuperar
        LyricsNormalizer(MODE_STRIP).apply(run(root)[1], root)

    results = backup.recover_session(folders[0])
    assert [status for _name, status, _msg in results] == ["restored"]
    assert path.read_bytes() == original
    assert not pending_sessions(root)
    manifest = backup.load_manifest(folders[0])
    assert manifest["edits"][0]["status"] == backup.ITEM_FAILED
    assert {r.status for r in backup.revert(folders[0])} == {backup.REVERT_ALREADY}
    assert path.read_bytes() == original


@needs_ffmpeg
def test_crash_after_write_completed(gen, lyrics, tmp_path, monkeypatch):
    root = tmp_path / "lib"
    path = _make(gen, lyrics, root, "mp3")
    original = path.read_bytes()
    normalizer, changes = run(root)

    def crash(*args):
        raise SimulatedCrash()
    monkeypatch.setattr(writer, "_check", crash)  # se corta justo después de escribir
    with pytest.raises(SimulatedCrash):
        normalizer.apply(changes, root)
    monkeypatch.undo()
    folder = pending_sessions(root)[0]
    results = backup.recover_session(folder)
    assert [status for _name, status, _msg in results] == ["complete"]
    assert backup.load_manifest(folder)["edits"][0]["status"] == backup.ITEM_APPLIED
    assert path.read_bytes() != original
    assert {r.status for r in backup.revert(folder)} == {backup.REVERT_RESTORED}
    assert path.read_bytes() == original


@needs_ffmpeg
def test_io_error_mid_write_restores_immediately(gen, lyrics, tmp_path, monkeypatch):
    root = tmp_path / "lib"
    path = _make(gen, lyrics, root, "mp3")
    original = path.read_bytes()
    normalizer, changes = run(root)
    calls = {"n": 0}

    def flaky(handle, data):
        calls["n"] += 1
        if calls["n"] == 1:  # la escritura falla a la mitad; la restauración funciona
            handle.write(data[:len(data) // 2])
            raise OSError(errno.EINVAL, "Invalid argument")  # error no fatal (EIO detiene todo)
        handle.write(data)
    monkeypatch.setattr(writer, "_write", flaky)
    session = normalizer.apply(changes, root)
    item = session.manifest["items"][0]
    assert item["status"] == backup.ITEM_FAILED and "se restauró el original" in item["error"]
    assert path.read_bytes() == original
    assert not pending_sessions(root)


@needs_ffmpeg
def test_revert_conflict_when_tags_changed(gen, lyrics, tmp_path, paths_mode):
    root = tmp_path / "lib"
    path = _make(gen, lyrics, root, "flac")
    session, _ = apply(root)
    from mutagen.flac import FLAC
    audio = FLAC(path)
    audio["TITLE"] = "Editado después"
    audio.save()
    edited = path.read_bytes()
    results = backup.revert(session.folder)
    assert {r.status for r in results} == {backup.REVERT_CONFLICT}
    assert path.read_bytes() == edited


@needs_ffmpeg
def test_manifest_records_patches_not_audio(gen, lyrics, tmp_path):
    root = tmp_path / "lib"
    _make(gen, lyrics, root, "mp3")
    session, _ = apply(root)
    manifest = session.manifest
    assert manifest["manifest_version"] == 3
    edit = manifest["edits"][0]
    assert edit["writer"] == "raw" and edit["mode"] == "inplace" and edit["status"] == "applied"
    patches = json.loads((session.folder / edit["patches"]).read_text(encoding="utf-8"))
    assert len(json.dumps(patches)) < 5_000  # letra y relleno; la portada de 300 KB no está
