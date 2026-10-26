import codecs

import pytest

from choconostle.models.track import Track
from choconostle.normalizer import (
    ENCODING_KEEP, ENCODING_UTF8, ENCODING_UTF8_BOM, MODE_STANDARDIZE, MODE_STRIP,
    LyricsEncodingError, build_headers, encode_lyrics_file, looks_like_latin_text,
    normalize_text, shift_line,
)

BODY = "[00:01.00]Uno\n[00:02.00]Dos\n[00:03.00]Tres\n"


def strip(text):
    return normalize_text(text, MODE_STRIP, [])


def test_strip_removes_headers_and_keeps_timestamps():
    result = strip("[ti:T]\n[ar:A]\n[by:B]\n[al:X]\n[length:03:00]\n[re:x]\n[ve:1]\n" + BODY)
    assert result.text == BODY
    assert result.removed_headers == ["ti", "ar", "by", "al", "length", "re", "ve"]
    assert result.synced


def test_strip_headers_anywhere_and_leading_blank_lines():
    result = strip("[ti:T]\n\n" + BODY + "[ar:A]\n")
    assert result.text == BODY


def test_section_labels_are_kept():
    text = "[Coro: Artista]\n" + BODY
    assert strip(text).text == text


def test_positive_offset_makes_lyrics_earlier():
    result = strip("[offset:+500]\n[00:01.00]Uno\n[00:03.20]Dos\n[01:00.00]Tres\n")
    assert result.text == "[00:00.50]Uno\n[00:02.70]Dos\n[00:59.50]Tres\n"
    assert result.offset_ms == 500
    assert result.shifted == 3


def test_negative_offset_makes_lyrics_later():
    result = strip("[offset:-1500]\n[00:59.00]Uno\n[00:02.00]Dos\n[00:03.00]Tres\n")
    assert result.text == "[01:00.50]Uno\n[00:03.50]Dos\n[00:04.50]Tres\n"


def test_offset_clamps_to_zero():
    result = strip("[offset:2000]\n[00:01.00]Uno\n[00:03.00]Dos\n[00:04.00]Tres\n")
    assert result.text.splitlines()[0] == "[00:00.00]Uno"
    assert result.clamped == 1


def test_offset_keeps_timestamp_style():
    line, shifted, _ = shift_line("[01:02.345][1:02:34]<01:02.345>Hola <01:03>mundo", 100)
    assert line == "[01:02.245][01:02:24]<01:02.245>Hola <01:02.90>mundo"
    assert shifted == 4


def test_offset_on_timestamp_without_fraction():
    assert shift_line("[00:05]x", 1000)[0] == "[00:04]x"
    assert shift_line("[00:05]x", 250)[0] == "[00:04.75]x"


def test_offset_does_not_touch_brackets_inside_text():
    assert shift_line("[00:05.00]Canción [1:30] en vivo", 1000)[0] == "[00:04.00]Canción [1:30] en vivo"


def test_invalid_offset_is_removed_without_shifting():
    result = strip("[offset:abc]\n" + BODY)
    assert result.text == BODY
    assert result.shifted == 0
    assert result.warnings


def test_unsynced_with_headers_only_loses_headers():
    result = strip("[ar:A]\nLínea uno\nLínea dos\nLínea tres\n")
    assert result.text == "Línea uno\nLínea dos\nLínea tres\n"
    assert not result.synced


def test_unsynced_without_headers_is_unchanged():
    text = "Línea uno\nLínea dos\nLínea tres"
    for mode in (MODE_STRIP, MODE_STANDARDIZE):
        assert normalize_text(text, mode, [("ar", "A")]).text == text


def test_offset_is_not_applied_to_unsynced_lyrics():
    result = strip("[offset:500]\nUno\nDos\nTres")
    assert result.text == "Uno\nDos\nTres"
    assert result.shifted == 0


def test_newlines_are_normalized():
    result = strip(BODY.replace("\n", "\r\n"))
    assert result.text == BODY
    assert result.newline == "CRLF"


