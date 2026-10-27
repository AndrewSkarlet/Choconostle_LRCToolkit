from choconostle.models.track import Track
from choconostle.normalizer import (
    MODE_STANDARDIZE, MODE_STRIP, OFFSET_FIRST, OFFSET_LAST, OFFSET_SUM, build_headers,
    header_lines, normalize_sylt, normalize_text, parse_offset, shift_line,
)

BODY = "[00:01.00]Uno\n[00:02.00]Dos\n[00:03.00]Tres\n"


def strip(text, **options):
    return normalize_text(text, MODE_STRIP, **options)


def test_strip_removes_headers_and_keeps_timestamps():
    result = strip("[ti:T]\n[ar:A]\n[by:B]\n[al:X]\n[length:03:00]\n[re:x]\n[ve:1]\n" + BODY)
    assert result.text == BODY
    assert result.removed_headers == ["ti", "ar", "by", "al", "length", "re", "ve"]
    assert result.synced and result.changed


def test_lr_and_hash_are_known_headers():
    result = strip("[lr:Letrista]\n[hash:abc123]\n" + BODY)
    assert result.text == BODY
    assert result.removed_headers == ["lr", "hash"]


def test_strip_headers_anywhere_and_leading_blank_lines():
    result = strip("[ti:T]\n\n" + BODY + "[ar:A]\n")
    assert result.text == BODY


def test_blank_lines_inside_lyrics_are_kept():
    text = "[ti:T]\n\n\n[00:01.00]Uno\n\n[00:02.00]Dos\n\n\n[00:03.00]Tres\n"
    assert strip(text).text == "[00:01.00]Uno\n\n[00:02.00]Dos\n\n\n[00:03.00]Tres\n"


def test_no_headers_means_no_change():
    result = strip(BODY)
    assert not result.changed
    assert result.text == BODY


# --- Saltos de línea y caracteres ------------------------------------------

def test_crlf_cr_and_mixed_newlines_are_preserved():
    for eol in ("\r\n", "\r"):
        text = f"[ti:T]{eol}" + BODY.replace("\n", eol)
        assert strip(text).text == BODY.replace("\n", eol)
    mixed = "[ti:T]\r\n[ar:A]\n\r\n[00:01.00]Uno\r[00:02.00]Dos\n[00:03.00]Tres\r\n[00:04.00]Cuatro"
    assert strip(mixed).text == "[00:01.00]Uno\r[00:02.00]Dos\n[00:03.00]Tres\r\n[00:04.00]Cuatro"


def test_unicode_line_separators_are_content():
    # U+2028, U+0085 y \x0c no son saltos de línea en LRC.
    text = "[ti:T]\n[00:01.00]Uno sigue\n[00:02.00]Dos\x85\n[00:03.00]Tres\x0c\n"
    result = strip(text)
    assert result.text == "[00:01.00]Uno sigue\n[00:02.00]Dos\x85\n[00:03.00]Tres\x0c\n"
    assert result.content_lines == 3


def test_invisible_prefix_removed_only_with_header():
    for char in "​﻿‎‏⁠":
        result = strip(f"{char}[ti:T]\n" + BODY)
        assert result.text == BODY, repr(char)
    # En la letra no se tocan.
    text = "[ti:T]\n[00:01.00]Uno​\n​[00:02.00]Dos\n[00:03.00]Tres﻿\n"
    assert strip(text).text == "[00:01.00]Uno​\n​[00:02.00]Dos\n[00:03.00]Tres﻿\n"


def test_leading_feff_kept_when_not_followed_by_header():
    text = "﻿" + BODY
    result = strip(text)
    assert not result.changed
    assert result.text == text


def test_spaces_inside_brackets_are_not_headers():
    text = "[ ti : Con espacios ]\n" + BODY
    result = strip(text)
    assert result.text == text
    assert result.removed_headers == []


def test_section_labels_are_kept():
    text = "[Coro: Artista]\n" + BODY
    result = strip(text)
    assert result.text == text
    assert result.unknown_headers == ["Coro"]
    assert strip("[00:00.50]x\n[Coro: Artista]\n" + BODY).unknown_headers == []


