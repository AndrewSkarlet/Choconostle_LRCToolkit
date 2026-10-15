import pytest
from mutagen.mp4 import MP4, MP4Cover

from builders import (
    JPEG, add_id3, ffmpeg, has_encoder, make_ape, make_flac, make_mp3, make_wav, needs_ffmpeg,
)
from choconostle.models.track import TAGS_FULL, TAGS_LIMITED, TAGS_NONE
from choconostle.scanner import create_track


def test_flac(tmp_path):
    track = create_track(make_flac(tmp_path / "a.flac", rate=96000, bits=24))
    assert track.error is None
    assert track.format_label == "FLAC"
    assert track.lossless is True
    assert track.bits_per_sample == 24
    assert track.sample_rate == 96000
    assert track.tag_support == TAGS_FULL
    assert track.embedded_lyrics_supported


def test_flac_embedded_lyrics_and_cover(tmp_path):
    path = make_flac(
        tmp_path / "a.flac",
        tags={
            "TITLE": "Canción",
            "ALBUM": "Álbum",
            "LYRICS": "[ar:Artista]\n[00:01.00]Hola",
            "UNSYNCEDLYRICS": "Hola\nMundo",
        },
        picture=True,
    )
    track = create_track(path)
    assert track.title == "Canción"
    assert track.album == "Álbum"
    assert track.has_embedded_cover
    by_tag = {lyrics.location: lyrics for lyrics in track.lyrics}
    assert by_tag["LYRICS"].synced
    assert by_tag["LYRICS"].headers == ["ar"]
    assert not by_tag["UNSYNCEDLYRICS"].synced
    assert track.lyrics_status == "synced"


def test_mp3_uslt_sylt_apic(tmp_path):
    path = make_mp3(tmp_path / "a.mp3")
    add_id3(path, title="T", album="A", uslt="Hola\nMundo", uslt_encoding=0,
            sylt=[("Hola", 1000), ("Mundo", 2000)], cover=True)
    track = create_track(path)
    assert track.error is None
    assert track.format_label == "MP3"
    assert track.lossless is False
    assert track.has_embedded_cover
    by_tag = {lyrics.location: lyrics for lyrics in track.lyrics}
    assert not by_tag["USLT"].synced
    assert by_tag["USLT"].encoding == "latin-1"
    assert not by_tag["USLT"].is_utf8
    assert by_tag["SYLT"].synced


def test_mp3_uslt_with_lrc_text_is_synced(tmp_path):
    path = make_mp3(tmp_path / "a.mp3")
    add_id3(path, uslt="[ti:x]\n[00:01.00]Hola")
    track = create_track(path)
    assert track.lyrics[0].synced
    assert track.lyrics[0].headers == ["ti"]


@pytest.mark.parametrize("bits", [16, 24])
def test_wav(tmp_path, bits):
    track = create_track(make_wav(tmp_path / "a.wav", bits=bits))
    assert track.error is None
    assert track.format_label == "PCM (WAV)"
    assert track.lossless is True
    assert track.bits_per_sample == bits
    assert track.tag_support == TAGS_LIMITED
    assert not track.embedded_lyrics_supported


def test_ape(tmp_path):
    track = create_track(make_ape(tmp_path / "a.ape"))
    assert track.error is None
    assert track.format_label == "APE"
    assert track.lossless is True
    assert track.bits_per_sample == 16


def test_extension_mismatch(tmp_path):
    path = make_flac(tmp_path / "a.flac")
    renamed = path.with_suffix(".mp3")
    path.rename(renamed)
    track = create_track(renamed)
    assert track.codec == "FLAC"
    assert track.extension_mismatch
    assert any("no corresponde" in note for note in track.notes)


def test_corrupt_file_reports_error(tmp_path):
    path = tmp_path / "roto.flac"
    path.write_bytes(b"esto no es audio")
    track = create_track(path)
    assert track.error


def test_truncated_matroska_reports_error_or_unknown(tmp_path):
    path = tmp_path / "roto.mka"
    path.write_bytes(b"\x1a\x45\xdf\xa3\x80")
    track = create_track(path)
    assert track.error or track.codec == "Desconocido"


