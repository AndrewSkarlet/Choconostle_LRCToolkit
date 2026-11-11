"""
suspicious.py

Avisos de letras sospechosas (solo se informa; nunca se modifica nada):

- con una URL o un dominio (www., http..., algo.com): publicidad o créditos
  de la web de origen;
- el mismo texto de letra en muchas canciones distintas (por defecto 5 o
  más): suele ser un texto de relleno («Lyrics not available») o publicidad,
  aunque también pueden ser remixes y versiones (Slowed, Sped Up), por eso se
  muestran los títulos de cada grupo;
- muy cortas que no parecen letra: menos de SHORT_MAX_LETTERS letras en total.
  Las «casi vacías» (pocas líneas) ya tienen su propia sección y no se
  repiten aquí, y las instrumentales ([instrumental:true]) no cuentan.

Lo usan scan (pantalla y JSON) y la simulación de normalize-lyrics.

Autor: AndrewSkarlet
Licencia: MIT
"""

from __future__ import annotations

import hashlib
import re

from choconostle import lrc
from choconostle.textio import line_contents, strip_invisible_prefix

REPEAT_THRESHOLD = 5
"""Canciones distintas con el mismo texto a partir de las que se avisa (--repeat-threshold)."""
SHORT_MAX_LETTERS = 40
"""Menos letras (caracteres alfabéticos) que esto en toda la letra: «muy corta»."""

# Dominios sin www. ni http: solo terminaciones poco ambiguas (.es, .me o .co
# darían falsos positivos como «mira.Es la vida»).
_TLDS = "com|net|org|info|xyz|top|site|online|club|biz|lyrics|ru|cn"
URL_RE = re.compile(
    r"(?:https?://\S+|www\.\S+|\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:" + _TLDS + r")\b(?:/\S*)?)",
    re.IGNORECASE,
)
_WORD_TIMESTAMP_RE = lrc.WORD_TIMESTAMP_RE


def lyric_lines(text: str) -> list[str]:
    """Líneas de texto de la letra: sin marcas de tiempo, cabeceras, secciones ni datos extendidos."""
    lines = []
    for line in line_contents(text or ""):
        _prefix, core = strip_invisible_prefix(line)
        timestamp = lrc.TIMESTAMP_RE.match(core)
        if timestamp:
            core = core[timestamp.end():]
        elif lrc.header_key(core) or lrc.is_section(core):
            continue
        core = _WORD_TIMESTAMP_RE.sub("", core).strip()
        if core and not lrc.is_section(core):
            lines.append(core)
    return lines


def find_url(text: str) -> str | None:
    """Primera URL o dominio del texto de la letra (incluidas las cabeceras), o None."""
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(".,;:)]}\"'") if match else None


def text_key(lines: list[str]) -> int | None:
    """
    Clave del texto para comparar letras entre canciones: sin marcas de
    tiempo, cabeceras, mayúsculas ni espacios. Un entero de 60 bits (poca
    memoria aunque haya miles de letras).
    """
    normal = "\n".join(" ".join(line.lower().split()) for line in lines)
    if not normal:
        return None
    return int(hashlib.sha1(normal.encode("utf-8")).hexdigest()[:15], 16)


def profile(text: str, nearly_empty: bool = False, instrumental: bool = False) -> dict:
    """
    Datos de una letra para los avisos: {"url": str|None, "key": int|None,
    "short": bool}. "short" nunca coincide con «casi vacía» ni instrumental.
    """
    lines = lyric_lines(text)
    letters = sum(1 for line in lines for char in line if char.isalpha())
    return {
        "url": find_url(text),
        "key": None if instrumental else text_key(lines),
        "short": bool(lines) and letters < SHORT_MAX_LETTERS and not nearly_empty and not instrumental,
    }


def song_label(title: str | None, path: str | None) -> str:
    """Título y ruta de la canción, para distinguir remixes y versiones (Slowed, Sped Up)."""
    if title and path:
        return f"{title} ({path})"
    return title or path or "?"


def repeated_groups(items, threshold: int = REPEAT_THRESHOLD) -> list[dict]:
    """
    Grupos de canciones distintas con el mismo texto de letra.

    `items()` se puede llamar dos veces y da (clave, canción, etiqueta).

    1. Primera pasada, con poca memoria: por clave solo un contador y un
       número que identifica la última canción. Las letras de una misma
       canción (.lrc e incrustada) van seguidas, así que casi nunca se
       cuentan dos veces; si pasa, el contador sobra, no falta.
    2. Segunda pasada, solo para las claves que llegaron al umbral: se
       cuentan las canciones distintas de verdad y se guardan sus etiquetas.

    Retorna [{"count": n, "songs": [etiquetas]}], de mayor a menor.
    """
    counts: dict[int, list] = {}
    for key, song, _label in items():
        if key is None:
            continue
        song_id = hash(song)
        entry = counts.get(key)
        if entry is None:
            counts[key] = [1, song_id]
        elif entry[1] != song_id:
            entry[0] += 1
            entry[1] = song_id
    wanted = {key for key, (count, _song) in counts.items() if count >= threshold}
    del counts
    if not wanted:
        return []
    groups: dict[int, dict] = {key: {"songs": [], "seen": set()} for key in wanted}
    for key, song, label in items():
        group = groups.get(key)
        if group is None or song in group["seen"]:
            continue
        group["seen"].add(song)
        group["songs"].append(label)
    result = [{"count": len(group["songs"]), "songs": group["songs"]} for group in groups.values()
              if len(group["songs"]) >= threshold]
    return sorted(result, key=lambda group: (-group["count"], group["songs"][:1]))
