"""
lyrics.py

Modelo que describe una letra encontrada, ya sea un archivo externo
(.lrc / .txt) o una letra incrustada en las etiquetas del audio.

Responsabilidad:
- Almacenar el resultado del análisis de una letra.
- No contiene lógica de análisis (ver lrc.py).

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field

SOURCE_EXTERNAL = "external"
SOURCE_EMBEDDED = "embedded"


@dataclass
class LyricsInfo:
    """Resultado del análisis de una letra."""
    source: str
    """SOURCE_EXTERNAL o SOURCE_EMBEDDED."""
    location: str
    """Ruta del archivo externo, o nombre de la etiqueta (USLT, SYLT, LYRICS...)."""
    synced: bool = False
    """True si tiene marcas de tiempo ([mm:ss.xx]), sin importar la extensión."""
    timestamp_lines: int = 0
    plain_lines: int = 0
    """Líneas con texto pero sin marca de tiempo (ni cabecera)."""
    headers: list[str] = field(default_factory=list)
    """Cabeceras LRC encontradas, en minúsculas: ["ar", "ti", "length"...]."""
    has_bom: bool = False
    encoding: str = "utf-8"
    is_utf8: bool = True
    empty: bool = False
    content_lines: int = 0
    """Líneas con texto de la letra (sin contar cabeceras ni marcas vacías)."""
    nearly_empty: bool = False
    """Pocas líneas con texto (ver NEARLY_EMPTY_MAX_LINES). Se marcan, no se corrigen."""
    error: str | None = None

    @property
    def has_headers(self) -> bool:
        return bool(self.headers)

    @property
    def needs_fix(self) -> bool:
        """True si la Fase 2 debería corregir esta letra."""
        return self.has_headers or self.has_bom or not self.is_utf8

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "location": self.location,
            "synced": self.synced,
            "timestamp_lines": self.timestamp_lines,
            "plain_lines": self.plain_lines,
            "headers": list(self.headers),
            "has_bom": self.has_bom,
            "encoding": self.encoding,
            "is_utf8": self.is_utf8,
            "empty": self.empty,
            "content_lines": self.content_lines,
            "nearly_empty": self.nearly_empty,
            "needs_fix": self.needs_fix,
            "error": self.error,
        }
