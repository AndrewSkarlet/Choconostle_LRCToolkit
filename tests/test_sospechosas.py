"""
Letras sospechosas (rc3): solo se informa, nunca se modifica nada.

Casos generados: letras con URL o dominio, el mismo texto en muchas
canciones (con títulos de remixes para distinguir versiones de publicidad),
letras muy cortas que no parecen letra, y que las «casi vacías» y las
instrumentales no se repitan en «muy cortas».
"""

import json

import pytest
from typer.testing import CliRunner

from builders import make_flac
from choconostle.cli import app
from choconostle.suspicious import find_url, profile, repeated_groups

runner = CliRunner()
ENV = {"COLUMNS": "200"}
LYRIC = ("[00:01.00]Esta es la primera línea de la canción\n[00:04.00]Sigue la segunda con más palabras\n"
         "[00:08.00]Y una tercera para pasar el umbral\n")
REPEATED = "[00:01.00]Lyrics not available for this song\n[00:02.00]Please check back later\n[00:03.00]Thanks\n"


def song(library, folder, name, text, title=None):
    make_flac(library / folder / f"{name}.flac", tags={"TITLE": title or name})
    (library / folder / f"{name}.lrc").write_text(text, encoding="utf-8")


@pytest.fixture
def library(tmp_path):
    lib = tmp_path / "lib"
    song(lib, "a", "01 url", "[ar:x]\n" + LYRIC + "[00:12.00]Letra de www.letrasgratis.com\n")
    song(lib, "a", "02 dominio", LYRIC.replace("canción", "canción en musica-letras.net"))
    for index, title in enumerate(["Hit", "Hit (Slowed)", "Hit (Sped Up)", "Otra", "Otra más"], 1):
        song(lib, "b", f"{index:02d} repetida", REPEATED, title)
    for index in range(1, 5):  # 4 canciones: por debajo del umbral por defecto
        song(lib, "c", f"{index:02d} cuatro", LYRIC.replace("primera", "única"), f"Cuatro {index}")
    song(lib, "d", "01 corta", "[00:01.00]Oh\n[00:02.00]Yeah\n[00:03.00]Ah\n")
    song(lib, "d", "02 casi vacia", "[00:01.00]Instrumental\n")
    song(lib, "d", "03 instrumental", "[instrumental:true]\n")
    song(lib, "d", "04 normal", LYRIC.replace("primera", "distinta"))
    return lib


def test_profile_and_urls():
    assert find_url("visita https://ejemplo.org/letras.") == "https://ejemplo.org/letras"
    assert find_url("WWW.Letras.COM") == "WWW.Letras.COM"
    assert find_url("mira.Es la vida") is None and find_url("Sr. Dios, 3.14 y 1.000") is None
    assert profile(LYRIC)["short"] is False
    assert profile("[00:01]Oh\n[00:02]Yeah\n[00:03]Ah\n")["short"] is True
    assert profile("[00:01]Oh\n", nearly_empty=True)["short"] is False  # ya es «casi vacía»
    assert profile("[instrumental:true]\n", instrumental=True) == {"url": None, "key": None, "short": False}
    # Mismo texto aunque cambien marcas de tiempo, cabeceras, mayúsculas o espacios.
    assert profile("[ar:A]\n[00:05.00]HOLA   mundo\n")["key"] == profile("[00:09.10]hola mundo\n")["key"]


def test_repeated_groups_counts_distinct_songs_even_if_not_adjacent():
    items = [(1, "a", "A"), (1, "b", "B"), (1, "a", "A"), (2, "c", "C"), (1, "c", "C"), (1, "a", "A")]
    assert repeated_groups(lambda: iter(items), 3) == [{"count": 3, "songs": ["A", "B", "C"]}]
    assert repeated_groups(lambda: iter(items), 4) == []  # «a» no adyacente no cuenta dos veces


def test_scan_screen_and_json(library, tmp_path):
    output = tmp_path / "r.json"
    result = runner.invoke(app, ["scan", str(library), "--json", str(output), "--no-progress", "--limit", "0"],
                           env=ENV)
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Letras sospechosas" in out and "www.letrasgratis.com" in out and "musica-letras.net" in out
    assert "Hit (Slowed)" in out and "Hit (Sped Up)" in out
    data = json.loads(output.read_text(encoding="utf-8"))["suspicious_lyrics"]
    assert data["repeat_threshold"] == 5
    assert {item["url"] for item in data["urls"]} == {"www.letrasgratis.com", "musica-letras.net"}
    assert [group["count"] for group in data["repeated"]] == [5]
    assert any("Hit (Slowed)" in label for label in data["repeated"][0]["songs"])
    short = [item["location"] for item in data["short"]]
    assert short == ["d/01 corta.lrc"]  # ni la casi vacía ni la instrumental
    nearly = [item["location"] for item in json.loads(output.read_text(encoding="utf-8"))["lyrics_nearly_empty"]]
    assert "d/02 casi vacia.lrc" in nearly and "d/01 corta.lrc" not in nearly

    result = runner.invoke(app, ["scan", str(library), "--json", str(output), "--no-progress",
                                 "--repeat-threshold", "4"], env=ENV)
    groups = json.loads(output.read_text(encoding="utf-8"))["suspicious_lyrics"]["repeated"]
    assert sorted(group["count"] for group in groups) == [4, 5]


def test_normalize_simulation_export_and_nothing_changes(library, tmp_path):
    before = {p: p.read_bytes() for p in library.rglob("*.lrc")}
    target = tmp_path / "lista.txt"
    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--no-progress",
                                 "--export", str(target)], env=ENV)
    assert result.exit_code == 0, result.output
    assert "Letras sospechosas" in result.output and "Hit (Sped Up)" in result.output
    text = target.read_text(encoding="utf-8")
    assert "Letras sospechosas" in text and "www.letrasgratis.com" in text and "d/01 corta.lrc" in text
    assert {p: p.read_bytes() for p in library.rglob("*.lrc")} == before

    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--no-progress",
                                 "--compact"], env=ENV)
    assert "letras sospechosas" in result.output and "Hit (Slowed)" not in result.output

    result = runner.invoke(app, ["normalize-lyrics", str(library), "--strip-headers", "--no-progress",
                                 "--apply"], env=ENV)
    assert result.exit_code == 0 and "Letras sospechosas" not in result.output  # solo en la simulación
    # Solo se quitó [ar:]; las sospechosas siguen igual.
    assert (library / "b" / "01 repetida.lrc").read_bytes() == before[library / "b" / "01 repetida.lrc"]
