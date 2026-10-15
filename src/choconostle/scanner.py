"""
scanner.py

Escanea una biblioteca musical y crea objetos Track.

Responsabilidades:
- Recorrer carpetas.
- Detectar archivos compatibles.
- Crear objetos Track.

Autor: Andrew
Licencia: MIT
"""

from pathlib import Path

from choconostle.models.track import Track


def scan_directory(directory: Path):
    """
    Escanea una carpeta completa.

    Parámetros
    ----------
    directory : Path
        Ruta de la biblioteca musical.

    Retorna
    -------
    list[Track]
        Lista de canciones encontradas.
    """
    pass


from choconostle.models.track import Track
from choconostle.config import (
    SUPPORTED_AUDIO,
    SUPPORTED_LYRICS,
    SUPPORTED_IMAGES,
)


def create_track(file: Path):
    """
    Convierte un archivo encontrado en un objeto Track.
    """
    pass