"""
audio.py

Identifica el formato real de un archivo de audio a partir de su
contenido (no de su extensión) y lo clasifica como con o sin pérdida.

Responsabilidades:
- Detectar contenedor y códec (FLAC, ALAC, AAC, Opus, AC-3, E-AC-3...).
- Detectar audio Dolby aunque venga dentro de .m4a/.mp4/.mka/.wav.
- Indicar qué formatos admiten etiquetas y letras incrustadas.
- Leer etiquetas, letras y portadas incrustadas (ver tags.py).

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import mutagen
from mutagen.aac import AAC
from mutagen.ac3 import AC3
from mutagen.aiff import AIFF
from mutagen.flac import FLAC
from mutagen.monkeysaudio import MonkeysAudio
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggflac import OggFLAC
from mutagen.oggopus import OggOpus
from mutagen.oggspeex import OggSpeex
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from mutagen.wavpack import WavPack

from choconostle import matroska, tags
from choconostle.models.track import TAGS_LIMITED, TAGS_NONE, Track


@dataclass
class Codec:
    name: str
    lossless: bool | None
    dolby: bool = False


# Extensiones esperadas para cada contenedor. Si no coinciden, la
# extensión no corresponde al contenido real del archivo.
EXPECTED_EXTENSIONS = {
    "FLAC": {".flac"},
    "MP4": {".m4a", ".m4b", ".mp4"},
    "Ogg": {".ogg", ".oga", ".opus"},
    "Matroska": {".mka", ".mkv", ".webm"},
    "WAV": {".wav"},
    "AIFF": {".aif", ".aiff", ".aifc"},
    "APE": {".ape"},
    "WavPack": {".wv"},
    "MP3": {".mp3", ".mp2"},
    "MP2": {".mp2", ".mp3"},
    "AAC": {".aac"},
    "AC-3": {".ac3"},
    "E-AC-3": {".eac3", ".ec3", ".ac3"},
}

MP4_CODECS = {
    "alac": Codec("ALAC", True),
    "flac": Codec("FLAC", True),
    "ac-3": Codec("AC-3", False, dolby=True),
    "ec-3": Codec("E-AC-3", False, dolby=True),
    "ac-4": Codec("AC-4", False, dolby=True),
    "mlpa": Codec("TrueHD", True, dolby=True),
    "opus": Codec("Opus", False),
    "mp4a.69": Codec("MP3", False),
    "mp4a.6b": Codec("MP3", False),
}

MATROSKA_CODECS = {
    "A_FLAC": Codec("FLAC", True),
    "A_ALAC": Codec("ALAC", True),
    "A_PCM/INT/LIT": Codec("PCM", True),
    "A_PCM/INT/BIG": Codec("PCM", True),
    "A_PCM/FLOAT/IEEE": Codec("PCM", True),
    "A_WAVPACK4": Codec("WavPack", True),
    "A_TRUEHD": Codec("TrueHD", True, dolby=True),
    "A_MLP": Codec("MLP", True, dolby=True),
    "A_AC3": Codec("AC-3", False, dolby=True),
    "A_AC3/BSID9": Codec("AC-3", False, dolby=True),
    "A_AC3/BSID10": Codec("AC-3", False, dolby=True),
    "A_EAC3": Codec("E-AC-3", False, dolby=True),
    # DTS-HD MA es sin pérdida, DTS normal no: no se puede saber sin decodificar.
    "A_DTS": Codec("DTS", None),
    "A_OPUS": Codec("Opus", False),
    "A_VORBIS": Codec("Vorbis", False),
    "A_MPEG/L3": Codec("MP3", False),
    "A_MPEG/L2": Codec("MP2", False),
}

# Códigos de formato del bloque "fmt " de WAV.
WAV_CODECS = {
    0x0001: Codec("PCM", True),
    0x0003: Codec("PCM", True),
    0x0002: Codec("ADPCM", False),
    0x0011: Codec("ADPCM", False),
    0x0006: Codec("A-law", False),
    0x0007: Codec("u-law", False),
    0x0050: Codec("MP2", False),
    0x0055: Codec("MP3", False),
    0x00FF: Codec("AAC", False),
    0x1610: Codec("AAC", False),
    0x0092: Codec("AC-3", False, dolby=True),
    0x2000: Codec("AC-3", False, dolby=True),
    0x2001: Codec("DTS", None),
    0xF1AC: Codec("FLAC", True),
}
_WAVE_FORMAT_EXTENSIBLE = 0xFFFE

# Tipos de compresión de AIFF-C que siguen siendo PCM sin pérdida.
AIFC_PCM = {b"NONE", b"sowt", b"twos", b"raw ", b"in24", b"in32", b"fl32", b"FL32", b"fl64", b"FL64"}

# Banderas de la cabecera WavPack.
_WAVPACK_MONO = 0x4
_WAVPACK_HYBRID = 0x8


def _riff_format_tag(path: Path) -> int | None:
    """Lee el código de formato del bloque "fmt " de un WAV."""
    with open(path, "rb") as handle:
        header = handle.read(12)
        if len(header) < 12 or header[:4] not in (b"RIFF", b"RF64") or header[8:12] != b"WAVE":
            return None
        while True:
            chunk = handle.read(8)
            if len(chunk) < 8:
                return None
            chunk_id, size = chunk[:4], struct.unpack("<I", chunk[4:])[0]
            if chunk_id == b"fmt ":
                data = handle.read(min(size, 40))
                if len(data) < 2:
                    return None
                tag = struct.unpack("<H", data[:2])[0]
                if tag == _WAVE_FORMAT_EXTENSIBLE and len(data) >= 26:
                    tag = struct.unpack("<H", data[24:26])[0]
                return tag
            handle.seek(size + (size & 1), 1)


def _aifc_compression(path: Path) -> bytes | None:
    """Tipo de compresión de un AIFF-C, o None si es AIFF normal."""
    with open(path, "rb") as handle:
        header = handle.read(12)
        if len(header) < 12 or header[:4] != b"FORM" or header[8:12] != b"AIFC":
            return None
        while True:
            chunk = handle.read(8)
            if len(chunk) < 8:
                return None
            chunk_id, size = chunk[:4], struct.unpack(">I", chunk[4:])[0]
            if chunk_id == b"COMM":
                data = handle.read(min(size, 22))
                return data[18:22] if len(data) >= 22 else b"NONE"
            handle.seek(size + (size & 1), 1)


def _wavpack_flags(path: Path) -> int | None:
    with open(path, "rb") as handle:
        header = handle.read(32)
    if len(header) < 32 or header[:4] != b"wvpk":
        return None
    return struct.unpack("<I", header[24:28])[0]


def _sniff(path: Path) -> list | None:
    """
    Elige el lector de mutagen según los primeros bytes del archivo.

    mutagen.File() da mucho peso a la extensión: un FLAC renombrado a
    .mp3 se intentaría leer como MP3 y fallaría. Aquí se decide por el
    contenido. Retorna None si no se reconoce la firma (se deja decidir
    a mutagen).
    """
    with open(path, "rb") as handle:
        header = handle.read(12)
        offset = 0
        # Una etiqueta ID3v2 al inicio (MP3, a veces FLAC/AAC): saltarla.
        if header[:3] == b"ID3" and len(header) >= 10:
            size = 0
            for byte in header[6:10]:
                size = (size << 7) | (byte & 0x7F)
            offset = 10 + size + (10 if header[5] & 0x10 else 0)
            handle.seek(offset)
            header = handle.read(12)

    if header[:4] == b"fLaC":
        return [FLAC]
    if header[:4] == b"OggS":
        return [OggOpus, OggVorbis, OggFLAC, OggSpeex]
    if header[:4] in (b"RIFF", b"RF64") and header[8:12] == b"WAVE":
        return [WAVE]
    if header[:4] == b"FORM" and header[8:12] in (b"AIFF", b"AIFC"):
        return [AIFF]
    if header[:4] == b"MAC ":
        return [MonkeysAudio]
    if header[:4] == b"wvpk":
        return [WavPack]
    if header[4:8] == b"ftyp":
        return [MP4]
    if header[:2] == b"\x0b\x77":
        return [AC3]
    if header[:4] == b"ADIF":
        return [AAC]
    if len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0:
        # Sincronía MPEG: capa 00 con sincronía completa es AAC (ADTS).
        if header[1] & 0xF6 == 0xF0:
            return [AAC]
        return [MP3]
    if offset:
        return [MP3]
    return None


def _set_codec(track: Track, container: str, codec: Codec) -> None:
    track.container = container
    track.codec = codec.name
    track.lossless = codec.lossless
    track.dolby = codec.dolby


def _number(value) -> int | None:
    # mutagen a veces reporta los canales de WavPack como bool.
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number or None


def _identify(track: Track, audio) -> None:
    """Llena contenedor, códec y capacidades a partir de un objeto mutagen."""
    path = track.filepath
    info = audio.info

    if isinstance(audio, FLAC):
        _set_codec(track, "FLAC", Codec("FLAC", True))
    elif isinstance(audio, MP4):
        raw = (getattr(info, "codec", "") or "").lower()
        if raw.startswith("mp4a.40") or raw == "mp4a":
            codec = Codec("AAC", False)
        else:
            codec = MP4_CODECS.get(raw, Codec(raw.upper() or "Desconocido", None))
        _set_codec(track, "MP4", codec)
    elif isinstance(audio, MP3):
        layer = getattr(info, "layer", 3)
        name = "MP3" if layer == 3 else f"MP{layer}"
        _set_codec(track, name, Codec(name, False))
    elif isinstance(audio, OggOpus):
        _set_codec(track, "Ogg", Codec("Opus", False))
        track.sample_rate = 48000
    elif isinstance(audio, OggVorbis):
        _set_codec(track, "Ogg", Codec("Vorbis", False))
    elif isinstance(audio, OggFLAC):
        _set_codec(track, "Ogg", Codec("FLAC", True))
    elif isinstance(audio, OggSpeex):
        _set_codec(track, "Ogg", Codec("Speex", False))
    elif isinstance(audio, MonkeysAudio):
        _set_codec(track, "APE", Codec("APE", True))
    elif isinstance(audio, WavPack):
        flags = _wavpack_flags(path)
        hybrid = bool(flags is not None and flags & _WAVPACK_HYBRID)
        # El modo híbrido es con pérdida salvo que exista el archivo de
        # corrección .wvc junto al .wv.
        lossless = not hybrid or path.with_suffix(".wvc").exists()
        _set_codec(track, "WavPack", Codec("WavPack", lossless))
        if hybrid:
            track.notes.append(
                "WavPack híbrido " + ("con archivo .wvc (sin pérdida)." if lossless
                                      else "sin archivo .wvc (con pérdida).")
            )
        if flags is not None and _number(getattr(info, "channels", None)) is None:
            track.channels = 1 if flags & _WAVPACK_MONO else 2
    elif isinstance(audio, WAVE):
        tag = _riff_format_tag(path)
        codec = WAV_CODECS.get(tag, Codec(f"WAV 0x{tag:04X}" if tag is not None else "Desconocido", None))
        _set_codec(track, "WAV", codec)
        track.tag_support = TAGS_LIMITED
        track.embedded_lyrics_supported = False
    elif isinstance(audio, AIFF):
        compression = _aifc_compression(path)
        if compression is None or compression in AIFC_PCM:
            codec = Codec("PCM", True)
        else:
            codec = Codec(compression.decode("latin-1").strip() or "AIFF-C", False)
        _set_codec(track, "AIFF", codec)
        track.tag_support = TAGS_LIMITED
        track.embedded_lyrics_supported = False
    elif isinstance(audio, AC3):
        name = "E-AC-3" if getattr(info, "codec", "ac-3") == "ec-3" else "AC-3"
        _set_codec(track, name, Codec(name, False, dolby=True))
        track.tag_support = TAGS_NONE
        track.embedded_lyrics_supported = False
    elif isinstance(audio, AAC):
        _set_codec(track, "AAC", Codec("AAC", False))
        track.tag_support = TAGS_NONE
        track.embedded_lyrics_supported = False
    else:
        name = type(audio).__name__
        _set_codec(track, name, Codec(name, None))
        track.notes.append(f"Formato {name} reconocido por mutagen pero no clasificado.")

    if track.sample_rate is None:
        track.sample_rate = _number(getattr(info, "sample_rate", None))
    if track.channels is None:
        track.channels = _number(getattr(info, "channels", None))
    if track.lossless:
        track.bits_per_sample = _number(getattr(info, "bits_per_sample", None))
    track.duration = getattr(info, "length", None) or None
    track.bitrate = _number(getattr(info, "bitrate", None))


def _identify_matroska(track: Track) -> None:
    with open(track.filepath, "rb") as handle:
        info = matroska.read_matroska(handle)

    codec_id = info.codec_id or ""
    codec = MATROSKA_CODECS.get(codec_id)
    if codec is None:
        if codec_id.startswith("A_AAC"):
            codec = Codec("AAC", False)
        elif codec_id:
            codec = Codec(codec_id, None)
        else:
            codec = Codec("Desconocido", None)
            track.notes.append("No se encontró una pista de audio en el Matroska.")
    _set_codec(track, "Matroska", codec)
    track.sample_rate = info.sample_rate
    track.channels = info.channels
    if track.lossless:
        track.bits_per_sample = info.bits_per_sample
    track.duration = info.duration
    tags.read_matroska_tags(track, info)


def _check_extension(track: Track) -> None:
    expected = EXPECTED_EXTENSIONS.get(track.container or "")
    if expected and track.extension not in expected:
        track.extension_mismatch = True
        track.notes.append(
            f"La extensión {track.extension} no corresponde al contenido real "
            f"({track.format_label})."
        )


def analyze_track(track: Track) -> None:
    """
    Identifica el formato real de la pista y lee sus etiquetas.

    Los errores se guardan en track.error en lugar de propagarse, para
    que un archivo dañado no detenga el escaneo.
    """
    try:
        with open(track.filepath, "rb") as handle:
            magic = handle.read(4)
        if magic == matroska.EBML_MAGIC:
            _identify_matroska(track)
        else:
            readers = _sniff(track.filepath)
            if readers is None:
                audio = mutagen.File(track.filepath)
            elif len(readers) == 1:
                # Se abre directamente: mutagen.File() podría descartar el
                # lector si la extensión no le corresponde.
                audio = readers[0](track.filepath)
            else:
                audio = mutagen.File(track.filepath, options=readers)
            if audio is None:
                track.error = "Formato no reconocido (el contenido no es audio compatible)."
                return
            _identify(track, audio)
            tags.read_tags(track, audio)
    except (OSError, matroska.MatroskaError, mutagen.MutagenError) as exc:
        track.error = f"No se pudo leer: {exc}"
        return
    except Exception as exc:  # noqa: BLE001 - un archivo dañado no debe detener el escaneo
        track.error = f"Error inesperado al leer ({type(exc).__name__}): {exc}"
        return

    _check_extension(track)
    if track.lyrics and not track.embedded_lyrics_supported:
        track.notes.append(
            "Tiene letra incrustada en un formato que normalmente no la admite; "
            "muchos reproductores no la leerán."
        )
