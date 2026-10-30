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


@pytest.fixture(params=["posix", "windows"])
def paths_mode(request):
    """
    Ejecuta la prueba con el comportamiento de os.path.isdir/exists/isfile/
    lexists de cada sistema (igual que el simulador Unplug de test_run.py):
    - "posix": pasan por os.stat en tiempo de ejecución, como en Linux.
    - "windows": no pasan por os.stat (en Windows son funciones en C,
      nt._path_isdir...); aquí usan la os.stat real capturada al inicio.
    """
    import os
    import stat

    real_stat = os.stat
    statter = (lambda path: os.stat(path)) if request.param == "posix" else real_stat

    def check(test):
        def inner(path):
            try:
                result = statter(path)
            except (OSError, ValueError):
                return False
            return True if test is None else test(result.st_mode)
        return inner
    # Instancia propia: las pruebas que "reconectan" con monkeypatch.undo() no deshacen el modo.
    patcher = pytest.MonkeyPatch()
    for name, test in [("isdir", stat.S_ISDIR), ("isfile", stat.S_ISREG), ("exists", None), ("lexists", None)]:
        patcher.setattr(os.path, name, check(test))
    yield request.param
    patcher.undo()


@pytest.fixture(scope="session")
def original(casos):
    """Bytes de todos los archivos de la biblioteca de casos, tal como se generó."""
    from test_run import files
    return files(casos)


@pytest.fixture(scope="session")
def reference(casos, tmp_path_factory):
    """Biblioteca tras aplicar normalize-lyrics (subconjunto ONLY) sin interrupciones."""
    from test_run import files, start
    from choconostle import run as runs
    root = tmp_path_factory.mktemp("ref") / "lib"
    shutil.copytree(casos, root)
    normalizer, execution = start(root)
    summary = runs.apply_run(execution, normalizer, root)
    assert summary.stopped is None and summary.failed == 0
    return files(root)
