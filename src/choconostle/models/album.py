"""
album.py

Modelo que representa un álbum: un grupo de pistas, ya sea por carpeta
o por etiqueta de álbum.

Responsabilidad:
- Almacenar las pistas de un álbum y datos derivados simples.
- No contiene lógica de agrupación (ver albums.py).

Autor: AndrewSkarlet
Licencia: MIT
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from choconostle.models.track import Track


@dataclass
class Album:
    """Un álbum de la biblioteca."""
    key: str
    name: str
    folders: list[Path] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    folder_covers: list[Path] = field(default_factory=list)

    @property
    def formats(self) -> Counter:
        return Counter(t.format_label for t in self.tracks)

    @property
    def qualities(self) -> Counter:
        return Counter(t.quality_key for t in self.tracks)

    @property
    def has_mixed_formats(self) -> bool:
        return len(self.formats) > 1

    @property
    def has_mixed_quality(self) -> bool:
        return len(self.qualities) > 1

    @property
    def embedded_cover_count(self) -> int:
        return sum(1 for t in self.tracks if t.has_embedded_cover)

    @property
    def missing_cover(self) -> bool:
        """Sin Cover.jpg/Folder.jpg y sin portada incrustada en ninguna pista."""
        return not self.folder_covers and self.embedded_cover_count == 0