# --- Cabeceras desconocidas --------------------------------------------------

def test_unknown_headers_kept_by_default_and_listed():
    text = "[ti:T]\n[xtrack:7]\n\n" + BODY
    result = strip(text)
    assert result.text == "[xtrack:7]\n\n" + BODY
    assert result.unknown_headers == ["xtrack"]


def test_strip_unknown_headers_only_in_initial_block():
    text = "[xtrack:7]\n[ti:T]\n\n" + BODY + "[otra:cosa]\n"
    result = strip(text, strip_unknown=True)
    assert result.text == BODY + "[otra:cosa]\n"
    assert result.removed_unknown == ["xtrack"]


# --- Offsets --------------------------------------------------------------

def test_positive_offset_makes_lyrics_earlier():
    result = strip("[offset:+500]\n[00:01.00]Uno\n[00:03.20]Dos\n[01:00.00]Tres\n")
    assert result.text == "[00:00.50]Uno\n[00:02.70]Dos\n[00:59.50]Tres\n"
    assert result.offset_ms == 500
    assert result.shifted == 3


def test_negative_offset_makes_lyrics_later():
    result = strip("[offset:-1500]\n[00:59.00]Uno\n[00:02.00]Dos\n[00:03.00]Tres\n")
    assert result.text == "[01:00.50]Uno\n[00:03.50]Dos\n[00:04.50]Tres\n"


def test_offset_clamps_to_zero_with_warning():
    result = strip("[offset:2000]\n[00:01.00]Uno\n[00:03.00]Dos\n[00:04.00]Tres\n")
    assert result.text.split("\n")[0] == "[00:00.00]Uno"
    assert result.clamped == 1
    assert any("00:00" in warning for warning in result.warnings)


def test_offset_applies_to_word_timestamps_and_keeps_crlf():
    text = "[offset:+500]\r\n[00:01.00]<00:01.00>Uno <00:01.40>dos\r\n[00:02.00]b\r\n[00:03.00]c\r\n"
    assert strip(text).text == "[00:00.50]<00:00.50>Uno <00:00.90>dos\r\n[00:01.50]b\r\n[00:02.50]c\r\n"


def test_offset_keeps_timestamp_style():
    line, shifted, _ = shift_line("[01:02.345][1:02:34]<01:02.345>Hola <01:03>mundo", 100)
    assert line == "[01:02.245][01:02:24]<01:02.245>Hola <01:02.90>mundo"
    assert shifted == 4


def test_offset_on_timestamp_without_fraction():
    assert shift_line("[00:05]x", 1000)[0] == "[00:04]x"
    assert shift_line("[00:05]x", 250)[0] == "[00:04.75]x"


def test_parse_offset():
    assert parse_offset("+500") == 500
    assert parse_offset(" -300 ") == -300
    assert parse_offset("250") == 250
    assert parse_offset("medio segundo") is None
    assert parse_offset("") is None
    assert parse_offset("1.5") is None


def test_invalid_offset_is_never_applied():
    text = "[ti:T]\n[offset:medio segundo]\n" + BODY
    for policy in ("skip", OFFSET_FIRST, OFFSET_LAST, OFFSET_SUM):
        result = strip(text, offset_policy=policy)
        assert result.decision and "inválido" in result.decision
        assert result.text == text and not result.changed


def test_two_offsets_require_decision_by_default():
    text = "[offset:+100]\n[offset:+400]\n" + BODY
    result = strip(text)
    assert result.decision and "--offset-policy" in result.decision
    assert result.text == text


def test_two_offsets_with_policy():
    text = "[offset:+100]\n[offset:+400]\n[00:01.00]Uno\n[00:02.00]Dos\n[00:03.00]Tres\n"
    assert strip(text, offset_policy=OFFSET_FIRST).text.startswith("[00:00.90]Uno")
    assert strip(text, offset_policy=OFFSET_LAST).text.startswith("[00:00.60]Uno")
    result = strip(text, offset_policy=OFFSET_SUM)
    assert result.text == "[00:00.50]Uno\n[00:01.50]Dos\n[00:02.50]Tres\n"
    assert result.offset_ms == 500


