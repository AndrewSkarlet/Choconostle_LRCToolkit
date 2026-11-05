"""
Pruebas de fix-gallery sobre copias de la biblioteca de tools/generar_casos.py.

El generador no crea imágenes: cada prueba añade portadas de pocos bytes
(cover.jpg y COVER.JPG) en su copia. Todas se ejecutan en los modos
"posix" y "windows" de rutas (fixture paths_mode).
"""

import json
import shutil

import pytest
from typer.testing import CliRunner

from choconostle.cli import app
from choconostle.config import BACKUP_DIR_NAME
from choconostle.gallery import RECORD_NAME
from test_run import Unplug, eio, win_error

runner = CliRunner()
ENV = {"COLUMNS": "200"}
WITH_IMAGES = ["01_codificaciones", "03_cabeceras", "06_traducciones"]
WITHOUT_IMAGES = "02_saltos_de_linea"


def invoke(*args):
    return runner.invoke(app, ["fix-gallery", *map(str, args), "--no-progress"], env=ENV)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def nomedia(root):
    return sorted(p.parent.relative_to(root).as_posix() for p in root.rglob(".nomedia"))


def record(root):
    return json.loads((root / BACKUP_DIR_NAME / RECORD_NAME).read_text(encoding="utf-8"))["carpetas"]


@pytest.fixture
def lib(biblioteca, paths_mode):
    (biblioteca / WITH_IMAGES[0] / "cover.jpg").write_bytes(b"\xff\xd8\xff")
    (biblioteca / WITH_IMAGES[1] / "COVER.JPG").write_bytes(b"\xff\xd8\xff")  # extensión en mayúsculas
    (biblioteca / WITH_IMAGES[2] / "folder.webp").write_bytes(b"RIFF")
    return biblioteca


def test_simulation_changes_nothing(lib):
    before = snapshot(lib)
    result = invoke(lib)
    assert result.exit_code == 0, result.output
    assert "SIMULACIÓN" in result.output
    for folder in WITH_IMAGES:
        assert f"  {folder}\n" in result.output
    assert WITHOUT_IMAGES not in result.output
    assert "se crearían 3" in result.output
    assert snapshot(lib) == before
    assert not (lib / BACKUP_DIR_NAME).exists()


def test_apply_repeat_and_remove(lib):
    before = snapshot(lib)
    result = invoke(lib, "--apply")
    assert result.exit_code == 0, result.output
    assert "creadas 3, ya existentes 0" in result.output
    assert nomedia(lib) == sorted(WITH_IMAGES)
    assert all((lib / f / ".nomedia").read_bytes() == b"" for f in WITH_IMAGES)
    assert record(lib) == {f: "creado" for f in WITH_IMAGES}
    # Ni audio, ni letras, ni portadas cambian: solo se añaden los .nomedia.
    after = {k: v for k, v in snapshot(lib).items() if not k.endswith(".nomedia") and BACKUP_DIR_NAME not in k}
    assert after == before

    # Repetir no cambia nada.
    state = snapshot(lib)
    result = invoke(lib, "--apply")
    assert result.exit_code == 0, result.output
    assert "creadas 0, ya existentes 3" in result.output
    assert snapshot(lib) == state

    # --remove simula; con --apply quita lo creado.
    result = invoke(lib, "--remove")
    assert result.exit_code == 0 and "se quitarían 3" in result.output, result.output
    assert nomedia(lib) == sorted(WITH_IMAGES)
    result = invoke(lib, "--remove", "--apply")
    assert result.exit_code == 0 and "quitadas 3" in result.output, result.output
    assert nomedia(lib) == []
    assert record(lib) == {}
    assert {k: v for k, v in snapshot(lib).items() if BACKUP_DIR_NAME not in k} == before


def test_remove_never_touches_preexisting(lib):
    (lib / WITH_IMAGES[0] / ".nomedia").write_bytes(b"")               # ya existía, vacío
    (lib / WITHOUT_IMAGES / ".nomedia").write_bytes(b"del usuario")    # ya existía, con contenido
    result = invoke(lib, "--apply")
    assert result.exit_code == 0, result.output
    assert "creadas 2, ya existentes 1" in result.output
    assert sorted(record(lib)) == sorted(WITH_IMAGES[1:])
    result = invoke(lib, "--remove", "--apply")
    assert result.exit_code == 0 and "quitadas 2" in result.output, result.output
    assert nomedia(lib) == sorted([WITH_IMAGES[0], WITHOUT_IMAGES])
    assert (lib / WITHOUT_IMAGES / ".nomedia").read_bytes() == b"del usuario"


def test_remove_keeps_created_file_with_content(lib):
    invoke(lib, "--apply")
    (lib / WITH_IMAGES[0] / ".nomedia").write_bytes(b"cambiado")
    result = invoke(lib, "--remove", "--apply")
    assert result.exit_code == 0, result.output
    assert "conservadas 1" in result.output and "tiene contenido" in result.output
    assert nomedia(lib) == [WITH_IMAGES[0]]


def test_folder_without_images_and_all_folders(lib):
    result = invoke(lib, "--apply")
    assert result.exit_code == 0, result.output
    assert not (lib / WITHOUT_IMAGES / ".nomedia").exists()
    result = invoke(lib, "--all-folders", "--apply")
    assert result.exit_code == 0, result.output
    assert (lib / WITHOUT_IMAGES / ".nomedia").exists()
    audio_folders = sorted(p.relative_to(lib).as_posix() for p in lib.iterdir()
                           if p.is_dir() and p.name != BACKUP_DIR_NAME)
    assert set(audio_folders) <= set(nomedia(lib))
    assert "." not in nomedia(lib)  # raíz protegida también con --all-folders


