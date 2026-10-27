import codecs
import json
import os

import pytest
from mutagen.id3 import ID3, TXXX
from mutagen.mp4 import MP4
from mutagen.wave import WAVE

from builders import add_id3, audio_payload, ffmpeg, has_encoder, make_flac, make_mp3, make_wav, needs_ffmpeg
from choconostle import backup
from choconostle.config import BACKUP_DIR_NAME
from choconostle.normalizer import (
    ENCODING_KEEP, MODE_STANDARDIZE, MODE_STRIP, STATUS_CHANGE, STATUS_SKIPPED,
    LyricsNormalizer, SelectionError, select,
)
from choconostle.scanner import scan_directory

LRC = "[ti:Uno]\n[ar:Artista]\n[by:LRCGet]\n[offset:+500]\n[00:01.00]Primera\n[00:03.20]Segunda\n[00:05.00]Tercera\n"
PAYLOAD = bytes(range(256)) * 8


@pytest.fixture
def library(tmp_path):
    """Reproduce el caso real: la letra 3 veces (LYRICS, UNSYNCEDLYRICS y .lrc) con cabeceras."""
    root = tmp_path / "Música"
    album = root / "Artista - Álbum"
    make_flac(album / "01 Uno.flac", payload=PAYLOAD, tags={
        "TITLE": "Uno", "ARTIST": "Artista", "ALBUM": "Álbum",
        "LYRICS": LRC, "UNSYNCEDLYRICS": LRC, "GENRE": "Rock",
    })
    (album / "01 Uno.lrc").write_bytes(codecs.BOM_UTF8 + LRC.replace("\n", "\r\n").encode())

    # MP3 con ID3 2.3: USLT en Latin-1, SYLT y TXXX:LYRICS.
    mp3 = make_mp3(album / "02 Dos.mp3")
    add_id3(mp3, title="Dos", artist="Artista",
            uslt="[ar:Artista]\n[00:01.00]a\n[00:02.00]b\n[00:03.00]c", uslt_encoding=0,
            sylt=[("[ti:Dos]", 0), ("a", 1000), ("b", 2000), ("c", 3000)])
    tags = ID3(mp3)
    tags.add(TXXX(encoding=3, desc="LYRICS", text=["[by:x]\n[00:01.00]a\n[00:02.00]b\n[00:03.00]c"]))
    tags.save(mp3, v2_version=3)

    # Sin álbum ni artista: --standardize-headers no debe inventarlos.
    make_flac(album / "03 Tres.flac", tags={"TITLE": "Tres", "LYRICS": "[by:x]\n" + LRC.split("\n", 4)[4]})

    # Casi vacía, sin sincronizar y huérfana.
    make_flac(album / "04 Cuatro.flac", tags={"LYRICS": "[ar:A]\n[00:00.00]Instrumental"})
    make_flac(album / "05 Cinco.flac")
    (album / "05 Cinco.txt").write_bytes("[ar:Artista]\nCanción sin tiempos\nLínea dos\nLínea tres\n".encode("cp1252"))
    (root / "Otra" / "huérfana.lrc").parent.mkdir(parents=True)
    (root / "Otra" / "huérfana.lrc").write_bytes(b"[ar:x]\n[00:01.00]a\n[00:02.00]b\n[00:03.00]c\n")

    # WAV con ID3 (las letras incrustadas en WAV son poco comunes pero existen).
    wav = make_wav(root / "Otra" / "06 Seis.wav")
    audio = WAVE(wav)
    audio.add_tags()
    from mutagen.id3 import USLT
    audio.tags.add(USLT(encoding=3, lang="spa", desc="", text="[ti:Seis]\n[00:01.00]a\n[00:02.00]b\n[00:03.00]c"))
    audio.save()
    return root


