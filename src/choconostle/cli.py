"""
cli.py

Interfaz de línea de comandos.

Uso:
    choconostle scan RUTA [--group-by folder|tag] [--json reporte.json]
    choconostle normalize-lyrics RUTA --strip-headers|--standardize-headers [--apply]
    choconostle normalize-lyrics RUTA --resume CARPETA_DE_RESPALDO
    choconostle revert CARPETA_DE_RESPALDO
    choconostle recover CARPETA_DE_RESPALDO
    choconostle clean-backups RUTA --older-than DÍAS [--apply]
    choconostle version

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import shutil
import sys
from enum import Enum
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn,
    TimeRemainingColumn,
)

from choconostle.config import APP_CODENAME, APP_DESCRIPTION, APP_NAME, APP_VERSION
from choconostle import backup
from choconostle import run as runs
from choconostle.normalizer import (
    ENCODING_KEEP, MODE_STANDARDIZE, MODE_STRIP, OFFSET_FIRST, OFFSET_LAST, OFFSET_SKIP, OFFSET_SUM,
    LyricsNormalizer, PendingWritesError, pending_sessions,
)
from choconostle.rawtags.writer import VERIFY_AUTO, VERIFY_FULL, VERIFY_QUICK
from choconostle.report import (
    build_report, print_copyable, print_report, print_revert, print_run_report, write_json,
)
from choconostle.scanner import LibraryScan, count_files, scan_directory
from choconostle.textio import EncodingOptionError, parse_target_encoding
from choconostle.utils import format_size
from rich.text import Text

app = typer.Typer(
    help=APP_DESCRIPTION,
    add_completion=False,
    no_args_is_help=True,
)


class GroupBy(str, Enum):
    folder = "folder"
    tag = "tag"


class Verify(str, Enum):
    auto = VERIFY_AUTO
    full = VERIFY_FULL
    quick = VERIFY_QUICK


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
        print_copyable(error_console, f"No es una carpeta: {path}", "red")
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
    allow_full_rewrite: bool = typer.Option(
        False, "--allow-full-rewrite",
        help="Permite reescribir el archivo de audio completo cuando la letra no cabe en el relleno "
             "de las etiquetas (y siempre en Ogg/Opus). Se hace en una copia temporal verificada; "
             "requiere espacio libre del tamaño del archivo. Por defecto esos archivos se omiten.",
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
        help="Máximo de canciones por lista en pantalla (0 = sin límite). Por defecto 20; todas con --diff; "
             "con --apply todas hasta 50 entradas y, si hay más, solo el resumen y los fallos "
             "(registro.txt siempre tiene la lista completa).",
    ),
    include_hidden: bool = typer.Option(
        False, "--include-hidden",
        help="Incluye carpetas y archivos ocultos (que empiezan con '.').",
    ),
    no_progress: bool = typer.Option(False, "--no-progress", help="No muestra el progreso."),
    resume: Optional[Path] = typer.Option(
        None, "--resume",
        help="Continúa una ejecución interrumpida (carpeta <biblioteca>/ChoconostleLRCTool_back/<fecha-hora>). "
             "Usa las opciones guardadas y solo sigue si el diario, el respaldo y los archivos son coherentes.",
    ),
    verify: Verify = typer.Option(
        Verify.auto, "--verify",
        help="Verificación tras escribir en archivos de audio: auto (por defecto: quick si el audio no se "
             "escribe, full si se reescribe el archivo), full (hash de todo el audio, antes y después) "
             "o quick (etiquetas byte a byte, tamaño y el primer y último MB del audio).",
    ),
) -> None:
    """Quita o estandariza las cabeceras de las letras (archivos y etiquetas incrustadas)."""
    _safe_streams()
    console = Console(highlight=False)
    error_console = Console(stderr=True, highlight=False)

    path = path.expanduser()
    if not path.is_dir():
        print_copyable(error_console, f"No es una carpeta: {path}", "red")
        raise typer.Exit(code=2)
    show_limit = limit  # None: el reporte decide (20; todo con --diff; resumen con --apply y más de 50)
    progress = _RunProgress(error_console, enabled=not no_progress and error_console.is_terminal)

    if resume is not None:
        _resume(path, resume.expanduser(), console, error_console, progress, show_limit, diff)
        return

    if strip_headers == standardize_headers:
        error_console.print("Elige un modo: --strip-headers o --standardize-headers.", style="red")
        raise typer.Exit(code=2)
    mode = MODE_STRIP if strip_headers else MODE_STANDARDIZE
    try:
        parse_target_encoding(encoding)
    except EncodingOptionError as exc:
        error_console.print(str(exc), style="red", markup=False)
        raise typer.Exit(code=2)

    pending = pending_sessions(path)
    if pending:
        print_copyable(error_console, str(PendingWritesError(pending)), "yellow")
        if apply:
            raise typer.Exit(code=2)

    normalizer = LyricsNormalizer(
        mode, encoding, strip_unknown=strip_unknown_headers,
        offset_policy=offset_policy.value, skip_near_empty=skip_near_empty,
        allow_full_rewrite=allow_full_rewrite,
    )
    execution = runs.Run.create(path, "normalize-lyrics", dict(normalizer.options(), verify=verify.value),
                                temporary=not apply)
    keep_folder = apply
    try:
        progress.start_plan(count_files(path, include_hidden))
        try:
            totals = runs.plan_library(execution, normalizer, path, only or [], include_hidden, progress)
        except runs.StopRun as stop:
            progress.stop()
            keep_folder = False  # no se aplicó nada
            print_copyable(error_console, f"SE DETUVO: {stop}", "red")
            raise typer.Exit(code=3)
        progress.stop()
        if execution.state.get("missing_albums"):
            names = ", ".join(execution.state["missing_albums"])
            error_console.print(f"No se encontró una carpeta ni un álbum llamado: {names}", style="red",
                                markup=False)
            keep_folder = False
            raise typer.Exit(code=2)
        summary = None
        if apply and totals.entries == 0:
            keep_folder = False  # nada que aplicar: no se crea respaldo
        elif apply:
            try:
                progress.start_apply(totals.entries)
                summary = runs.apply_run(execution, normalizer, path, progress, verify=verify.value)
            except runs.InsufficientSpace as exc:
                progress.stop()
                print_copyable(error_console, str(exc), "red")
                error_console.print("Cuando haya espacio:")
                print_copyable(error_console, f'choconostle normalize-lyrics "{path}" --resume "{execution.folder}"')
                raise typer.Exit(code=2)
            except KeyboardInterrupt:
                progress.stop()
                error_console.print("Interrumpido. Para continuar:", style="yellow")
                print_copyable(error_console, f'choconostle normalize-lyrics "{path}" --resume "{execution.folder}"')
                raise typer.Exit(code=130)
            finally:
                progress.stop()
        _report(execution, console, error_console, path, show_limit, diff, apply,
                summary or (runs.ApplySummary() if apply else None), _option_lines(execution.state["options"]))
        _exit_for(summary)
    finally:
        if not keep_folder:
            shutil.rmtree(execution.folder, ignore_errors=True)


def _option_lines(options: dict) -> list[str]:
    lines = [f"Política de offset: {options['offset_policy']}"]
    if options.get("strip_unknown_headers"):
        lines.append("Cabeceras desconocidas del inicio: se quitan")
    if options.get("skip_near_empty"):
        lines.append("Letras casi vacías: se omiten")
    if options.get("allow_full_rewrite"):
        lines.append("Reescritura completa de archivos de audio: permitida")
    verify = options.get("verify", VERIFY_AUTO)
    lines.append({VERIFY_AUTO: "Verificación tras escribir: automática (rápida en su sitio, completa al reescribir)",
                  VERIFY_FULL: "Verificación tras escribir: completa (hash de todo el audio)",
                  VERIFY_QUICK: "Verificación tras escribir: rápida (etiquetas, tamaño, primer y último MB)"}[verify])
    return lines


def _report(execution, console, error_console, path, limit, diff, applied, summary, options) -> None:
    """
    Reporte leído del plan en disco. Si la unidad ya no está (tarjeta SD
    desconectada), se muestra solo lo que se sabe en memoria.
    """
    try:
        print_run_report(execution, console=console, limit=limit, show_diff=diff, applied=applied,
                         summary=summary, options=options)
    except OSError:
        if summary is None or not summary.stopped:
            raise
        print_copyable(error_console, f"SE DETUVO: {summary.stopped}", "red")
        error_console.print(f"Confirmadas antes de detenerse: {summary.applied} aplicadas, {summary.failed} con error. "
                            "El resto no se modificó o se restauró; el diario en la tarjeta dice qué terminó.",
                            markup=False)
        error_console.print("Cuando vuelvas a conectar la unidad, para continuar:")
        print_copyable(error_console, f'choconostle normalize-lyrics "{path}" --resume "{execution.folder}"')


def _exit_for(summary) -> None:
    if summary is None:
        return
    if summary.stopped:
        raise typer.Exit(code=3)
    if summary.failed:
        raise typer.Exit(code=1)


def _resume(path, folder, console, error_console, progress, show_limit, diff) -> None:
    try:
        execution = runs.Run(folder)
    except (FileNotFoundError, ValueError) as exc:
        print_copyable(error_console, f"No se puede reanudar: {exc}", "red")
        raise typer.Exit(code=2)
    options = execution.state["options"]
    normalizer = LyricsNormalizer.from_options(options)
    try:
        problems = runs.resume_check(execution, path, normalizer)
    except OSError as exc:
        print_copyable(error_console, f"No se puede reanudar: la biblioteca o su respaldo no están accesibles ({exc}). "
                                      "No se modificó nada; vuelve a intentarlo cuando la unidad esté conectada.", "red")
        raise typer.Exit(code=3)
    if problems:
        error_console.print("No se puede reanudar con seguridad; no se modificó nada:", style="red")
        for problem in problems:
            print_copyable(error_console, f"  - {problem}", "red")
        raise typer.Exit(code=2)
    _intents, done = execution.outcome()
    try:
        progress.start_apply(execution.state["totals"]["entries"], completed=len(done))
        summary = runs.apply_run(execution, normalizer, path, progress, resume=True,
                                 verify=options.get("verify", VERIFY_AUTO))
    except runs.InsufficientSpace as exc:
        print_copyable(error_console, str(exc), "red")
        raise typer.Exit(code=2)
    finally:
        progress.stop()
    _report(execution, console, error_console, path, show_limit, diff, True, summary,
            _option_lines(options) + ["Reanudada"])
    _exit_for(summary)


class _RunProgress:
    """Progreso en la terminal: archivos, cambios, errores, tiempo y tiempo restante estimado."""

    def __init__(self, console: Console, enabled: bool):
        self.enabled = enabled
        self.console = console
        self.progress = None
        self.task = None

    def _start(self, description: str, total: int | None, completed: int = 0) -> None:
        self.stop()
        if not self.enabled:
            return
        self.progress = Progress(
            SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(),
            TextColumn("{task.fields[stats]}"), TimeElapsedColumn(),
            TextColumn("restante (estimado)"), TimeRemainingColumn(),
            console=self.console, transient=True,
        )
        self.progress.start()
        self.task = self.progress.add_task(description, total=total, completed=completed, stats="")

    def start_plan(self, total: int) -> None:
        self._start("Planificando", total)

    def start_apply(self, total: int, completed: int = 0) -> None:
        self._start("Aplicando", total, completed)

    def advance(self, totals) -> None:
        if self.progress is not None:
            stats = (f"cambios {totals.statuses.get('change', 0)}  "
                     f"errores {totals.statuses.get('error', 0)}")
            self.progress.update(self.task, completed=totals.files_seen, stats=stats)

    def applied(self, summary) -> None:
        if self.progress is not None:
            self.progress.update(self.task, advance=1,
                                 stats=f"aplicados {summary.applied}  errores {summary.failed}")

    def stop(self) -> None:
        if self.progress is not None:
            self.progress.stop()
            self.progress = None


@app.command()
def revert(
    folder: Path = typer.Argument(
        ..., help="Carpeta de respaldo (<biblioteca>/ChoconostleLRCTool_back/<fecha-hora>), "
                  "o la carpeta de la biblioteca con --latest."),
    latest: bool = typer.Option(
        False, "--latest",
        help="Si se indica la biblioteca (o su carpeta ChoconostleLRCTool_back), usa el respaldo más reciente.",
    ),
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
    try:
        folder = backup.resolve_backup(folder.expanduser(), latest=latest)
        if latest:
            console.print("Respaldo más reciente:")
            print_copyable(console, str(folder))
        results = backup.revert(folder, force=force, dry_run=dry_run)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print_copyable(error_console, f"No se puede revertir: {exc}", "red")
        raise typer.Exit(code=2)
    print_revert(results, folder, console=console, dry_run=dry_run)
    if any(result.status in (backup.REVERT_CONFLICT, backup.REVERT_ERROR) for result in results):
        raise typer.Exit(code=1)


@app.command()
def recover(
    folder: Path = typer.Argument(
        ..., help="Carpeta de respaldo: <biblioteca>/ChoconostleLRCTool_back/<fecha-hora>."),
) -> None:
    """Resuelve escrituras interrumpidas: deja cada archivo como el original o como quedó aplicado."""
    _safe_streams()
    console = Console(highlight=False)
    error_console = Console(stderr=True, highlight=False)
    try:
        results = backup.recover_session(folder.expanduser())
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print_copyable(error_console, f"No se puede recuperar: {exc}", "red")
        raise typer.Exit(code=2)
    if not results:
        console.print("No hay escrituras interrumpidas en este respaldo.")
        return
    names = {"complete": "había terminado", "untouched": "no se había modificado",
             "restored": "RESTAURADO al original", "failed": "NO SE PUDO RECUPERAR"}
    for name, status, message in results:
        console.print(f"  {name}: {names.get(status, status)} - {message}", markup=False)
    if any(status == "failed" for _n, status, _m in results):
        raise typer.Exit(code=1)


@app.command("clean-backups")
def clean_backups(
    path: Path = typer.Argument(..., help="Carpeta de la biblioteca musical."),
    older_than: int = typer.Option(
        ..., "--older-than", min=0,
        help="Antigüedad mínima en días (número entero, p. ej. 30).",
    ),
    apply: bool = typer.Option(
        False, "--apply",
        help="Borra los respaldos. Sin esta opción solo se muestra qué se borraría.",
    ),
) -> None:
    """Borra respaldos antiguos de ChoconostleLRCTool_back (nunca los incompletos o reanudables)."""
    _safe_streams()
    console = Console(highlight=False)
    path = path.expanduser()
    remove, keep = runs.clean_backups(path, older_than, apply=apply)
    title = "BORRADOS" if apply else "SIMULACIÓN (no se borró nada)"
    console.print(f"[bold]clean-backups - {title}[/bold]")
    print_copyable(console, f"Respaldos de más de {older_than} días en {path / 'ChoconostleLRCTool_back'}")
    console.print()
    label = "Borrados" if apply else "Se borrarían"
    console.print(f"{label} ({len(remove)}, {format_size(sum(i.size for i in remove))}):", markup=False)
    for info in remove:
        when = info.created.strftime("%Y-%m-%d %H:%M") if info.created else "?"
        console.print(Text(f"  {info.folder.name}  {when}  {format_size(info.size)}  ({info.state})"))
    console.print(f"Se conservan ({len(keep)}):", markup=False)
    for info in keep:
        console.print(Text(f"  {info.folder.name}  {info.state}: {info.keep_reason}",
                           style="yellow" if "reanudable" in (info.keep_reason or "")
                           or "interrumpidas" in (info.keep_reason or "") else ""))
    if remove and not apply:
        console.print()
        console.print("Para borrarlos, repite el comando con --apply.", markup=False)


@app.command()
def version() -> None:
    """Muestra la versión del programa."""
    typer.echo(f"{APP_NAME} {APP_VERSION} ({APP_CODENAME})")


def main() -> None:
    """Inicia la aplicación."""
    app()


if __name__ == "__main__":
    main()
