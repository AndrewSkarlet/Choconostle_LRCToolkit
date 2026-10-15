"""
track.py

Modelo que representa una pista musical dentro de la biblioteca.

Responsabilidad:
- Almacenar información de una canción.
- No contiene lógica de análisis.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from choconostle.models.lyrics import SOURCE_EXTERNAL, LyricsInfo

# Nivel de soporte de etiquetas del formato.
TAGS_FULL = "full"          # Etiquetas estándar y bien soportadas.
TAGS_LIMITED = "limited"    # Existen, pero pocos reproductores las leen (WAV, AIFF).
TAGS_NONE = "none"          # El formato no admite etiquetas (AAC ADTS, AC-3 crudo).

# Códecs cuyo contenedor habitual no se muestra en la etiqueta del formato.
NATURAL_CONTAINERS = {("Opus", "Ogg"), ("Vorbis", "Ogg"), ("Speex", "Ogg")}

LYRICS_SYNCED = "synced"
LYRICS_UNSYNCED = "unsynced"
LYRICS_NONE = "none"


@dataclass
class Track:
    """Representa una canción encontrada por el escáner."""
    filename: str
    filepath: Path
    extension: str
    size: int

    # Formato real, detectado a partir del contenido.
    container: str | None = None
    codec: str | None = None
    lossless: bool | None = None
    dolby: bool = False
    sample_rate: int | None = None
    bits_per_sample: int | None = None
    channels: int | None = None
    duration: float | None = None
    bitrate: int | None = None
    extension_mismatch: bool = False

    # Capacidades del formato.
    tag_support: str = TAGS_FULL
    embedded_lyrics_supported: bool = True

    # Etiquetas básicas.
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None

    # Letras y portadas.
    lyrics: list[LyricsInfo] = field(default_factory=list)
    has_embedded_cover: bool = False
    folder_cover: Path | None = None

    notes: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def has_lyrics(self) -> bool:
        return any(not lyr.empty for lyr in self.lyrics)

    @property
    def has_synced_lyrics(self) -> bool:
        return any(lyr.synced for lyr in self.lyrics)

    @property
    def lyrics_status(self) -> str:
        if self.has_synced_lyrics:
            return LYRICS_SYNCED
        if self.has_lyrics:
            return LYRICS_UNSYNCED
        return LYRICS_NONE

    @property
    def has_cover(self) -> bool:
        return self.has_embedded_cover or self.folder_cover is not None

    @property
    def format_label(self) -> str:
        """Ej.: "FLAC", "ALAC (MP4)", "AC-3 (Matroska)"."""
        if self.codec is None:
            return "Desconocido"
        if (self.container and self.container != self.codec
                and (self.codec, self.container) not in NATURAL_CONTAINERS):
            return f"{self.codec} ({self.container})"
        return self.codec

    @property
    def quality_key(self) -> tuple[int | None, int | None]:
        """(bits, frecuencia). Los bits solo tienen sentido sin pérdida."""
        bits = self.bits_per_sample if self.lossless else None
        return (bits, self.sample_rate)

    def to_dict(self, root: Path | None = None) -> dict:
        def rel(path: Path | None) -> str | None:
            if path is None:
                return None
            if root is not None:
                try:
                    return path.relative_to(root).as_posix()
                except ValueError:
                    pass
            return str(path)

        return {
            "path": rel(self.filepath),
            "size": self.size,
            "extension": self.extension,
            "container": self.container,
            "codec": self.codec,
            "format": self.format_label,
            "lossless": self.lossless,
            "dolby": self.dolby,
            "sample_rate": self.sample_rate,
            "bits_per_sample": self.bits_per_sample,
            "channels": self.channels,
            "duration": self.duration,
            "bitrate": self.bitrate,
            "extension_mismatch": self.extension_mismatch,
            "tag_support": self.tag_support,
            "embedded_lyrics_supported": self.embedded_lyrics_supported,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "album_artist": self.album_artist,
            "lyrics_status": self.lyrics_status,
            "lyrics": [
                {
                    **lyr.to_dict(),
                    "location": rel(Path(lyr.location))
                    if lyr.source == SOURCE_EXTERNAL else lyr.location,
                }
                for lyr in self.lyrics
            ],
            "has_embedded_cover": self.has_embedded_cover,
            "folder_cover": rel(self.folder_cover),
            "notes": list(self.notes),
            "error": self.error,
        }
