import codecs

import pytest

from choconostle.textio import (
    EncodingOptionError, UnencodableError, decode_lyrics, detect_encoding, diff_lines, encode_text,
    encoding_family, eol_summary, find_mojibake, join_lines, judge_candidates, parse_target_encoding,
    split_lines, visible,
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


# --- Decisión de la detección (independiente de la versión de charset-normalizer) ---

KOREAN = ("[00:01.00]이것은 첫 번째 테스트 줄입니다\n[00:04.50]두 번째 줄 가사\n"
          "[00:08.20]세 번째 줄\n[00:12.00]마지막 줄\n").encode("euc_kr")
CHINESE = "[00:01.00]这是第一行测试歌词\n[00:04.50]第二行歌词\n".encode("gbk")


@pytest.mark.parametrize("version,candidates", [
    ("3.5.1", [("cp949", 0.0), ("euc_jis_2004", 0.15)]),
    ("3.5.2", [("cp949", 0.0), ("euc_jis_2004", 0.1)]),
])
def test_wrong_cjk_decoding_is_not_a_tie(version, candidates):
    # Valores reales de charset-normalizer para "10 euc-kr coreano.lrc".
    detection = judge_candidates(KOREAN, candidates)
    assert detection.confident, version
    assert encoding_family(detection.encoding) == "EUC-KR"


def test_gbk_with_korean_and_japanese_rivals():
    # charset-normalizer 3.5.2 para "09 gbk chino.lrc".
    detection = judge_candidates(CHINESE, [("gb18030", 0.0), ("cp949", 0.138), ("euc_jis_2004", 0.159)])
    assert detection.confident and detection.encoding == "gb18030"


def test_real_tie_between_different_texts_is_ambiguous():
    spanish = "Canción ñandú pingüino".encode("cp1252")
    detection = judge_candidates(spanish, [("cp1250", 0.0), ("cp1252", 0.0)])
    assert not detection.confident
    assert detection.candidates == ["cp1250", "cp1252"]
    # Un rival de otra familia casi empatado también es ambiguo.
    assert not judge_candidates(KOREAN, [("cp949", 0.0), ("euc_jis_2004", 0.03)]).confident


def test_same_family_with_different_text_uses_widest():
    # 0x81 0x60: "〜" (U+301C) en shift_jis, "～" (U+FF5E) en cp932.
    data = "テスト".encode("cp932") + b"\x81\x60"
    assert data.decode("shift_jis") != data.decode("cp932")
    detection = judge_candidates(data, [("shift_jis", 0.0), ("cp932", 0.0)])
    assert detection.confident and detection.encoding == "cp932"
    quotes = "“Canción”".encode("cp1252")
    detection = judge_candidates(quotes, [("latin_1", 0.0), ("cp1252", 0.0)])
    assert detection.confident and detection.encoding == "cp1252"


def test_candidates_that_do_not_roundtrip_are_ignored():
    assert judge_candidates(b"\xff\xfe\x00", [("utf-8", 0.0)]).encoding is None


def test_encoding_family():
    assert encoding_family("euc-kr") == encoding_family("cp949") == "EUC-KR"
    assert encoding_family("Shift_JIS") == encoding_family("cp932") == "Shift-JIS"
    assert encoding_family("gbk") == encoding_family("gb18030") == "GB"
    assert encoding_family("cp1251") is None


# --- charset-normalizer en Python puro (Termux) ---------------------------

PURE_SCRIPT = r"""
import json, sys
import charset_normalizer
from charset_normalizer import md
from choconostle.textio import detect_encoding, encoding_family
samples = json.loads(sys.argv[1])
out = {"md": md.__file__, "results": {}}
for name, hexdata in samples.items():
    detection = detect_encoding(bytes.fromhex(hexdata))
    out["results"][name] = [detection.encoding, detection.confident, encoding_family(detection.encoding)]
print(json.dumps(out))
"""


def test_pure_python_charset_normalizer(tmp_path):
    """
    La rueda compilada (mypyc) y la de Python puro deben dar el mismo
    resultado. Se copia el paquete instalado sin las extensiones (.so/.pyd)
    y se ejecuta en un proceso aparte.
    """
    import json
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    import charset_normalizer

    import choconostle

    package = Path(charset_normalizer.__file__).parent
    target = tmp_path / "pure"
    shutil.copytree(package, target / "charset_normalizer",
                    ignore=shutil.ignore_patterns("*.so", "*.pyd", "__pycache__"))
    samples = {
        "shift_jis": ("[00:01.00]これはテストの最初の行です\n[00:04.50]二行目：ひらがなとカタカナ\n"
                      "[00:08.20]三行目の歌詞\n").encode("shift_jis").hex(),
        "gbk": ("[00:01.00]这是第一行测试歌词\n[00:04.50]第二行歌词\n[00:08.20]第三行\n"
                "[00:12.00]最后一行\n").encode("gbk").hex(),
        "euc_kr": KOREAN.hex(),
        "cp1251": ("[00:01.00]Это первая тестовая строка\n[00:04.50]Вторая строка песни\n"
                   "[00:08.20]Третья строка\n").encode("cp1251").hex(),
        "cp1252": "[00:01.00]Sigue la canción con acentos: ñandú, pingüino\n".encode("cp1252").hex(),
    }
    src = Path(choconostle.__file__).parents[1]
    code = f"import sys; sys.path[:0] = [{str(target)!r}, {str(src)!r}]\n" + PURE_SCRIPT
    output = subprocess.run([sys.executable, "-I", "-c", code, json.dumps(samples)],
                            check=True, capture_output=True, text=True).stdout
    result = json.loads(output)
    assert result["md"].endswith("md.py"), result["md"]  # ruta de Python puro
    pure = result["results"]
    for name, family in [("shift_jis", "Shift-JIS"), ("gbk", "GB"), ("euc_kr", "EUC-KR")]:
        assert pure[name][1] and pure[name][2] == family, (name, pure[name])
    assert pure["cp1251"][:2] == ["cp1251", True]
    assert pure["cp1252"][1] is False  # ambiguo frente a cp1250, también en Python puro
    # Mismo resultado que el paquete instalado en este proceso.
    for name, hexdata in samples.items():
        detection = detect_encoding(bytes.fromhex(hexdata))
        assert [detection.encoding, detection.confident] == pure[name][:2], name
