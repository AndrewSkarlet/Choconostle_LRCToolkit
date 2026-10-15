"""
models

Modelos de datos utilizados por Choconostle LRC Toolkit.

Responsabilidad:
- Definir las estructuras de datos del programa.
- No contiene lógica de negocio.

Autor: Andrew
Licencia: MIT
"""

from choconostle.models.album import Album
from choconostle.models.lyrics import LyricsInfo
from choconostle.models.track import Track

__all__ = ["Album", "LyricsInfo", "Track"]