def snapshot(root):
    """Estado comparable de la biblioteca: bytes de letras y etiquetas de audio."""
    state = {}
    for path in sorted(root.rglob("*")):
        if BACKUP_DIR_NAME in path.parts or path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() in (".lrc", ".txt"):
            state[relative] = (path.read_bytes(), path.stat().st_mtime)
        else:
            import mutagen
            audio = mutagen.File(path)
            if audio is None:  # Matroska: mutagen no lo lee
                state[relative] = path.read_bytes()
                continue
            tags = audio.tags
            if tags is None:
                state[relative] = None
            elif isinstance(tags, ID3):
                state[relative] = (tags.version, sorted((key, repr(frame)) for key, frame in tags.items()))
            else:
                state[relative] = list(tags.items()) if not isinstance(tags, list) else list(tags)
            if path.suffix in (".flac", ".mp3"):
                state[relative + "#audio"] = audio_payload(path)
    return state


def run(root, mode=MODE_STRIP, encoding=ENCODING_KEEP, only=None):
    scan = scan_directory(root)
    tracks, orphans = select(scan, only or [])
    normalizer = LyricsNormalizer(mode, encoding)
    changes = normalizer.plan(scan, tracks, orphans)
    return normalizer, changes


def by_label(changes):
    return {(change.path.name, change.label): change for change in changes}


def test_simulation_changes_nothing(library):
    before = snapshot(library)
    _normalizer, changes = run(library)
    assert any(change.status == STATUS_CHANGE for change in changes)
    assert snapshot(library) == before
    assert not (library / BACKUP_DIR_NAME).exists()


def test_plan_covers_every_copy(library):
    _normalizer, changes = run(library)
    changes = by_label(changes)
    for key in [("01 Uno.lrc", "01 Uno.lrc"), ("01 Uno.flac", "LYRICS"), ("01 Uno.flac", "UNSYNCEDLYRICS"),
                ("02 Dos.mp3", "USLT"), ("02 Dos.mp3", "SYLT"), ("02 Dos.mp3", "TXXX:LYRICS"),
                ("05 Cinco.txt", "05 Cinco.txt"), ("huérfana.lrc", "huérfana.lrc"), ("06 Seis.wav", "USLT")]:
        assert changes[key].status == STATUS_CHANGE, key
    # Casi vacía: se procesa con un aviso.
    cuatro = changes[("04 Cuatro.flac", "LYRICS")]
    assert cuatro.status == STATUS_CHANGE and cuatro.nearly_empty
    assert any("Casi vacía" in warning for warning in cuatro.warnings)


def test_apply_strip(library):
    before = snapshot(library)
    normalizer, changes = run(library)
    session = normalizer.apply(changes, library)
    assert all(item["status"] == backup.ITEM_APPLIED for item in session.manifest["items"])

    expected = "[00:00.50]Primera\n[00:02.70]Segunda\n[00:04.50]Tercera\n"
    album = library / "Artista - Álbum"
    # Se conservan el BOM y los saltos CRLF del archivo.
    assert (album / "01 Uno.lrc").read_bytes() == codecs.BOM_UTF8 + expected.replace("\n", "\r\n").encode()
    from mutagen.flac import FLAC
    flac = FLAC(album / "01 Uno.flac")
    assert flac["LYRICS"] == [expected]
    assert flac["UNSYNCEDLYRICS"] == [expected]
    assert flac["GENRE"] == ["Rock"]
    assert audio_payload(album / "01 Uno.flac") == before["Artista - Álbum/01 Uno.flac#audio"]

    id3 = ID3(album / "02 Dos.mp3")
    assert id3.version == (2, 3, 0)
    assert id3.getall("USLT")[0].text == "[00:01.00]a\n[00:02.00]b\n[00:03.00]c"
    assert [text for text, _ in id3.getall("SYLT")[0].text] == ["a", "b", "c"]
    assert id3.getall("TXXX:LYRICS")[0].text == ["[00:01.00]a\n[00:02.00]b\n[00:03.00]c"]
    assert audio_payload(album / "02 Dos.mp3") == before["Artista - Álbum/02 Dos.mp3#audio"]

    # Windows-1252: se conserva la codificación.
    assert (album / "05 Cinco.txt").read_bytes() == \
        "Canción sin tiempos\nLínea dos\nLínea tres\n".encode("cp1252")
    assert FLAC(album / "04 Cuatro.flac")["LYRICS"] == ["[00:00.00]Instrumental"]

    # Segunda pasada: nada que cambiar. El escáner ignora la carpeta de respaldo.
    scan = scan_directory(library)
    assert all(BACKUP_DIR_NAME not in str(lyrics.location) for lyrics in scan.orphan_lyrics)
    _normalizer, again = run(library)
    assert not [change for change in again if change.status == STATUS_CHANGE]