def test_embedded_bom_char_is_removed():
    result = strip("﻿" + BODY)
    assert result.text == BODY
    assert result.removed_bom


def test_nearly_empty_is_untouched():
    text = "[ar:A]\n[offset:500]\n[00:00.00]Instrumental\n[00:10.00]\n"
    result = strip(text)
    assert result.nearly_empty
    assert result.text == text


def test_standardize_writes_fixed_block_without_duplicates():
    headers = [("ar", "Artista"), ("ti", "Título"), ("al", "Álbum"), ("length", "03:20")]
    text = "[ti:viejo]\n[ar:Artista]\n[by:LRCGet]\n[offset:+100]\n" + BODY
    result = normalize_text(text, MODE_STANDARDIZE, headers)
    assert result.text == (
        "[ar:Artista]\n[ti:Título]\n[al:Álbum]\n[length:03:20]\n"
        "[00:00.90]Uno\n[00:01.90]Dos\n[00:02.90]Tres\n"
    )
    # Idempotente: una segunda pasada no cambia nada.
    assert normalize_text(result.text, MODE_STANDARDIZE, headers).text == result.text


def test_standardize_adds_headers_to_synced_lyrics_without_headers():
    result = normalize_text(BODY, MODE_STANDARDIZE, [("ti", "T")])
    assert result.text == "[ti:T]\n" + BODY


def test_build_headers_never_invents_data():
    track = Track(filename="a.flac", filepath=None, extension=".flac", size=0)
    assert build_headers(track) == []
    track.title = "Título"
    track.duration = 200.4
    assert build_headers(track) == [("ti", "Título"), ("length", "03:20")]
    track.artist = "Línea\nrota"
    assert ("ar", "Línea rota") in build_headers(track)
    assert build_headers(None) == []


def test_encode_utf8_default_and_bom():
    assert encode_lyrics_file("ñ\n", ENCODING_UTF8, "utf-8", True)[0] == "ñ\n".encode()
    data, encoding, bom, _ = encode_lyrics_file("ñ\n", ENCODING_UTF8_BOM, "utf-8", False)
    assert data == codecs.BOM_UTF8 + "ñ\n".encode()
    assert bom


def test_encode_converts_cp1252_to_utf8():
    data, encoding, _, warnings = encode_lyrics_file("Canción ¿qué?\n", ENCODING_UTF8, "cp1252", False)
    assert data == "Canción ¿qué?\n".encode()
    assert not warnings


def test_encode_keep():
    assert encode_lyrics_file("Canción\n", ENCODING_KEEP, "cp1252", False)[0] == "Canción\n".encode("cp1252")
    data = encode_lyrics_file("x\n", ENCODING_KEEP, "utf-16-le", True)[0]
    assert data == codecs.BOM_UTF16_LE + "x\n".encode("utf-16-le")
    assert encode_lyrics_file("x\n", ENCODING_KEEP, "ascii", False)[0] == b"x\n"


def test_encode_keep_fails_when_text_does_not_fit():
    with pytest.raises(LyricsEncodingError):
        encode_lyrics_file("[ti:東京]\n", ENCODING_KEEP, "cp1252", False)


def test_unconfirmed_encoding_is_kept():
    # Bytes Shift-JIS leídos como Latin-1: no se convierten a UTF-8.
    mojibake = "東京の夜".encode("shift_jis").decode("latin-1")
    data, encoding, _, warnings = encode_lyrics_file(mojibake + "\n", ENCODING_UTF8, "latin-1", False)
    assert encoding == "latin-1"
    assert data == "東京の夜\n".encode("shift_jis")
    assert warnings


def test_looks_like_latin_text():
    assert looks_like_latin_text("Canción, acción, ¿qué?, ñandú, coração, œuvre")
    assert not looks_like_latin_text("ÄãºÃÃÃ")
    assert not looks_like_latin_text("‚ƒ")
