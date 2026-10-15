"""
track.py

Modelo que representa una pista musical dentro de la biblioteca.

Responsabilidad:
- Almacenar información de una canción.
- No contiene lógica de análisis.

Autor: Andrew
Licencia: MIT
"""

from dataclasses import dataclass


@dataclass
class Track:
    """Representa una canción encontrada por el escáner."""
    filename: str
    filepath: str
    extension: str
    size: int