"""
Regresión de memoria (etapa ⑥): el pico de Python al planificar, aplicar,
mostrar el reporte y revertir no debe crecer con el número de archivos.

Se compara una biblioteca ×1 con otra ×20, hechas copiando carpetas de
tools/generar_casos.py (fixture `casos`). Se usan las carpetas de letras
.lrc para que la prueba sea rápida; cada copia añade las mismas entradas.
La medición es determinista: tracemalloc cuenta solo memoria de Python.
"""

import io
import shutil
import tracemalloc
from pathlib import Path

from rich.console import Console

from choconostle import run as runs
from choconostle.normalizer import MODE_STRIP, LyricsNormalizer
from choconostle.report import print_run_report

FOLDERS = ["02_saltos_de_linea", "03_cabeceras"]
LIMIT_PER_ENTRY = 1024
"""
Bytes de pico que puede añadir cada entrada aplicada. Medido en la etapa ⑥:
648 con las correcciones y 2388 sin ellas (los eventos del diario y los
resultados de revert enteros en memoria).
"""


def library(casos: Path, target: Path, copies: int) -> Path:
    for index in range(copies):
        for folder in FOLDERS:
            shutil.copytree(casos / folder, target / f"copia_{index:02d}" / folder)
    return target


def peak(root: Path) -> tuple[int, int]:
    """(pico de Python en bytes, entradas aplicadas) de un ciclo completo."""
    tracemalloc.start()
    try:
        normalizer = LyricsNormalizer(MODE_STRIP)
        execution = runs.Run.create(root, "normalize-lyrics", dict(normalizer.options(), verify="auto"))
        runs.plan_library(execution, normalizer, root)
        summary = runs.apply_run(execution, normalizer, root)
        console = Console(file=io.StringIO(), width=120)
        print_run_report(runs.Run(execution.folder), console=console, applied=True, summary=summary)
        runs.revert_run(execution.folder)
        return tracemalloc.get_traced_memory()[1], summary.applied
    finally:
        tracemalloc.stop()


def test_memory_does_not_grow_with_library(casos, tmp_path):
    small_peak, small = peak(library(casos, tmp_path / "x1", 1))
    large_peak, large = peak(library(casos, tmp_path / "x20", 20))
    assert small > 0 and large == 20 * small
    per_entry = (large_peak - small_peak) / (large - small)
    assert per_entry < LIMIT_PER_ENTRY, (
        f"el pico creció {per_entry:.0f} bytes por entrada ({small_peak} → {large_peak})")
