"""
builders.py

Genera archivos de audio mínimos para las pruebas.

FLAC, MP3, WAV y APE se generan en Python puro (funcionan en Windows y
Termux sin herramientas externas). El resto de formatos usa ffmpeg y
sus pruebas se omiten si no está instalado.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import wave
from functools import lru_cache
from pathlib import Path

import pytest
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, SYLT, TALB, TIT2, TPE1, TPE2, USLT

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="requiere ffmpeg")

# Un JPEG mínimo basta: solo se revisa que exista una imagen.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


def make_flac(path: Path, rate=44100, bits=16, channels=2, seconds=1, tags=None, picture=False) -> Path:
    """FLAC con solo el bloque STREAMINFO (mutagen no necesita frames de audio)."""
    samples = rate * seconds
    packed = (rate << 44) | ((channels - 1) << 41) | ((bits - 1) << 36) | samples
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6 + packed.to_bytes(8, "big") + b"\x00" * 16
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fLaC" + bytes([0x80]) + len(streaminfo).to_bytes(3, "big") + streaminfo)
    if tags or picture:
        audio = FLAC(path)
        for key, value in (tags or {}).items():
            audio[key] = value
        if picture:
            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.data = JPEG
            audio.add_picture(pic)
        audio.save()
    return path


def make_mp3(path: Path, frames=40) -> Path:
    """MP3 de frames MPEG-1 Layer III (128 kbps, 44.1 kHz) en silencio."""
    header = b"\xff\xfb\x90\x00"
    frame = header + b"\x00" * (417 - len(header))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(frame * frames)
    return path


def add_id3(path: Path, title=None, artist=None, album=None, album_artist=None,
            uslt=None, uslt_encoding=3, sylt=None, cover=False) -> None:
    tags = ID3()
    if title:
        tags.add(TIT2(encoding=3, text=title))
    if artist:
        tags.add(TPE1(encoding=3, text=artist))
    if album:
        tags.add(TALB(encoding=3, text=album))
    if album_artist:
        tags.add(TPE2(encoding=3, text=album_artist))
    if uslt is not None:
        tags.add(USLT(encoding=uslt_encoding, lang="spa", desc="", text=uslt))
    if sylt is not None:
        tags.add(SYLT(encoding=3, lang="spa", format=2, type=1, desc="", text=sylt))
    if cover:
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=JPEG))
    tags.save(path)


def make_wav(path: Path, bits=16, rate=44100, channels=2, seconds=1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(bits // 8)
        handle.setframerate(rate)
        handle.writeframes(b"\x00" * (bits // 8) * channels * rate * seconds)
    return path


def make_ape(path: Path, rate=44100, bits=16, channels=2) -> Path:
    """Cabecera de Monkey's Audio (versión 3.99) sin datos de audio."""
    header = b"MAC " + struct.pack("<H", 3990) + b"\x00" * 50
    header += struct.pack("<IIIHHI", 73728, 1000, 1, bits, channels, rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + b"\x00" * 64)
    return path


@lru_cache(maxsize=None)
def ffmpeg_encoders() -> str:
    if FFMPEG is None:
        return ""
    result = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True)
    return result.stdout


def has_encoder(name: str) -> bool:
    return any(line.split()[1:2] == [name] for line in ffmpeg_encoders().splitlines() if line.strip())


def ffmpeg(path: Path, *args: str, rate=44100) -> Path:
    """Genera 1 segundo de tono con ffmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration=1:sample_rate={rate}",
        *args, str(path),
    ]
    subprocess.run(command, check=True)
    return path
