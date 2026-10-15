"""
cli.py

Interfaz de línea de comandos.

Uso:
    choconostle scan RUTA [--group-by folder|tag] [--json reporte.json]
    choconostle version

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from choconostle.config import APP_CODENAME, APP_DESCRIPTION, APP_NAME, APP_VERSION
from choconostle.report import build_report, print_report, write_json
from choconostle.scanner import scan_directory

app = typer.Typer(
    help=APP_DESCRIPTION,
    add_completion=False,
    no_args_is_help=True,
)


class GroupBy(str, Enum):
    folder = "folder"
    tag = "tag"


def _safe_streams() -> None:
    # Nombres de archivo con caracteres que la consola no puede mostrar
    # (p. ej. japonés en una consola cp1252 de Windows) no deben romper
    # el programa: se reemplazan por "?".
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


@app.command()
def scan(
    path: Path = typer.Argument(..., help="Carpeta de la biblioteca musical."),
    group_by: GroupBy = typer.Option(
        GroupBy.folder, "--group-by", "-g",
        help="Cómo agrupar álbumes para las revisiones: por carpeta o por etiqueta de álbum.",
    ),
    json_path: Optional[Path] = typer.Option(
        None, "--json", "-j",
        help="Guarda el reporte completo (todas las pistas) en un archivo JSON.",
    ),
    limit: int = typer.Option(
        20, "--limit", "-l",
        help="Máximo de elementos por lista en pantalla (0 = sin límite).",
    ),
    include_hidden: bool = typer.Option(
        False, "--include-hidden",
        help="Incluye carpetas y archivos ocultos (que empiezan con '.').",
    ),
    no_progress: bool = typer.Option(
        False, "--no-progress",
        help="No muestra el progreso del escaneo.",
    ),
) -> None:
    """Escanea una biblioteca y muestra el reporte de formatos, letras, álbumes y portadas."""
    _safe_streams()
    console = Console(highlight=False)
    error_console = Console(stderr=True, highlight=False)

    path = path.expanduser()
    if not path.is_dir():
        error_console.print(f"No es una carpeta: {path}", style="red", markup=False)
        raise typer.Exit(code=2)

    show_progress = not no_progress and error_console.is_terminal
    if show_progress:
        with Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            console=error_console,
            transient=True,
        ) as progress:
            task = progress.add_task("Escaneando...", total=None)
            count = 0

            def on_file(file: Path) -> None:
                nonlocal count
                count += 1
                progress.update(task, description=f"Escaneando... {count} archivos  {file.name}")

            result = scan_directory(path, include_hidden=include_hidden, on_file=on_file)
    else:
        result = scan_directory(path, include_hidden=include_hidden)

    report = build_report(result, group_by=group_by.value)
    print_report(report, console=console, limit=limit)

    if json_path is not None:
        write_json(report, json_path)
        console.print(f"Reporte JSON guardado en: {json_path}")


@app.command()
def version() -> None:
    """Muestra la versión del programa."""
    typer.echo(f"{APP_NAME} {APP_VERSION} ({APP_CODENAME})")


def main() -> None:
    """Inicia la aplicación."""
    app()


if __name__ == "__main__":
    main()