def test_only(lib):
    result = invoke(lib, "--apply", "--only", WITH_IMAGES[1])
    assert result.exit_code == 0, result.output
    assert nomedia(lib) == [WITH_IMAGES[1]]
    # Nombre de álbum (etiqueta ALBUM = nombre de la carpeta en los casos generados).
    result = invoke(lib, "--apply", "--only", WITH_IMAGES[0].upper(), "--only", WITH_IMAGES[0])
    assert result.exit_code == 0, result.output
    assert nomedia(lib) == sorted(WITH_IMAGES[:2])
    result = invoke(lib, "--only", "Álbum que no existe")
    assert result.exit_code == 2


def test_root_protected_unless_include_root(lib):
    (lib / "cover.jpg").write_bytes(b"\xff\xd8\xff")
    music = lib / "Music"
    music.mkdir()
    flac = next((lib / "03_cabeceras").glob("*.flac"))
    shutil.copy2(flac, music / flac.name)
    (music / "folder.png").write_bytes(b"\x89PNG")

    result = invoke(lib, "--apply")
    assert result.exit_code == 0, result.output
    assert "La carpeta raíz queda fuera" in result.output
    assert "carpeta de sistema (Music)" in result.output
    assert "protegidas 2" in result.output
    assert not (lib / ".nomedia").exists() and not (music / ".nomedia").exists()

    result = invoke(lib, "--apply", "--include-root")
    assert result.exit_code == 0, result.output
    assert "La carpeta raíz queda fuera" not in result.output
    assert (lib / ".nomedia").exists() and (music / ".nomedia").exists()
    assert {".", "Music"} <= set(record(lib))
    invoke(lib, "--remove", "--apply")
    assert nomedia(lib) == []


def test_album_folder_given_directly(lib):
    """Una carpeta con audio y sin subcarpetas con audio es un álbum, no una raíz."""
    album = lib / WITH_IMAGES[0]
    result = invoke(album, "--apply")
    assert result.exit_code == 0, result.output
    assert "La carpeta raíz queda fuera" not in result.output
    assert (album / ".nomedia").exists()
    assert record(album) == {".": "creado"}
    result = invoke(album, "--remove", "--apply")
    assert result.exit_code == 0, result.output
    assert not (album / ".nomedia").exists()


def test_album_folder_named_music_stays_protected(lib):
    music = lib / "Music"
    (lib / WITH_IMAGES[0]).rename(music)
    result = invoke(music, "--apply")
    assert result.exit_code == 0, result.output
    assert "carpeta de sistema (Music)" in result.output
    assert not (music / ".nomedia").exists()
    assert invoke(music, "--apply", "--include-root").exit_code == 0
    assert (music / ".nomedia").exists()


@pytest.mark.parametrize("error", [eio, lambda: win_error(1167), lambda: win_error(3)],
                         ids=["EIO", "WinError1167", "WinError3"])
def test_drive_disconnected(lib, monkeypatch, paths_mode, error):
    unplug = Unplug(monkeypatch, lib, after=2, error=error, paths=paths_mode)
    result = invoke(lib, "--apply")
    assert unplug.unplugged
    assert result.exit_code == 3, result.output
    assert "SE DETUVO" in result.output and "fix-gallery" in result.output
    monkeypatch.undo()  # se vuelve a conectar
    assert nomedia(lib) == [WITH_IMAGES[0]]
    result = invoke(lib, "--apply")
    assert result.exit_code == 0, result.output
    assert nomedia(lib) == sorted(WITH_IMAGES)
    # Lo creado antes de la desconexión también queda anotado y se puede quitar.
    assert record(lib) == {f: "creado" for f in WITH_IMAGES}
    result = invoke(lib, "--remove", "--apply")
    assert result.exit_code == 0, result.output
    assert nomedia(lib) == []


def test_drive_disconnected_during_remove(lib, monkeypatch, paths_mode):
    import os
    assert invoke(lib, "--apply").exit_code == 0
    unplug = Unplug(monkeypatch, lib, after=10**9, error=eio, paths=paths_mode)
    real_unlink = os.unlink

    def unlink_then_unplug(path, *args, **kwargs):  # la unidad se va tras el primer borrado
        real_unlink(path, *args, **kwargs)
        unplug.unplugged = True
    monkeypatch.setattr(os, "unlink", unlink_then_unplug)
    result = invoke(lib, "--remove", "--apply")
    assert result.exit_code == 3, result.output
    assert "SE DETUVO" in result.output
    monkeypatch.undo()
    assert nomedia(lib) == sorted(WITH_IMAGES[1:])
    result = invoke(lib, "--remove", "--apply")
    assert result.exit_code == 0, result.output
    assert nomedia(lib) == []
    assert record(lib) == {}


def test_drive_missing_at_start(lib, monkeypatch, paths_mode):
    unplug = Unplug(monkeypatch, lib, after=10**9, error=lambda: win_error(1167), paths=paths_mode)
    unplug.unplugged = True
    assert invoke(lib, "--apply").exit_code == 3
    assert invoke(lib, "--remove", "--apply").exit_code == 3
    monkeypatch.undo()
    assert nomedia(lib) == []


def test_clean_backups_keeps_record(lib):
    assert invoke(lib, "--apply").exit_code == 0
    result = runner.invoke(app, ["normalize-lyrics", str(lib), "--strip-headers", "--apply", "--no-progress",
                                 "--only", "03_cabeceras"], env=ENV)
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["clean-backups", str(lib), "--older-than", "0", "--apply"], env=ENV)
    assert result.exit_code == 0, result.output
    assert "Borrados (1" in result.output
    remaining = [p.name for p in (lib / BACKUP_DIR_NAME).iterdir()]
    assert remaining == [RECORD_NAME]
    assert record(lib) == {f: "creado" for f in WITH_IMAGES}