FFMPEG_CASES = [
    # (archivo, argumentos, encoder, formato esperado, sin pérdida, dolby, etiquetas)
    ("a.m4a", ["-c:a", "alac"], "alac", "ALAC (MP4)", True, False, TAGS_FULL),
    ("a.m4a", ["-c:a", "aac"], "aac", "AAC (MP4)", False, False, TAGS_FULL),
    ("a.m4a", ["-c:a", "ac3"], "ac3", "AC-3 (MP4)", False, True, TAGS_FULL),
    ("a.mp4", ["-c:a", "eac3"], "eac3", "E-AC-3 (MP4)", False, True, TAGS_FULL),
    ("a.mka", ["-c:a", "ac3"], "ac3", "AC-3 (Matroska)", False, True, TAGS_FULL),
    ("a.mka", ["-c:a", "eac3"], "eac3", "E-AC-3 (Matroska)", False, True, TAGS_FULL),
    ("a.mka", ["-c:a", "flac"], "flac", "FLAC (Matroska)", True, False, TAGS_FULL),
    ("a.opus", ["-c:a", "libopus"], "libopus", "Opus", False, False, TAGS_FULL),
    ("a.ogg", ["-c:a", "libvorbis"], "libvorbis", "Vorbis", False, False, TAGS_FULL),
    ("a.wv", ["-c:a", "wavpack"], "wavpack", "WavPack", True, False, TAGS_FULL),
    ("a.aiff", ["-c:a", "pcm_s16be"], "pcm_s16be", "PCM (AIFF)", True, False, TAGS_LIMITED),
    ("a.aac", ["-c:a", "aac"], "aac", "AAC", False, False, TAGS_NONE),
    ("a.ac3", ["-c:a", "ac3"], "ac3", "AC-3", False, True, TAGS_NONE),
    ("a.eac3", ["-c:a", "eac3", "-f", "eac3"], "eac3", "E-AC-3", False, True, TAGS_NONE),
]


@needs_ffmpeg
@pytest.mark.parametrize("name,args,encoder,label,lossless,dolby,tag_support", FFMPEG_CASES)
def test_ffmpeg_formats(tmp_path, name, args, encoder, label, lossless, dolby, tag_support):
    if not has_encoder(encoder):
        pytest.skip(f"ffmpeg sin encoder {encoder}")
    track = create_track(ffmpeg(tmp_path / name, *args))
    assert track.error is None
    assert track.format_label == label
    assert track.lossless is lossless
    assert track.dolby is dolby
    assert track.tag_support == tag_support
    assert not track.extension_mismatch


@needs_ffmpeg
def test_m4a_lyrics_and_cover(tmp_path):
    path = ffmpeg(tmp_path / "a.m4a", "-c:a", "alac")
    audio = MP4(path)
    audio["\xa9lyr"] = ["[length:01:00]\n[00:01.00]Hola"]
    audio["\xa9alb"] = ["Álbum"]
    audio["covr"] = [MP4Cover(JPEG, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()
    track = create_track(path)
    assert track.album == "Álbum"
    assert track.has_embedded_cover
    assert track.lyrics[0].synced
    assert track.lyrics[0].headers == ["length"]


@needs_ffmpeg
def test_matroska_tags_lyrics_and_attachment(tmp_path):
    if not has_encoder("flac"):
        pytest.skip("ffmpeg sin encoder flac")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(JPEG)
    path = ffmpeg(
        tmp_path / "a.mka",
        "-c:a", "flac",
        "-metadata", "title=Canción",
        "-metadata", "album=Álbum",
        "-metadata", "LYRICS=[00:01.00]Hola",
        "-attach", str(cover), "-metadata:s:t", "mimetype=image/jpeg",
    )
    track = create_track(path)
    assert track.error is None
    assert track.title == "Canción"
    assert track.album == "Álbum"
    assert track.has_embedded_cover
    assert track.lyrics and track.lyrics[0].synced


@needs_ffmpeg
def test_wav_with_ac3_inside(tmp_path):
    if not has_encoder("ac3"):
        pytest.skip("ffmpeg sin encoder ac3")
    track = create_track(ffmpeg(tmp_path / "a.wav", "-c:a", "ac3", "-f", "wav"))
    assert track.codec == "AC-3"
    assert track.dolby
    assert track.lossless is False