def test_backup_contents(library):
    normalizer, changes = run(library)
    session = normalizer.apply(changes, library)
    folder = session.folder
    assert folder.parent == library / BACKUP_DIR_NAME
    manifest = json.loads((folder / backup.MANIFEST_NAME).read_text(encoding="utf-8"))
    items = manifest["items"]
    assert len(items) == len([c for c in changes if c.status == STATUS_CHANGE])
    for item in items:
        assert (folder / item["original_copy"]).is_file()
    lrc_item = next(item for item in items if item["path"].endswith("01 Uno.lrc"))
    assert (folder / lrc_item["original_copy"]).read_bytes().startswith(codecs.BOM_UTF8)
    log = (folder / backup.LOG_NAME).read_text(encoding="utf-8")
    assert "choconostle revert" in log and "-[ti:Uno]" in log
    # No se copian archivos de audio.
    assert not [p for p in folder.rglob("*") if p.suffix in (".flac", ".mp3", ".wav")]


@pytest.mark.parametrize("mode", [MODE_STRIP, MODE_STANDARDIZE])
def test_apply_then_revert_is_identical(library, mode):
    before = snapshot(library)
    normalizer, changes = run(library, mode=mode)
    session = normalizer.apply(changes, library)
    assert snapshot(library) != before

    results = backup.revert(session.folder)
    assert {result.status for result in results} == {backup.REVERT_RESTORED}
    assert snapshot(library) == before

    # Revertir otra vez no hace nada.
    again = backup.revert(session.folder)
    assert {result.status for result in again} == {backup.REVERT_ALREADY}


def test_standardize_uses_tags_only(library):
    normalizer, changes = run(library, mode=MODE_STANDARDIZE)
    changes = by_label(changes)
    uno = changes[("01 Uno.flac", "LYRICS")].new_text
    assert uno.startswith("[ar:Artista]\n[ti:Uno]\n[al:Álbum]\n[length:00:01]\n[00:00.50]Primera")
    assert "[by:" not in uno and "[offset:" not in uno
    tres = changes[("03 Tres.flac", "LYRICS")].new_text
    assert tres.startswith("[ti:Tres]\n[length:00:01]\n[00:01.00]")  # sin [ar:] ni [al:]
    assert changes[("huérfana.lrc", "huérfana.lrc")].status == STATUS_SKIPPED


def test_revert_conflict_and_force(library):
    normalizer, changes = run(library)
    session = normalizer.apply(changes, library)
    lrc = library / "Artista - Álbum" / "01 Uno.lrc"
    lrc.write_text("editado a mano\n", encoding="utf-8")

    results = backup.revert(session.folder)
    conflict = [r for r in results if r.item["path"].endswith("01 Uno.lrc")][0]
    assert conflict.status == backup.REVERT_CONFLICT
    assert lrc.read_text(encoding="utf-8") == "editado a mano\n"

    backup.revert(session.folder, force=True)
    assert lrc.read_bytes().startswith(codecs.BOM_UTF8)


def test_revert_dry_run_changes_nothing(library):
    normalizer, changes = run(library)
    session = normalizer.apply(changes, library)
    after = snapshot(library)
    results = backup.revert(session.folder, dry_run=True)
    assert {r.status for r in results} == {backup.REVERT_RESTORED}
    assert snapshot(library) == after


