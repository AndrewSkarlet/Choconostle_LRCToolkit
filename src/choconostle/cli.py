"""
cli.py

Interfaz de línea de comandos.

Uso:
    choconostle scan RUTA [--group-by folder|tag] [--json reporte.json]
    choconostle normalize-lyrics RUTA --strip-headers|--standardize-headers [--apply]
    choconostle revert CARPETA_DE_RESPALDO
    choconostle version

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from choconostle.config import APP_CODENAME, APP_DESCRIPTION, APP_NAME, APP_VERSION
from choconostle import backup
from choconostle.normalizer import (
    ENCODING_KEEP, MODE_STANDARDIZE, MODE_STRIP, OFFSET_FIRST, OFFSET_LAST, OFFSET_SKIP, OFFSET_SUM,
    LyricsNormalizer, SelectionError, select,
)
from choconostle.report import (
    build_report, print_normalize_plan, print_report, print_revert, write_json,
)
from choconostle.scanner import LibraryScan, scan_directory
from choconostle.textio import EncodingOptionError, parse_target_encoding

app = typer.Typer(
    help=APP_DESCRIPTION,
    add_completion=False,
    no_args_is_help=True,
)


class GroupBy(str, Enum):
    folder = "folder"
    tag = "tag"


class OffsetPolicy(str, Enum):
    skip = OFFSET_SKIP
    first = OFFSET_FIRST
    last = OFFSET_LAST
    sum = OFFSET_SUM


def _safe_streams() -> None:
    # Nombres de archivo con caracteres que la consola no puede mostrar
    # (p. ej. japonés en una consola cp1252 de Windows) no deben romper
    # el programa: se reemplazan por "?".
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def _scan(path: Path, include_hidden: bool, no_progress: bool, error_console: Console) -> LibraryScan:
    """Escanea mostrando el progreso si la salida es una terminal."""
    if no_progress or not error_console.is_terminal:
        return scan_directory(path, include_hidden=include_hidden)
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

        return scan_directory(path, include_hidden=include_hidden, on_file=on_file)


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

    result = _scan(path, include_hidden, no_progress, error_console)
    report = build_report(result, group_by=group_by.value)
    print_report(report, console=console, limit=limit)

    if json_path is not None:
        write_json(report, json_path)
        console.print(f"Reporte JSON guardado en: {json_path}")


@app.command("normalize-lyrics")
def normalize_lyrics(
    path: Path = typer.Argument(..., help="Carpeta de la biblioteca musical."),
    strip_headers: bool = typer.Option(
        False, "--strip-headers",
        help="Quita las cabeceras LRC conocidas (\\[ar:], \\[ti:], \\[by:], \\[lr:], \\[hash:]...). "
             "Si hay un único \\[offset:] válido, lo aplica a las marcas de tiempo antes de quitarlo.",
    ),
    standardize_headers: bool = typer.Option(
        False, "--standardize-headers",
        help="Deja solo \\[ar:], \\[ti:], \\[al:] y \\[length:] con datos de las etiquetas de la canción.",
    ),
    strip_unknown_headers: bool = typer.Option(
        False, "--strip-unknown-headers",
        help="Quita también las líneas con forma \\[palabra:valor] desconocidas del inicio "
             "(p. ej. \\[xtrack:7]). Por defecto se conservan.",
    ),
    offset_policy: OffsetPolicy = typer.Option(
        OffsetPolicy.skip, "--offset-policy",
        help="Con dos o más \\[offset:]: skip (no tocar el archivo y listarlo), first, last o sum. "
             "Un \\[offset:] inválido nunca se aplica.",
    ),
    skip_near_empty: bool = typer.Option(
        False, "--skip-near-empty",
        help="Omite las letras casi vacías (por defecto se procesan con un aviso).",
    ),
    encoding: str = typer.Option(
        ENCODING_KEEP, "--encoding", "-e",
        help="Codificación de los .lrc/.txt: keep (conserva la actual, por defecto), utf8 (sin BOM), "
             "utf8-bom o cualquier códec de Python (cp1252, shift_jis, gbk...). Si algún carácter "
             "no cabe, el archivo se omite. Para más opciones usa convert-lyrics.",
    ),
    only: Optional[List[str]] = typer.Option(
        None, "--only", "-o",
        help="Limita a una carpeta (ruta) o álbum (nombre). Se puede repetir.",
    ),
    apply: bool = typer.Option(
        False, "--apply",
        help="Aplica los cambios. Sin esta opción solo se muestra qué cambiaría.",
    ),
    diff: bool = typer.Option(False, "--diff", help="Muestra las diferencias línea por línea."),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-l",
        help="Máximo de canciones por lista en pantalla (0 = sin límite). "
             "Por defecto 20, o sin límite con --diff.",
    ),
    include_hidden: bool = typer.Option(
        False, "--include-hidden",
        help="Incluye carpetas y archivos ocultos (que empiezan con '.').",
    ),
    no_progress: bool = typer.Option(False, "--no-progress", help="No muestra el progreso del escaneo."),
) -> None:
    """Quita o estandariza las cabeceras de las letras (archivos y etiquetas incrustadas)."""
    _safe_streams()
    console = Console(highlight=False)
    error_console = Console(stderr=True, highlight=False)

    if strip_headers == standardize_headers:
        error_console.print("Elige un modo: --strip-headers o --standardize-headers.", style="red")
        raise typer.Exit(code=2)
    mode = MODE_STRIP if strip_headers else MODE_STANDARDIZE
    try:
        parse_target_encoding(encoding)
    except EncodingOptionError as exc:
        error_console.print(str(exc), style="red", markup=False)
        raise typer.Exit(code=2)

    path = path.expanduser()
    if not path.is_dir():
        error_console.print(f"No es una carpeta: {path}", style="red", markup=False)
        raise typer.Exit(code=2)

    result = _scan(path, include_hidden, no_progress, error_console)
    try:
        tracks, orphans = select(result, only or [])
    except SelectionError as exc:
        error_console.print(str(exc), style="red", markup=False)
        raise typer.Exit(code=2)

    normalizer = LyricsNormalizer(
        mode, encoding, strip_unknown=strip_unknown_headers,
        offset_policy=offset_policy.value, skip_near_empty=skip_near_empty,
    )
    changes = normalizer.plan(result, tracks, orphans)
    session = normalizer.apply(changes, path) if apply else None
    options = [f"Política de offset: {offset_policy.value}"]
    if strip_unknown_headers:
        options.append("Cabeceras desconocidas del inicio: se quitan")
    if skip_near_empty:
        options.append("Letras casi vacías: se omiten")
    print_normalize_plan(
        changes, path, mode, encoding, console=console,
        limit=(0 if diff else 20) if limit is None else limit,
        show_diff=diff, session=session, options=options,
    )
    if session is not None and any(item["status"] != backup.ITEM_APPLIED
                                   for item in session.manifest["items"]):
        raise typer.Exit(code=1)


@app.command()
def revert(
    folder: Path = typer.Argument(
        ..., help="Carpeta de respaldo: <biblioteca>/ChoconostleLRCTool_back/<fecha-hora>."),
    force: bool = typer.Option(
        False, "--force",
        help="Restaura también las letras que cambiaron después de normalizarlas.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Solo muestra qué se restauraría."),
) -> None:
    """Restaura las letras originales desde una carpeta de respaldo de normalize-lyrics."""
    _safe_streams()
    console = Console(highlight=False)
    error_console = Console(stderr=True, highlight=False)
    folder = folder.expanduser()
    try:
        results = backup.revert(folder, force=force, dry_run=dry_run)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        error_console.print(f"No se puede revertir: {exc}", style="red", markup=False)
        raise typer.Exit(code=2)
    print_revert(results, folder, console=console, dry_run=dry_run)
    if any(result.status in (backup.REVERT_CONFLICT, backup.REVERT_ERROR) for result in results):
        raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Muestra la versión del programa."""
    typer.echo(f"{APP_NAME} {APP_VERSION} ({APP_CODENAME})")


def main() -> None:
    """Inicia la aplicación."""
    app()


if __name__ == "__main__":
    main()
