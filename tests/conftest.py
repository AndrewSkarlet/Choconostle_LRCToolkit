"""
Fixtures compartidas: la biblioteca de casos de tools/generar_casos.py
(ver tools/CASOS.md), generada una sola vez por sesión en una carpeta
temporal. Cada prueba que modifica archivos trabaja sobre una copia.
"""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

GENERATOR = Path(__file__).resolve().parents[1] / "tools" / "generar_casos.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("generar_casos", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def casos(tmp_path_factory) -> Path:
    if not shutil.which("ffmpeg"):
        pytest.skip("se necesita ffmpeg para generar la biblioteca de casos")
    root = tmp_path_factory.mktemp("casos") / "Choconostle_Casos_LRC"
    try:
        load_generator().build(root)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"ffmpeg no pudo generar algún caso (¿falta un códec?): {exc}")
    return root


@pytest.fixture
def biblioteca(casos, tmp_path) -> Path:
    root = tmp_path / "lib"
    shutil.copytree(casos, root)
    return root