def test_revert_restores_mtime(library):
    lrc = library / "Artista - Álbum" / "01 Uno.lrc"
    os.utime(lrc, (1_600_000_000, 1_600_000_000))
    normalizer, changes = run(library)
    session = normalizer.apply(changes, library)
    backup.revert(session.folder)
    assert lrc.stat().st_mtime == 1_600_000_000


def test_apply_skips_files_changed_after_plan(library):
    normalizer, changes = run(library)
    lrc = library / "Artista - Álbum" / "01 Uno.lrc"
    lrc.write_text("cambiado\n", encoding="utf-8")
    session = normalizer.apply(changes, library)
    item = next(i for i in session.manifest["items"] if i["path"].endswith("01 Uno.lrc"))
    assert item["status"] == backup.ITEM_FAILED
    assert lrc.read_text(encoding="utf-8") == "cambiado\n"


def test_encoding_utf8_conversion(library):
    _normalizer, changes = run(library, encoding="utf8")
    changes = by_label(changes)
    # Quita el BOM, pero los saltos CRLF no se tocan (eso es convert-lyrics --eol).
    assert changes[("01 Uno.lrc", "01 Uno.lrc")].new_bytes == \
        "[00:00.50]Primera\r\n[00:02.70]Segunda\r\n[00:04.50]Tercera\r\n".encode()
    assert "quita BOM" in changes[("01 Uno.lrc", "01 Uno.lrc")].details
    # Windows-1252 frente a Windows-1250 es ambiguo: no se convierte.
    cinco = changes[("05 Cinco.txt", "05 Cinco.txt")]
    assert cinco.status == STATUS_SKIPPED and "--source-encoding" in cinco.message


def test_only_folder_and_album(library):
    _normalizer, changes = run(library, only=["Otra"])
    assert {change.path.name for change in changes} == {"huérfana.lrc", "06 Seis.wav"}
    _normalizer, changes = run(library, only=["álbum"])
    assert {change.path.name for change in changes} == {"01 Uno.lrc", "01 Uno.flac"}
    with pytest.raises(SelectionError):
        run(library, only=["No existe"])


@needs_ffmpeg
def test_m4a_and_wavpack_apply_and_revert(tmp_path):
    if not (has_encoder("alac") and has_encoder("wavpack")):
        pytest.skip("ffmpeg sin alac o wavpack")
    root = tmp_path / "lib"
    m4a = ffmpeg(root / "a.m4a", "-c:a", "alac")
    audio = MP4(m4a)
    audio["\xa9lyr"] = ["[ti:x]\r\n[00:01.00]a\r\n[00:02.00]b\r\n[00:03.00]c"]
    audio["\xa9nam"] = ["Título"]
    audio.save()
    wv = ffmpeg(root / "b.wv", "-c:a", "wavpack")
    from mutagen.wavpack import WavPack
    audio = WavPack(wv)
    if audio.tags is None:
        audio.add_tags()
    audio["Lyrics"] = "[ar:x]\n[00:01.00]a\n[00:02.00]b\n[00:03.00]c"
    audio.save()
    mka = ffmpeg(root / "c.mka", "-c:a", "flac", "-metadata", "LYRICS=[ar:x]\n[00:01.00]a\n[00:02.00]b\n[00:03.00]c")

    before = snapshot(root)
    normalizer, changes = run(root)
    changes_by = by_label(changes)
    assert changes_by[("a.m4a", "\xa9lyr")].new_text == "[00:01.00]a\r\n[00:02.00]b\r\n[00:03.00]c"
    assert changes_by[("b.wv", "Lyrics")].status == STATUS_CHANGE
    assert changes_by[(mka.name, "(incrustada)")].status == STATUS_SKIPPED
    session = normalizer.apply(changes, root)
    assert MP4(m4a)["\xa9lyr"] == ["[00:01.00]a\r\n[00:02.00]b\r\n[00:03.00]c"]
    assert MP4(m4a)["\xa9nam"] == ["Título"]
    backup.revert(session.folder)
    assert snapshot(root) == before
