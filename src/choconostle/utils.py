"""
utils.py

Funciones auxiliares de formato.

Autor: AndrewSkarlet
Licencia: MIT
"""

from __future__ import annotations

import os
from pathlib import Path


def format_size(size: int) -> str:
    """1536 -> "1.5 KB"."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def format_duration(seconds: float | None) -> str:
    """3725 -> "1:02:05"."""
    if not seconds:
        return "-"
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_elapsed(seconds: float) -> str:
    """Tiempo total de un comando: 2.34 -> "2,3 s"; 125 -> "2 min 05 s"; 3725 -> "1 h 02 min 05 s"."""
    if seconds < 60:
        return f"{seconds:.1f} s".replace(".", ",")
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes:02d} min {secs:02d} s"
    return f"{minutes} min {secs:02d} s"


# Reloj del comando en curso (cli.py lo inicia al empezar cada comando con resumen).
_CLOCK: dict = {"start": None, "shown": False}


def start_clock() -> None:
    import time
    _CLOCK.update(start=time.perf_counter(), shown=False)


def stop_clock() -> None:
    _CLOCK.update(start=None, shown=False)


def elapsed_line(mark_shown: bool = True) -> str | None:
    """"Tiempo total: ..." desde start_clock(), o None si no hay reloj en marcha."""
    import time
    if _CLOCK["start"] is None:
        return None
    if mark_shown:
        _CLOCK["shown"] = True
    return f"Tiempo total: {format_elapsed(time.perf_counter() - _CLOCK['start'])}"


def elapsed_shown() -> bool:
    return bool(_CLOCK["shown"])


def format_sample_rate(rate: int | None) -> str:
    """44100 -> "44.1 kHz"."""
    if not rate:
        return "? kHz"
    khz = rate / 1000
    return f"{khz:g} kHz"


def format_quality(bits: int | None, rate: int | None) -> str:
    """(24, 96000) -> "24 bits / 96 kHz"; sin bits -> "44.1 kHz"."""
    if bits:
        return f"{bits} bits / {format_sample_rate(rate)}"
    return format_sample_rate(rate)


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    """plural(1, "pista") -> "1 pista"; plural(3, "pista") -> "3 pistas"."""
    word = singular if count == 1 else (plural_form or singular + "s")
    return f"{count} {word}"


def percent(part: int, total: int) -> str:
    if not total:
        return "0%"
    return f"{part * 100 / total:.1f}%"


# Windows limita las rutas a 260 caracteres salvo con el prefijo \\?\ (o con
# LongPathsEnabled en el registro y Python 3.6+). Se añade el prefijo a partir
# de este largo para dejar margen a los nombres temporales.
_LONG_PATH = 240


def long_path(path, windows: bool | None = None) -> str:
    r"""
    Ruta utilizable por las funciones de archivos aunque sea larga.

    En Windows, una ruta absoluta de 240 caracteres o más recibe el prefijo
    \\?\ (o \\?\UNC\ para rutas de red). En Linux, macOS y Android se
    devuelve tal cual.
    """
    windows = os.name == "nt" if windows is None else windows
    text = os.fspath(path)
    if not windows or text.startswith("\\\\?\\"):
        return text
    if windows and os.name == "nt":
        text = os.path.abspath(text)
    if len(text) < _LONG_PATH:
        return text
    text = text.replace("/", "\\")
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def fsync_file(handle) -> None:
    handle.flush()
    os.fsync(handle.fileno())


def write_file_atomic(path: Path, data: bytes) -> None:
    """
    Escribe un archivo de forma segura: primero en uno temporal junto al
    original y luego lo reemplaza, para no dejarlo a medias si algo falla.
    """
    temporary = path.with_name(path.name + ".choconostle-tmp")
    try:
        with open(long_path(temporary), "wb") as handle:
            handle.write(data)
            fsync_file(handle)
        os.replace(long_path(temporary), long_path(path))
    finally:
        if os.path.exists(long_path(temporary)):
            os.unlink(long_path(temporary))
