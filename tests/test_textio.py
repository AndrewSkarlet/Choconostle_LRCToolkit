import codecs

import pytest

from choconostle.textio import (
    EncodingOptionError, UnencodableError, decode_lyrics, detect_encoding, diff_lines,
    encode_text, eol_summary, find_mojibake, join_lines, parse_target_encoding, split_lines,
    visible,
)

LYRICS = "[ti:Canción]\r\n[00:01.00]Uno\n[00:02.00]Dos\r[00:03.00]Tres"


def test_split_lines_keeps_delimiters():
    lines = split_lines(LYRICS)
    assert [eol for _content, eol in lines] == ["\r\n", "\n", "\r", ""]
    assert join_lines(lines) == LYRICS
    assert split_lines("a b\x85c\n") == [("a b\x85c", "\n")]
    assert split_lines("") == []


def test_eol_summary():
    assert eol_summary("a\nb\n") == "LF"
    assert eol_summary("a\r\nb\n") == "mixtos (CRLF, LF)"
    assert eol_summary("a") == "-"


@pytest.mark.parametrize("encoding,bom", [
    ("utf-8", b""), ("utf-8", codecs.BOM_UTF8), ("utf-16-le", codecs.BOM_UTF16_LE),
    ("utf-16-be", codecs.BOM_UTF16_BE), ("utf-16-le", b""), ("utf-32-le", codecs.BOM_UTF32_LE),
])
def test_decode_is_reversible_and_exact(encoding, bom):
    data = bom + LYRICS.encode(encoding)
    decoded = decode_lyrics(data)
    assert decoded.exact
    assert decoded.bom == bom
    assert decoded.encode(decoded.text) == data
    assert decoded.text == LYRICS


@pytest.mark.parametrize("encoding", ["cp1252", "shift_jis", "gbk", "euc_kr", "cp1251"])
def test_8bit_files_use_byte_transparent_view(encoding):
    text = {"cp1252": "Canción ñandú", "shift_jis": "東京の夜", "gbk": "这是第一行",
            "euc_kr": "첫 번째 줄", "cp1251": "Последняя строка"}[encoding]
    data = f"[ti:x]\n[00:01.00]{text}\n".encode(encoding)
    decoded = decode_lyrics(data)
    assert not decoded.exact
    assert decoded.encode(decoded.text) == data


def test_detection_confident_and_ambiguous():
    japanese = ("[00:01.00]これはテストの最初の行です\n[00:04.50]二行目：ひらがなとカタカナ\n"
                "[00:08.20]三行目の歌詞\n").encode("shift_jis")
    detection = detect_encoding(japanese)
    assert detection.confident
    assert japanese.decode(detection.encoding) == japanese.decode("shift_jis")
    # Windows-1252 frente a Windows-1250: "ñ" o "ń" son igual de probables.
    spanish = "[00:01.00]Sigue la canción con acentos: ñandú, pingüino\n".encode("cp1252")
    ambiguous = detect_encoding(spanish)
    assert not ambiguous.confident
    assert "ambigua" in ambiguous.describe()


def test_utf16_with_invalid_bytes_raises():
    from choconostle.textio import LyricsDecodeError
    with pytest.raises(LyricsDecodeError):
        decode_lyrics(codecs.BOM_UTF16_LE + b"\x00\xd8a\x00")  # surrogate suelto


def test_parse_target_encoding():
    assert parse_target_encoding("keep") is None
    assert parse_target_encoding("utf8").bom == b""
    assert parse_target_encoding("utf8-bom").bom == codecs.BOM_UTF8
    assert parse_target_encoding("Shift_JIS").codec == "shift_jis"
    assert parse_target_encoding("cp1252").codec == "cp1252"
    with pytest.raises(EncodingOptionError):
        parse_target_encoding("no-existe")
    with pytest.raises(EncodingOptionError):
        parse_target_encoding("rot13")


def test_encode_text_never_substitutes():
    target = parse_target_encoding("cp1252")
    assert encode_text("Canción", target) == "Canción".encode("cp1252")
    with pytest.raises(UnencodableError) as error:
        encode_text("Canción 東京 東", target)
    assert error.value.chars == ["東", "京"]
    assert error.value.count == 3
    assert "?" not in str(error.value).split(":")[0]


def test_find_mojibake():
    assert find_mojibake("CanciÃ³n de prueba, Ã±andÃº")[0] == ("Ã³", "ó")
    assert find_mojibake("Canción ñandú, coração, Ärger") == []


def test_visible_and_diff():
    assert visible("a​b﻿ \t") == "a⟨U+200B⟩b⟨U+FEFF⟩⟨U+00A0⟩\t"
    lines = diff_lines("​[ti:x]\nUno\n", "Uno\n")
    assert "-⟨U+200B⟩[ti:x]" in lines
