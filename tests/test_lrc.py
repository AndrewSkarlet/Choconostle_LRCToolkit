import codecs

from choconostle import lrc
from choconostle.models.lyrics import SOURCE_EMBEDDED, SOURCE_EXTERNAL

SYNCED_WITH_HEADERS = """[ar:Artista]
[ti:Título]
[al:Álbum]
[length:03:20]
[offset:+100]
[00:12.00]Hola
[00:15.50]Mundo
"""


def write(tmp_path, name, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_synced_with_headers(tmp_path):
    info = lrc.analyze_file(write(tmp_path, "a.lrc", SYNCED_WITH_HEADERS.encode("utf-8")))
    assert info.source == SOURCE_EXTERNAL
    assert info.synced
    assert info.timestamp_lines == 2
    assert info.headers == ["ar", "ti", "al", "length", "offset"]
    assert not info.has_bom
    assert info.is_utf8
    assert info.needs_fix


def test_clean_synced_lrc_needs_no_fix(tmp_path):
    info = lrc.analyze_file(write(tmp_path, "a.lrc", b"[00:01.00]Hola\n[00:02.50]Mundo\n"))
    assert info.synced
    assert info.headers == []
    assert not info.needs_fix


def test_txt_with_timestamps_is_synced(tmp_path):
    info = lrc.analyze_file(write(tmp_path, "a.txt", b"[00:01.00]Hola\n"))
    assert info.synced


def test_lrc_without_timestamps_is_unsynced(tmp_path):
    info = lrc.analyze_file(write(tmp_path, "a.lrc", b"Hola\nMundo\n"))
    assert not info.synced
    assert info.plain_lines == 2
    assert not info.empty


def test_timestamp_variants():
    text = "[00:01]a\n[01:02.345]b\n[1:02:34]c\n[00:01.00][00:30.00]coro\n[123:00.00]d"
    info = lrc.analyze_text(text, SOURCE_EXTERNAL, "x.lrc")
    assert info.timestamp_lines == 5
    assert info.plain_lines == 0


def test_section_labels_are_not_headers():
    text = "[Coro: Artista]\n[Verso 1]\nHola\n"
    info = lrc.analyze_text(text, SOURCE_EXTERNAL, "x.lrc")
    assert info.headers == []
    assert info.plain_lines == 3


def test_headers_are_case_insensitive_and_unique():
    info = lrc.analyze_text("[AR:a]\n[ar:b]\n[By:c]\n[00:01.00]x", SOURCE_EXTERNAL, "x.lrc")
    assert info.headers == ["ar", "by"]


def test_utf8_bom(tmp_path):
    info = lrc.analyze_file(write(tmp_path, "a.lrc", codecs.BOM_UTF8 + b"[00:01.00]Hola"))
    assert info.has_bom
    assert info.is_utf8
    assert info.synced
    assert info.needs_fix


def test_utf16_bom(tmp_path):
    data = codecs.BOM_UTF16_LE + "[00:01.00]Canción".encode("utf-16-le")
    info = lrc.analyze_file(write(tmp_path, "a.lrc", data))
    assert info.has_bom
    assert info.encoding == "utf-16-le"
    assert not info.is_utf8
    assert info.synced


def test_utf16_without_bom(tmp_path):
    info = lrc.analyze_file(write(tmp_path, "a.lrc", "[00:01.00]Hola mundo".encode("utf-16-le")))
    assert info.encoding == "utf-16-le"
    assert not info.has_bom
    assert info.synced


def test_windows_1252(tmp_path):
    info = lrc.analyze_file(write(tmp_path, "a.lrc", "[00:01.00]Canción".encode("cp1252")))
    assert info.encoding == "cp1252"
    assert not info.is_utf8
    assert info.synced
    assert info.needs_fix


def test_ascii_counts_as_utf8(tmp_path):
    info = lrc.analyze_file(write(tmp_path, "a.lrc", b"[00:01.00]Hello"))
    assert info.encoding == "ascii"
    assert info.is_utf8


def test_empty_file(tmp_path):
    info = lrc.analyze_file(write(tmp_path, "a.lrc", b""))
    assert info.empty
    assert not info.synced


def test_headers_only_is_empty(tmp_path):
    info = lrc.analyze_file(write(tmp_path, "a.lrc", b"[ar:Artista]\n[ti:Titulo]\n"))
    assert info.empty
    assert info.headers == ["ar", "ti"]


def test_missing_file(tmp_path):
    info = lrc.analyze_file(tmp_path / "no-existe.lrc")
    assert info.error


def test_embedded_text_with_bom():
    info = lrc.analyze_embedded("\ufeff[00:01.00]Hola", "LYRICS")
    assert info.source == SOURCE_EMBEDDED
    assert info.has_bom
    assert info.synced


def test_sylt_frame():
    info = lrc.analyze_synced_frame([("Hola", 1000), ("Mundo", 2000)], "SYLT", "utf-8")
    assert info.synced
    assert info.timestamp_lines == 2
    assert info.headers == []
