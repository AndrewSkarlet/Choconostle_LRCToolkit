#!/usr/bin/env python3
"""
generar_casos.py — Biblioteca de prueba para Choconostle_LRCToolkit.

Crea una carpeta con letras (.lrc / .txt) y audios cortos de silencio con
letras incrustadas, cubriendo codificaciones, saltos de línea, cabeceras,
formatos de marcas de tiempo, marcas por palabra, traducciones, letras casi
vacías, archivos .txt, emparejamiento por nombre y etiquetas incrustadas.

Requisitos: Python 3.9+ y ffmpeg en el PATH. No necesita mutagen: las
etiquetas ID3 y Vorbis se escriben a mano para controlar cada byte.

Uso:
    python generar_casos.py [carpeta_destino]

Todo el texto de las letras es original (inventado para pruebas).
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from pathlib import Path

DUR = 15  # segundos de silencio por audio

# ---------------------------------------------------------------------------
# Letras base (texto original para pruebas)
# ---------------------------------------------------------------------------
ES = [
    ("00:01.00", "Esta es la primera línea de prueba"),
    ("00:04.50", "Sigue la canción con acentos: ñandú, pingüino, acción"),
    ("00:08.20", "Tercera línea para pasar el umbral"),
    ("00:12.00", "Cuarta y última línea"),
]
JA = [
    ("00:01.00", "これはテストの最初の行です"),
    ("00:04.50", "二行目：ひらがなとカタカナ"),
    ("00:08.20", "三行目の歌詞"),
    ("00:12.00", "最後の行"),
]
KO = [
    ("00:01.00", "이것은 첫 번째 테스트 줄입니다"),
    ("00:04.50", "두 번째 줄 가사"),
    ("00:08.20", "세 번째 줄"),
    ("00:12.00", "마지막 줄"),
]
RU = [
    ("00:01.00", "Это первая тестовая строка"),
    ("00:04.50", "Вторая строка песни"),
    ("00:08.20", "Третья строка"),
    ("00:12.00", "Последняя строка"),
]
ZH = [
    ("00:01.00", "这是第一行测试歌词"),
    ("00:04.50", "第二行歌词"),
    ("00:08.20", "第三行"),
    ("00:12.00", "最后一行"),
]
MULTI = [
    ("00:01.00", "Español: canción con ñ"),
    ("00:03.00", "日本語：歌詞のテスト"),
    ("00:05.00", "한국어: 가사 테스트"),
    ("00:07.00", "Русский: проверка"),
    ("00:09.00", "العربية: اختبار الكلمات"),
    ("00:11.00", "ไทย: ทดสอบเนื้อเพลง"),
    ("00:13.00", "Emoji: 🎵🎤✨"),
]

HDR_STD = ["[ti:Canción de prueba]", "[ar:Artista de Prueba]", "[by:SpotiFLAC-Mobile (source: LRCLIB)]", ""]


def synced(lines, headers=None, eol="\n"):
    out = list(headers or [])
    out += [f"[{t}]{x}" for t, x in lines]
    return eol.join(out) + eol


def plain(lines, eol="\n"):
    return eol.join(x for _, x in lines) + eol


# ---------------------------------------------------------------------------
# Audio con ffmpeg
# ---------------------------------------------------------------------------
def ffmpeg(args):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo", "-t", str(DUR),
         "-map_metadata", "-1", "-fflags", "+bitexact", *args],
        check=True,
    )


def make_flac(path: Path, tags: list[tuple[str, str]] | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(["-c:a", "flac", "-sample_fmt", "s16", str(path)])
    write_vorbis_comments(path, tags or [])


def make_mp3(path: Path, frames: bytes | None = None, version: int = 4):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.mp3")
    ffmpeg(["-ac", "1", "-c:a", "libmp3lame", "-b:a", "32k",
            "-id3v2_version", "0", "-write_id3v1", "0", "-write_xing", "0", str(tmp)])
    data = tmp.read_bytes()
    tmp.unlink()
    tag = id3_tag(frames, version) if frames else b""
    path.write_bytes(tag + data)


def make_other(path: Path, codec_args: list[str], meta: dict[str, str] | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    margs = []
    for k, v in (meta or {}).items():
        margs += ["-metadata", f"{k}={v}"]
    ffmpeg([*codec_args, *margs, str(path)])


# ---------------------------------------------------------------------------
# Vorbis comments en FLAC (escritos a mano: permiten claves repetidas, BOM, CRLF)
# ---------------------------------------------------------------------------
def write_vorbis_comments(path: Path, tags: list[tuple[str, str]]):
    data = path.read_bytes()
    assert data[:4] == b"fLaC"
    pos, blocks = 4, []
    while True:
        hdr = data[pos]
        last, btype = hdr & 0x80, hdr & 0x7F
        length = int.from_bytes(data[pos + 1:pos + 4], "big")
        body = data[pos + 4:pos + 4 + length]
        if btype != 4:  # descartar VORBIS_COMMENT existente
            blocks.append((btype, body))
        pos += 4 + length
        if last:
            break
    audio = data[pos:]
    vendor = b"choconostle-test"
    vc = struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(tags))
    for k, v in tags:
        item = f"{k}={v}".encode("utf-8")
        vc += struct.pack("<I", len(item)) + item
    blocks.insert(1, (4, vc))  # después de STREAMINFO
    out = bytearray(b"fLaC")
    for i, (btype, body) in enumerate(blocks):
        flag = 0x80 if i == len(blocks) - 1 else 0
        out.append(flag | btype)
        out += len(body).to_bytes(3, "big") + body
    path.write_bytes(bytes(out) + audio)


# ---------------------------------------------------------------------------
# ID3v2.3 / v2.4 escritos a mano
# ---------------------------------------------------------------------------
ENC_LATIN1, ENC_UTF16, ENC_UTF8 = 0, 1, 3


def _enc(text: str, enc: int) -> bytes:
    if enc == ENC_LATIN1:
        return text.encode("latin-1")
    if enc == ENC_UTF16:
        return text.encode("utf-16")  # con BOM
    return text.encode("utf-8")


def _term(enc: int) -> bytes:
    return b"\x00\x00" if enc == ENC_UTF16 else b"\x00"


def _syncsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


class Frame:
    def __init__(self, fid: str, body: bytes):
        self.fid, self.body = fid, body


def T(fid, text, enc=ENC_UTF8):
    return Frame(fid, bytes([enc]) + _enc(text, enc))


def USLT(text, lang="eng", desc="", enc=ENC_UTF8):
    return Frame("USLT", bytes([enc]) + lang.encode() + _enc(desc, enc) + _term(enc) + _enc(text, enc))


def TXXX(desc, value, enc=ENC_UTF8):
    return Frame("TXXX", bytes([enc]) + _enc(desc, enc) + _term(enc) + _enc(value, enc))


def SYLT(entries, lang="eng", desc="", enc=ENC_UTF8):
    """entries: [(milisegundos, texto)]; formato de tiempo 2 = ms, tipo 1 = letra."""
    body = bytes([enc]) + lang.encode() + bytes([2, 1]) + _enc(desc, enc) + _term(enc)
    for ms, text in entries:
        body += _enc(text, enc) + _term(enc) + struct.pack(">I", ms)
    return Frame("SYLT", body)


def id3_tag(frames, version=4) -> bytes:
    payload = b""
    for f in frames:
        size = _syncsafe(len(f.body)) if version == 4 else struct.pack(">I", len(f.body))
        payload += f.fid.encode() + size + b"\x00\x00" + f.body
    payload += b"\x00" * 256  # relleno
    return b"ID3" + bytes([version, 0, 0]) + _syncsafe(len(payload)) + payload


def basic_id3(title, version=4):
    enc = ENC_UTF8 if version == 4 else ENC_UTF16
    return [T("TIT2", title, enc), T("TPE1", "Artista de Prueba", enc),
            T("TALB", "Álbum de Prueba", enc), T("TRCK", "1", enc)]


# ---------------------------------------------------------------------------
# Utilidades de escritura de texto
# ---------------------------------------------------------------------------
def wtext(path: Path, text: str, encoding="utf-8", bom=b""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bom + text.encode(encoding))


def wbytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def song(folder: Path, stem: str, lrc_text: str | None = None, ext=".lrc", **kw):
    """FLAC sin letra incrustada + archivo de letra con el mismo nombre."""
    make_flac(folder / f"{stem}.flac", [("TITLE", stem), ("ARTIST", "Artista de Prueba"),
                                         ("ALBUM", folder.name), ("ALBUMARTIST", "Artista de Prueba")])
    if lrc_text is not None:
        wtext(folder / f"{stem}{ext}", lrc_text, **kw)


def flac_tags(title, album, extra):
    return [("TITLE", title), ("ARTIST", "Artista de Prueba"), ("ALBUM", album),
            ("ALBUMARTIST", "Artista de Prueba"), ("TRACKNUMBER", "1")] + extra


# ---------------------------------------------------------------------------
# Casos
# ---------------------------------------------------------------------------
def build(root: Path):
    std = synced(ES, HDR_STD)

    # 01 — Codificaciones -----------------------------------------------------
    d = root / "01_codificaciones"
    song(d, "01 utf8 sin BOM", std)
    song(d, "02 utf8 con BOM", std, bom=b"\xef\xbb\xbf")
    song(d, "03 utf16 LE con BOM", std, encoding="utf-16-le", bom=b"\xff\xfe")
    song(d, "04 utf16 BE con BOM", std, encoding="utf-16-be", bom=b"\xfe\xff")
    song(d, "05 utf16 LE sin BOM", std, encoding="utf-16-le")
    song(d, "06 windows-1252 espanol", std, encoding="cp1252")
    song(d, "07 mojibake utf8 leido como 1252",
         std.encode("utf-8").decode("cp1252", errors="replace"))
    song(d, "08 shift-jis japones", synced(JA, ["[ti:テスト曲]", "[ar:テスト歌手]", ""]), encoding="shift_jis")
    song(d, "09 gbk chino", synced(ZH, ["[ti:测试歌曲]", "[ar:测试歌手]", ""]), encoding="gbk")
    song(d, "10 euc-kr coreano", synced(KO, ["[ti:테스트 곡]", "[ar:테스트 가수]", ""]), encoding="euc_kr")
    song(d, "11 windows-1251 ruso", synced(RU, ["[ti:Тестовая песня]", "[ar:Тестовый артист]", ""]), encoding="cp1251")
    song(d, "12 utf8 multiescritura", synced(MULTI, HDR_STD))
    song(d, "13 ascii puro", synced([(t, x.encode("ascii", "ignore").decode()) for t, x in ES], HDR_STD))
    song(d, "14 japones utf8", synced(JA, ["[ti:テスト曲]", "[ar:テスト歌手]", ""]))
    song(d, "15 coreano utf8", synced(KO, ["[ti:테스트 곡]", "[ar:테스트 가수]", ""]))
    song(d, "16 ruso utf8", synced(RU, ["[ti:Тестовая песня]", ""]))
    song(d, "17 utf8 con bytes invalidos", None)
    wbytes(d / "17 utf8 con bytes invalidos.lrc",
           std.encode("utf-8").replace("ñandú".encode(), b"\xf1and\xfa"))  # mezcla utf8 + 1252

    # 02 — Saltos de línea y espacios ----------------------------------------
    d = root / "02_saltos_de_linea"
    song(d, "01 LF", synced(ES, HDR_STD, "\n"))
    song(d, "02 CRLF", synced(ES, HDR_STD, "\r\n"))
    song(d, "03 CR solo", synced(ES, HDR_STD, "\r"))
    mixed = "[ti:Mezcla]\r\n[ar:Artista de Prueba]\n\r\n[00:01.00]Uno\r[00:04.50]Dos\n[00:08.20]Tres\r\n[00:12.00]Cuatro"
    song(d, "04 mixto sin salto final", mixed)
    song(d, "05 espacios y tabs", "[ti:Espacios]   \n\t[ar:Artista de Prueba]\n\n[00:01.00]   Uno con espacios   \n"
         "[00:04.50]\tDos con tab\n   [00:08.20]Tres con sangría\n[00:12.00]Cuatro\n\n\n")
    song(d, "06 lineas en blanco intermedias", "[ti:Blancos]\n\n\n[00:01.00]Uno\n\n[00:04.50]Dos\n\n\n[00:08.20]Tres\n[00:12.00]Cuatro\n")
    song(d, "07 caracteres invisibles", "​[ti:Invisible]\n[ar:Artista de Prueba]\n[00:01.00]Uno​\n"
         "[00:04.50]Dos con separador\n[00:08.20]Tres\n[00:12.00]Cuatro﻿\n")

    # 03 — Cabeceras ----------------------------------------------------------
    d = root / "03_cabeceras"
    song(d, "01 estandar ti ar by", std)
    song(d, "02 todas las conocidas", synced(ES, [
        "[ar:Artista de Prueba]", "[al:Álbum de Prueba]", "[ti:Canción]", "[au:Compositor]",
        "[lr:Letrista]", "[length:02:45]", "[by:Usuario]", "[re:Editor LRC 1.0]",
        "[tool:Herramienta]", "[ve:1.0]", "[la:es]", "[#:Comentario en cabecera]", ""]))
    song(d, "03 offset positivo +500", synced(ES, ["[ti:Offset]", "[offset:+500]", ""]))
    song(d, "04 offset negativo -300", synced(ES, ["[ti:Offset]", "[offset:-300]", ""]))
    song(d, "05 offset sin signo 250", synced(ES, ["[ti:Offset]", "[offset:250]", ""]))
    song(d, "06 offset que deja negativo", synced(ES, ["[ti:Offset]", "[offset:+2000]", ""]))
    song(d, "07 offset invalido", synced(ES, ["[ti:Offset]", "[offset:medio segundo]", ""]))
    song(d, "08 dos offsets", synced(ES, ["[offset:+100]", "[offset:+400]", ""]))
    song(d, "09 mayusculas", synced(ES, ["[TI:Mayúsculas]", "[Ar:Artista de Prueba]", "[BY:Alguien]", ""]))
    song(d, "10 espacios dentro", synced(ES, ["[ ti : Con espacios ]", "[ar: ]", "[al:]", ""]))
    song(d, "11 duplicadas", synced(ES, ["[ar:Artista Uno]", "[ar:Artista Dos]", "[ti:Duplicada]", "[ti:Duplicada]", ""]))
    song(d, "12 cabeceras en medio y al final",
         "[ti:Inicio]\n[00:01.00]Uno\n[00:04.50]Dos\n[ar:En medio]\n[00:08.20]Tres\n[00:12.00]Cuatro\n[by:Al final]\n")
    song(d, "13 corchetes que no son cabeceras",
         "[ti:Secciones]\n[00:01.00][Coro]\n[00:04.50][Coro: Artista Invitado] Esta sí es letra\n"
         "[00:08.20](Instrumental)\n[00:12.00][Verso 2] Cuarta línea\n")
    song(d, "14 secciones sin marca de tiempo",
         "[ti:Secciones]\n[Verso 1]\n[00:01.00]Uno\n[00:04.50]Dos\n[Coro]\n[00:08.20]Tres\n[00:12.00]Cuatro\n")
    song(d, "15 solo cabeceras", "[ti:Solo cabeceras]\n[ar:Artista de Prueba]\n[by:Alguien]\n")
    song(d, "16 cabeceras con letra sin sincronizar", "[ti:Sin sincronizar]\n[ar:Artista de Prueba]\n\n" + plain(ES))
    song(d, "17 cabecera desconocida", synced(ES, ["[ti:Desconocida]", "[xtrack:7]", "[hash:abc123]", ""]))
    song(d, "18 valor con corchetes y dos puntos", synced(ES, ["[ti:Canción: parte 2 [Remix]]", "[ar:A:B]", ""]))

    # 04 — Formatos de marcas de tiempo ---------------------------------------
    d = root / "04_marcas_de_tiempo"
    song(d, "01 centesimas mm-ss.xx", synced(ES))
    song(d, "02 milesimas mm-ss.xxx", synced([("00:01.000", "Uno"), ("00:04.500", "Dos"), ("00:08.250", "Tres"), ("00:12.125", "Cuatro")]))
    song(d, "03 decimas mm-ss.x", synced([("00:01.0", "Uno"), ("00:04.5", "Dos"), ("00:08.2", "Tres"), ("00:12.0", "Cuatro")]))
    song(d, "04 sin fraccion mm-ss", synced([("00:01", "Uno"), ("00:04", "Dos"), ("00:08", "Tres"), ("00:12", "Cuatro")]))
    song(d, "05 dos puntos mm-ss-xx", synced([("00:01:00", "Uno"), ("00:04:50", "Dos"), ("00:08:20", "Tres"), ("00:12:00", "Cuatro")]))
    song(d, "06 coma mm-ss,xx", synced([("00:01,00", "Uno"), ("00:04,50", "Dos"), ("00:08,20", "Tres"), ("00:12,00", "Cuatro")]))
    song(d, "07 un digito m-ss.xx", synced([("0:01.00", "Uno"), ("0:04.50", "Dos"), ("0:08.20", "Tres"), ("0:12.00", "Cuatro")]))
    song(d, "08 mas de 99 minutos", synced([("00:01.00", "Inicio"), ("59:59.99", "Casi una hora"),
                                             ("102:03.45", "Más de cien minutos"), ("01:02:03.45", "Con horas")]))
    song(d, "09 varias marcas por linea",
         "[ti:Repetidas]\n[00:01.00]Verso\n[00:04.50][00:12.00]Coro que se repite\n[00:08.20]Puente\n")
    song(d, "10 desordenadas", synced([("00:12.00", "Cuatro"), ("00:01.00", "Uno"), ("00:08.20", "Tres"), ("00:04.50", "Dos")]))
    song(d, "11 marcas vacias (pausas)", "[00:01.00]Uno\n[00:03.00]\n[00:04.50]Dos\n[00:06.00]\n[00:08.20]Tres\n[00:12.00]Cuatro\n")
    song(d, "12 mezcla sincronizada y sin marca",
         "[00:01.00]Uno\nLínea sin marca de tiempo\n[00:04.50]Dos\n[00:08.20]Tres\nOtra sin marca\n[00:12.00]Cuatro\n")
    song(d, "13 marcas invalidas",
         "[00:01.00]Válida\n[00:61.00]Segundos 61\n[aa:bb.cc]Letras en vez de números\n[00:04.5x]Mal formada\n[00:12.00]Válida\n")
    song(d, "14 marca con espacio despues", "[00:01.00] Uno\n[00:04.50]  Dos\n[00:08.20]Tres\n[00:12.00]Cuatro \n")
    song(d, "15 marca final sin texto (fin)", synced(ES) + "[00:14.50]\n")

    # 05 — Marcas por palabra -------------------------------------------------
    d = root / "05_palabra_por_palabra"
    enh = ("[ti:Por palabra]\n[ar:Artista de Prueba]\n\n"
           "[00:01.00]<00:01.00>Esta <00:01.40>es <00:01.70>la <00:02.00>primera <00:02.60>línea<00:03.20>\n"
           "[00:04.50]<00:04.50>Sigue <00:05.00>la <00:05.30>canción<00:06.10>\n"
           "[00:08.20]<00:08.20>Tercera <00:08.90>línea<00:09.60>\n"
           "[00:12.00]<00:12.00>Cuarta <00:12.60>y <00:12.80>última<00:13.50>\n")
    song(d, "01 enhanced A2 con cabeceras", enh)
    song(d, "02 enhanced milesimas",
         "[00:01.000]<00:01.000>Uno <00:01.500>dos<00:02.000>\n[00:04.500]<00:04.500>Tres <00:05.250>cuatro<00:06.000>\n"
         "[00:08.200]<00:08.200>Cinco <00:08.800>seis<00:09.400>\n[00:12.000]<00:12.000>Siete <00:12.700>ocho<00:13.300>\n")
    song(d, "03 enhanced con offset", "[offset:+500]\n" + enh)
    song(d, "04 enhanced sin marca de cierre",
         "[00:01.00]<00:01.00>Uno <00:01.40>dos\n[00:04.50]<00:04.50>Tres <00:05.00>cuatro\n"
         "[00:08.20]<00:08.20>Cinco <00:08.90>seis\n[00:12.00]<00:12.00>Siete <00:12.60>ocho\n")
    song(d, "05 palabra con corchetes en linea (estilo QQ)",
         "[00:01.00]Esta[00:01.40]es[00:01.70]la[00:02.00]primera\n[00:04.50]Sigue[00:05.00]la[00:05.30]canción\n"
         "[00:08.20]Tercera[00:08.90]línea\n[00:12.00]Cuarta[00:12.60]y[00:12.80]última\n")
    song(d, "06 voces duo (v1 v2)",
         "[00:01.00]v1: <00:01.00>Canta <00:01.50>uno\n[00:04.50]v2: <00:04.50>Responde <00:05.20>dos\n"
         "[00:08.20]v1: <00:08.20>Otra <00:08.80>vez\n[00:12.00]v2: <00:12.00>Final <00:12.60>juntos\n")
    song(d, "07 voces M F D (walaoke)",
         "[00:01.00]M: <00:01.00>Voz <00:01.40>masculina\n[00:04.50]F: <00:04.50>Voz <00:05.00>femenina\n"
         "[00:08.20]D: <00:08.20>Dueto <00:08.90>juntos\n[00:12.00]M: <00:12.00>Cierre\n")
    song(d, "08 mezcla por palabra y por linea",
         "[00:01.00]<00:01.00>Por <00:01.50>palabra\n[00:04.50]Solo por línea\n"
         "[00:08.20]<00:08.20>Otra <00:08.80>vez\n[00:12.00]Final por línea\n")
    song(d, "09 enhanced japones utf8",
         "[00:01.00]<00:01.00>これは<00:01.80>テスト<00:02.60>です\n[00:04.50]<00:04.50>二行目<00:05.50>の歌詞\n"
         "[00:08.20]<00:08.20>三行目\n[00:12.00]<00:12.00>最後<00:12.80>の行\n")
    song(d, "10 enhanced en .txt", enh, ext=".txt")

    # 06 — Traducciones y bilingües -------------------------------------------
    d = root / "06_traducciones"
    song(d, "01 marca duplicada original y traduccion",
         "[00:01.00]これはテストです\n[00:01.00]Esto es una prueba\n[00:04.50]二行目\n[00:04.50]Segunda línea\n"
         "[00:08.20]三行目\n[00:08.20]Tercera línea\n[00:12.00]最後\n[00:12.00]Final\n")
    song(d, "02 traduccion en la misma linea",
         "[00:01.00]これはテストです / Esto es una prueba\n[00:04.50]二行目 / Segunda línea\n"
         "[00:08.20]三行目 / Tercera línea\n[00:12.00]最後 / Final\n")
    song(d, "03 romanizacion entre parentesis",
         "[00:01.00]이것은 테스트 (igeoseun teseuteu)\n[00:04.50]두 번째 줄 (du beonjjae jul)\n"
         "[00:08.20]세 번째 (se beonjjae)\n[00:12.00]마지막 (majimak)\n")

    # 07 — Casi vacías y vacías -----------------------------------------------
    d = root / "07_casi_vacias"
    song(d, "01 solo instrumental", "[00:00.00]Instrumental\n")
    song(d, "02 instrumental con cabeceras", "[ti:Instrumental]\n[ar:Artista de Prueba]\n[by:SpotiFLAC-Mobile]\n\n[00:00.00]Instrumental\n")
    song(d, "03 dos lineas", "[ti:Corta]\n[00:01.00]Uno\n[00:04.50]Dos\n")
    song(d, "04 tres lineas (umbral)", "[ti:Umbral]\n[00:01.00]Uno\n[00:04.50]Dos\n[00:08.20]Tres\n")
    song(d, "05 archivo vacio 0 bytes", "")
    song(d, "06 solo espacios y saltos", "   \n\n\t\n")
    song(d, "07 solo BOM", "", bom=b"\xef\xbb\xbf")
    song(d, "08 marcas sin texto", "[00:01.00]\n[00:04.50]\n[00:08.20]\n")
    song(d, "09 texto de relleno (sin letra)", "[00:00.00]Letra no disponible\n")

    # 08 — Archivos .txt -------------------------------------------------------
    d = root / "08_txt"
    song(d, "01 txt sincronizado con cancion", std, ext=".txt")
    song(d, "02 txt sin sincronizar con cancion", "[ti:Texto]\n[ar:Artista de Prueba]\n\n" + plain(ES), ext=".txt")
    song(d, "03 mismo nombre lrc y txt", std)
    wtext(d / "03 mismo nombre lrc y txt.txt", plain(ES))
    wtext(d / "04 txt huerfano sincronizado.txt", std)
    wtext(d / "05 txt huerfano letra simple.txt", plain(ES))
    wtext(d / "README.txt", "Notas del álbum.\nDescargado en 2026.\n[Disco 1] contiene 12 pistas.\n")
    wtext(d / "tracklist.txt", "01. Primera canción (3:45)\n02. Segunda canción (4:10)\n[01:02] no es una marca de letra\n")
    wtext(d / "notas con cabecera.txt", "[ar:Esto parece cabecera]\nPero es un archivo de notas.\n")
    song(d, "06 extension en mayusculas", std, ext=".LRC")
    song(d, "07 extension mixta", std, ext=".Lrc")
    song(d, "08 txt utf16 con BOM", std, ext=".txt", encoding="utf-16-le", bom=b"\xff\xfe")

    # 09 — Emparejamiento por nombre ------------------------------------------
    d = root / "09_emparejamiento"
    song(d, "01. Mr. Nombre con puntos", std)
    song(d, "02 Acentos y eñe - Canción Ñandú", std)
    song(d, "03 Corchetes [Explicit] & símbolos (feat. Otro)", std)
    song(d, "04 歌のタイトル", synced(JA))
    make_flac(d / "05 Mayusculas distintas.flac", flac_tags("05", "09", []))
    wtext(d / "05 MAYUSCULAS DISTINTAS.lrc", std)
    make_flac(d / "06 Cancion sin letra.flac", flac_tags("06", "09", []))
    wtext(d / "06 Letra con otro nombre.lrc", std)
    make_flac(d / "07 Mismo nombre mp3 y flac.flac", flac_tags("07", "09", []))
    make_mp3(d / "07 Mismo nombre mp3 y flac.mp3", basic_id3("07"))
    wtext(d / "07 Mismo nombre mp3 y flac.lrc", std)
    song(d, "08 Espacio final antes de extension ", std)
    make_flac(d / "09 Letra en subcarpeta.flac", flac_tags("09", "09", []))
    wtext(d / "Lyrics" / "09 Letra en subcarpeta.lrc", std)
    wtext(d / "10 lrc huerfano total.lrc", std)

    # 10 — Letras incrustadas --------------------------------------------------
    d = root / "10_incrustadas"
    alb = "10_incrustadas"
    std_crlf = synced(ES, HDR_STD, "\r\n")
    make_flac(d / "01 FLAC LYRICS con cabeceras.flac", flac_tags("01", alb, [("LYRICS", std)]))
    make_flac(d / "02 FLAC UNSYNCEDLYRICS sincronizada.flac", flac_tags("02", alb, [("UNSYNCEDLYRICS", std)]))
    make_flac(d / "03 FLAC LYRICS y UNSYNCEDLYRICS distintas.flac",
              flac_tags("03", alb, [("LYRICS", std), ("UNSYNCEDLYRICS", plain(ES))]))
    make_flac(d / "04 FLAC incrustada distinta al lrc.flac", flac_tags("04", alb, [("LYRICS", synced(ES))]))
    wtext(d / "04 FLAC incrustada distinta al lrc.lrc", synced(ES[:2] + [("00:09.00", "Versión distinta del .lrc"), ES[3]], HDR_STD))
    make_flac(d / "05 FLAC con BOM dentro del texto.flac", flac_tags("05", alb, [("LYRICS", "﻿" + std)]))
    make_flac(d / "06 FLAC con CRLF dentro.flac", flac_tags("06", alb, [("LYRICS", std_crlf)]))
    make_flac(d / "07 FLAC por palabra.flac", flac_tags("07", alb, [("LYRICS", enh)]))
    make_flac(d / "08 FLAC dos campos LYRICS.flac", flac_tags("08", alb, [("LYRICS", std), ("LYRICS", plain(ES))]))
    make_flac(d / "09 FLAC clave en minusculas.flac", flac_tags("09", alb, [("lyrics", std)]))
    make_flac(d / "10 FLAC con offset.flac", flac_tags("10", alb, [("LYRICS", synced(ES, ["[offset:+500]", ""]))]))
    make_flac(d / "11 FLAC casi vacia.flac", flac_tags("11", alb, [("LYRICS", "[ti:X]\n[00:00.00]Instrumental\n")]))

    make_mp3(d / "20 MP3 v2.4 USLT utf8.mp3", basic_id3("20") + [USLT(std)], 4)
    make_mp3(d / "21 MP3 v2.3 USLT utf16.mp3", basic_id3("21", 3) + [USLT(std, enc=ENC_UTF16)], 3)
    make_mp3(d / "22 MP3 v2.3 USLT latin1.mp3", basic_id3("22", 3) + [USLT(std, enc=ENC_LATIN1)], 3)
    make_mp3(d / "23 MP3 dos USLT eng y spa.mp3", basic_id3("23") + [USLT(std, "eng"), USLT(plain(ES), "spa")], 4)
    make_mp3(d / "24 MP3 USLT con descripcion.mp3", basic_id3("24") + [USLT(std, desc="Letra sincronizada")], 4)
    make_mp3(d / "25 MP3 SYLT milisegundos.mp3",
             basic_id3("25") + [SYLT([(1000, "Esta es la primera línea"), (4500, "Sigue la canción"),
                                       (8200, "Tercera línea"), (12000, "Cuarta y última")])], 4)
    make_mp3(d / "26 MP3 SYLT con cabecera como entrada.mp3",
             basic_id3("26") + [SYLT([(0, "[ti:Cabecera dentro de SYLT]"), (1000, "Uno"), (4500, "Dos"),
                                       (8200, "Tres"), (12000, "Cuatro")])], 4)
    make_mp3(d / "27 MP3 TXXX LYRICS.mp3", basic_id3("27") + [TXXX("LYRICS", std)], 4)
    make_mp3(d / "28 MP3 USLT y SYLT y lrc.mp3",
             basic_id3("28") + [USLT(std), SYLT([(1000, "Uno"), (4500, "Dos"), (8200, "Tres"), (12000, "Cuatro")])], 4)
    wtext(d / "28 MP3 USLT y SYLT y lrc.lrc", std)
    make_mp3(d / "29 MP3 USLT por palabra.mp3", basic_id3("29") + [USLT(enh)], 4)
    make_mp3(d / "30 MP3 v2.3 TXXX unsyncedlyrics.mp3", basic_id3("30", 3) + [TXXX("UNSYNCEDLYRICS", std, ENC_UTF16)], 3)

    make_other(d / "40 M4A AAC lyr.m4a", ["-c:a", "aac", "-b:a", "48k"],
               {"title": "40", "artist": "Artista de Prueba", "album": alb, "lyrics": std})
    make_other(d / "41 M4A ALAC lyr.m4a", ["-c:a", "alac"],
               {"title": "41", "artist": "Artista de Prueba", "album": alb, "lyrics": std})
    make_other(d / "42 OPUS LYRICS.opus", ["-c:a", "libopus", "-b:a", "24k"],
               {"TITLE": "42", "ARTIST": "Artista de Prueba", "ALBUM": alb, "LYRICS": std})
    make_other(d / "43 OGG Vorbis LYRICS.ogg", ["-c:a", "libvorbis", "-q:a", "0"],
               {"TITLE": "43", "ARTIST": "Artista de Prueba", "ALBUM": alb, "LYRICS": std})
    make_other(d / "44 WavPack APEv2 Lyrics.wv", ["-c:a", "wavpack"],
               {"Title": "44", "Artist": "Artista de Prueba", "Album": alb, "Lyrics": std})
    make_other(d / "45 WAV sin etiquetas con lrc.wav", ["-c:a", "pcm_s16le", "-ac", "1", "-ar", "8000"])
    wtext(d / "45 WAV sin etiquetas con lrc.lrc", std)


def main():
    if not shutil.which("ffmpeg"):
        sys.exit("Se necesita ffmpeg en el PATH.")
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "Choconostle_Casos_LRC")
    if root.exists():
        sys.exit(f"{root} ya existe; bórrala o elige otro destino.")
    build(root)
    n = sum(1 for p in root.rglob("*") if p.is_file())
    print(f"Listo: {n} archivos en {root.resolve()}")


if __name__ == "__main__":
    main()