def test_offset_not_applied_with_invalid_or_inline_timestamps():
    invalid = "[offset:500]\n[00:01.00]Uno\n[00:61.00]Dos\n[00:03.00]Tres\n"
    assert "inválida" in strip(invalid).decision
    qq = "[offset:500]\n[00:01.00]Esta[00:01.40]es\n[00:02.00]Dos\n[00:03.00]Tres\n"
    assert "QQ" in strip(qq).decision
    # Sin offset, esos archivos se procesan normalmente.
    assert strip("[ti:x]\n" + qq.split("\n", 1)[1]).decision is None


def test_offset_is_not_applied_to_unsynced_lyrics():
    result = strip("[offset:500]\nUno\nDos\nTres")
    assert result.text == "Uno\nDos\nTres"
    assert result.shifted == 0


# --- Casi vacías y vacías -----------------------------------------------------

def test_nearly_empty_is_processed_with_warning():
    result = strip("[ar:A]\n[00:00.00]Instrumental\n")
    assert result.nearly_empty
    assert result.text == "[00:00.00]Instrumental\n"
    assert any("Casi vacía" in warning for warning in result.warnings)


def test_only_headers_would_be_empty():
    result = strip("[ti:Solo]\n[ar:A]\n[by:B]\n")
    assert result.empty_result
    assert not strip("").changed
    assert not strip("   \n\n").empty_result


def test_timestamps_without_text_are_not_empty():
    result = strip("[ti:x]\n[00:01.00]\n[00:04.50]\n")
    assert not result.empty_result
    assert result.text == "[00:01.00]\n[00:04.50]\n"


# --- Estandarizar ---------------------------------------------------------

def test_standardize_writes_fixed_block_without_duplicates():
    headers = [("ar", "Artista"), ("ti", "Título"), ("al", "Álbum"), ("length", "03:20")]
    block = header_lines(headers)
    text = "[ti:viejo]\n[ar:Artista]\n[by:LRCGet]\n[offset:+100]\n" + BODY
    result = normalize_text(text, MODE_STANDARDIZE, block)
    assert result.text == (
        "[ar:Artista]\n[ti:Título]\n[al:Álbum]\n[length:03:20]\n"
        "[00:00.90]Uno\n[00:01.90]Dos\n[00:02.90]Tres\n"
    )
    # Idempotente: una segunda pasada no cambia nada.
    assert not normalize_text(result.text, MODE_STANDARDIZE, block).changed


def test_standardize_uses_file_newlines():
    result = normalize_text(BODY.replace("\n", "\r\n"), MODE_STANDARDIZE, ["[ti:T]"])
    assert result.text == "[ti:T]\r\n" + BODY.replace("\n", "\r\n")


def test_unsynced_without_headers_is_unchanged():
    text = "Línea uno\nLínea dos\nLínea tres"
    for mode in (MODE_STRIP, MODE_STANDARDIZE):
        assert normalize_text(text, mode, ["[ar:A]"]).text == text


def test_build_headers_never_invents_data():
    track = Track(filename="a.flac", filepath=None, extension=".flac", size=0)
    assert build_headers(track) == []
    track.title = "Título"
    track.duration = 200.4
    assert build_headers(track) == [("ti", "Título"), ("length", "03:20")]
    track.artist = "Línea\nrota"
    assert ("ar", "Línea rota") in build_headers(track)
    assert build_headers(None) == []


# --- SYLT -----------------------------------------------------------------

def test_sylt_removes_header_entries_only():
    entries = [("[ti:x]", 0), ("﻿Uno", 1000), ("Dos", 2000), ("Tres", 3000)]
    result = normalize_sylt(entries)
    assert result.entries == entries[1:]
    assert result.removed_headers == ["ti"]


def test_sylt_with_offset_requires_decision():
    result = normalize_sylt([("[offset:100]", 0), ("Uno", 1000), ("Dos", 2000), ("Tres", 3000)])
    assert result.decision
