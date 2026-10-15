import codecs

import pytest

from builders import JPEG, add_id3, make_flac, make_mp3, make_wav
from choconostle.albums import GROUP_BY_FOLDER, GROUP_BY_TAG, group_albums
from choconostle.report import build_report
from choconostle.scanner import scan_directory


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "Música"

    # Álbum A: portada de carpeta, letras externas, una pista MP3 (formatos mezclados).
    a = root / "Artista - Álbum A"
    make_flac(a / "01 Uno.flac", tags={"ALBUM": "Álbum A", "ARTIST": "Artista"})
    (a / "01 Uno.lrc").write_bytes(codecs.BOM_UTF8 + b"[ar:Artista]\n[00:01.00]Hola\n")
    make_flac(a / "02 Dos.flac", tags={"ALBUM": "Álbum A", "ARTIST": "Artista"})
    (a / "02 Dos.TXT").write_bytes(b"[00:01.00]Sincronizada en txt\n")
    make_flac(a / "03 Tres.flac", tags={"ALBUM": "Álbum A", "ARTIST": "Artista"})
    (a / "03 Tres.lrc").write_bytes("Sin marcas de tiempo, Canción".encode("cp1252"))
    make_mp3(a / "04 Cuatro.mp3")
    add_id3(a / "04 Cuatro.mp3", album="Álbum A", artist="Artista")
    (a / "Cover.JPG").write_bytes(JPEG)

    # Álbum B: dos discos con calidad distinta, folder.jpg en la carpeta padre.
    b = root / "Álbum B"
    make_flac(b / "CD1" / "01.flac", bits=16, rate=44100, tags={"ALBUM": "Álbum B"})
    make_flac(b / "CD2" / "01.flac", bits=24, rate=96000, tags={"ALBUM": "Álbum B"})
    (b / "folder.jpg").write_bytes(JPEG)

    # Álbum C: WAV sin portada, .lrc huérfano y un .txt que no es letra.
    c = root / "Álbum C"
    make_wav(c / "01.wav")
    (c / "huérfano.lrc").write_bytes(b"[00:01.00]x")
    (c / "notas.txt").write_bytes(b"info")
    (c / "pista.wma").write_bytes(b"x")

    # Álbum D: solo portada incrustada (no cuenta como sin portada).
    make_flac(root / "Álbum D" / "01.flac", picture=True)

    # Ocultos e AppleDouble: se ignoran.
    make_flac(root / ".oculta" / "x.flac")
    (a / "._01 Uno.flac").write_bytes(b"\x00" * 10)

    return root


def by_name(scan):
    return {track.filepath.relative_to(scan.root).as_posix(): track for track in scan.tracks}


def test_scan_finds_tracks_and_lyrics(library):
    scan = scan_directory(library)
    tracks = by_name(scan)
    assert len(tracks) == 8
    assert not any(track.error for track in scan.tracks)

    uno = tracks["Artista - Álbum A/01 Uno.flac"]
    assert uno.lyrics_status == "synced"
    assert uno.lyrics[0].has_bom
    assert uno.lyrics[0].headers == ["ar"]
    assert uno.folder_cover.name == "Cover.JPG"

    dos = tracks["Artista - Álbum A/02 Dos.flac"]
    assert dos.lyrics_status == "synced"

    tres = tracks["Artista - Álbum A/03 Tres.flac"]
    assert tres.lyrics_status == "unsynced"
    assert tres.lyrics[0].encoding == "cp1252"

    assert tracks["Álbum C/01.wav"].lyrics_status == "none"
    assert tracks["Álbum B/CD2/01.flac"].folder_cover.name == "folder.jpg"


def test_scan_orphans_and_unsupported(library):
    scan = scan_directory(library)
    assert [lyrics.location.endswith("huérfano.lrc") for lyrics in scan.orphan_lyrics] == [True]
    assert [path.name for path in scan.unmatched_txt] == ["notas.txt"]
    assert [path.name for path in scan.unsupported_audio] == ["pista.wma"]


def test_scan_includes_hidden_on_request(library):
    scan = scan_directory(library, include_hidden=True)
    names = {track.filename for track in scan.tracks}
    assert "x.flac" in names


def test_albums_by_folder(library):
    scan = scan_directory(library)
    albums = {album.name: album for album in group_albums(scan, GROUP_BY_FOLDER)}
    assert set(albums) == {"Artista - Álbum A", "Álbum B", "Álbum C", "Álbum D"}

    assert albums["Artista - Álbum A"].has_mixed_formats
    # FLAC 16 bits + MP3: la calidad también cuenta como mezclada.
    assert albums["Artista - Álbum A"].has_mixed_quality

    assert len(albums["Álbum B"].tracks) == 2
    assert albums["Álbum B"].has_mixed_quality
    assert not albums["Álbum B"].has_mixed_formats
    assert not albums["Álbum B"].missing_cover

    assert albums["Álbum C"].missing_cover
    assert not albums["Álbum D"].missing_cover


def test_albums_by_tag(library):
    scan = scan_directory(library)
    names = {album.name for album in group_albums(scan, GROUP_BY_TAG)}
    # Sin etiqueta de álbum se agrupa por carpeta (Álbum C y Álbum D).
    assert names == {"Álbum A", "Álbum B", "Álbum C", "Álbum D"}


def test_albums_by_tag_uses_album_artist(tmp_path):
    root = tmp_path / "lib"
    # Compilación: artistas distintos, mismo artista del álbum.
    make_flac(root / "x" / "01.flac", tags={"ALBUM": "Éxitos", "ARTIST": "A", "ALBUMARTIST": "Varios"})
    make_flac(root / "y" / "02.flac", tags={"ALBUM": "Éxitos", "ARTIST": "B", "ALBUMARTIST": "Varios"})
    # Mismo nombre de álbum, otro artista del álbum: álbum distinto.
    make_flac(root / "z" / "01.flac", tags={"ALBUM": "Éxitos", "ALBUMARTIST": "Otro"})
    albums = {album.name: album for album in group_albums(scan_directory(root), GROUP_BY_TAG)}
    assert set(albums) == {"Varios - Éxitos", "Otro - Éxitos"}
    assert len(albums["Varios - Éxitos"].tracks) == 2


def test_report(library):
    report = build_report(scan_directory(library))
    summary = report["summary"]
    assert summary["tracks"] == 8
    assert summary["albums_by_folder"] == 4
    assert summary["albums_by_tag"] == 4
    assert summary["lyrics_synced"] == 2
    assert summary["lyrics_unsynced"] == 1
    assert summary["lyrics_none"] == 5
    assert summary["albums_mixed_formats"] == 1
    assert summary["albums_mixed_quality"] == 2
    assert summary["albums_missing_cover"] == 1
    assert summary["orphan_lrc"] == 1
    assert summary["unsupported_audio"] == 1

    assert report["lyrics_issues"]["with_headers"] == 1
    assert report["lyrics_issues"]["with_bom"] == 1
    assert report["lyrics_issues"]["not_utf8"] == 1
    assert report["lyrics_found"]["txt"] == {"synced": 1}
    fix_locations = {item["location"] for item in report["lyrics_to_fix"]}
    assert fix_locations == {"Artista - Álbum A/01 Uno.lrc", "Artista - Álbum A/03 Tres.lrc"}
    assert report["no_embedded_lyrics_support"]["by_format"] == {"PCM (WAV)": 1}


def test_scan_rejects_missing_folder(tmp_path):
    with pytest.raises(NotADirectoryError):
        scan_directory(tmp_path / "no-existe")
