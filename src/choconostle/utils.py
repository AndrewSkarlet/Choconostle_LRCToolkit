"""
utils.py

Funciones auxiliares de formato.

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations


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
