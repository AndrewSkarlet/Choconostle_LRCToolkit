"""
cli.py

Interfaz de línea de comandos.

Uso:
    choconostle scan RUTA [--group-by folder|tag] [--json reporte.json]
    choconostle normalize-lyrics RUTA --strip-headers|--standardize-headers [--apply]
    choconostle normalize-lyrics RUTA --resume CARPETA_DE_RESPALDO
    choconostle convert-lyrics RUTA [--to utf8] [--eol lf] [--replace-char DE=A] [--apply]
    choconostle revert CARPETA_DE_RESPALDO
    choconostle recover CARPETA_DE_RESPALDO
    choconostle clean-backups RUTA --older-than DÍAS [--apply]
    choconostle fix-gallery RUTA [--all-folders] [--include-root] [--remove] [--apply]
    choconostle version
    choconostle [welcome] [--no-banner]

Autor: AndrewSkarlet
Licencia: MIT
"""

from __future__ import annotations

import os
import shutil
import stat
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
    build_report, print_copyable, print_elapsed, print_report, print_revert, print_run_report, write_json,
)
from choconostle.scanner import LibraryScan, count_files, scan_directory
from choconostle.textio import EncodingOptionError, parse_target_encoding
from choconostle.utils import elapsed_line, elapsed_shown, format_size, long_path, plural, start_clock, stop_clock
from rich.table import Column
from rich.text import Text

app = typer.Typer(
    help=APP_DESCRIPTION,
    add_completion=False,
)

BANNER_WIDTH = 40
BANNER_ENV = "CHOCONOSTLE_NO_BANNER"
BANNER_COMMANDS = ["scan", "normalize-lyrics", "convert-lyrics", "revert", "recover", "clean-backups",
                   "fix-gallery", "welcome", "version"]


def banner_lines() -> list[str]:
    """Banner de bienvenida: solo ASCII y como máximo BANNER_WIDTH columnas."""
    import textwrap
    inner = BANNER_WIDTH - 4

    def wrap(text: str) -> list[str]:
        return textwrap.wrap(text, inner) or [""]
    body = wrap(f"{APP_NAME} {APP_VERSION} ({APP_CODENAME})")  # lo mismo que "choconostle version"
    body += [""] + wrap(APP_DESCRIPTION) + ["", "Comandos:"]
    body += [f"  {name}" for name in BANNER_COMMANDS]
    body += ["", *wrap("Consejo: empieza con scan; nada se modifica sin --apply."),
             *wrap("Ayuda: choconostle --help")]
    edge = "+" + "-" * (BANNER_WIDTH - 2) + "+"
    lines = [edge] + [f"| {line.ljust(inner)} |" for line in body] + [edge]
    # Cualquier carácter no ASCII (p. ej. una tilde en la descripción) se sustituye.
    return [line.encode("ascii", "replace").decode("ascii") for line in lines]


def _interactive() -> bool:
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _show_banner_or_help(ctx: typer.Context, no_banner: bool) -> None:
    import os as _os
    if not no_banner and not _os.environ.get(BANNER_ENV) and _interactive():
        typer.echo("\n".join(banner_lines()))
    else:
        typer.echo(ctx.find_root().get_help())


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    no_banner: bool = typer.Option(
        False, "--no-banner", help=f"No muestra el banner de bienvenida (también con la variable {BANNER_ENV}).",
    ),
) -> None:
    """Toolkit para analizar, reparar y organizar bibliotecas musicales con archivos LRC."""
    ctx.obj = {"no_banner": no_banner}
    if ctx.invoked_subcommand in TIMED_COMMANDS:
        start_clock()
        ctx.call_on_close(_elapsed_on_close)
    if ctx.invoked_subcommand is None:
        _show_banner_or_help(ctx, no_banner)


TIMED_COMMANDS = {"normalize-lyrics", "convert-lyrics", "revert", "clean-backups", "fix-gallery"}
"""Comandos que muestran el tiempo total al final (medido con time.perf_counter() desde el inicio)."""


def _elapsed_on_close() -> None:
    """Si el comando terminó sin llegar al resumen (error, Ctrl+C), muestra igualmente el tiempo total."""
    try:
        if not elapsed_shown():
            line = elapsed_line()
            if line:
                Console(stderr=True, highlight=False).print(line, markup=False)
    finally:
        stop_clock()


def _log_elapsed(folder: Path, label: str | None = None) -> None:
    """Añade el tiempo total al registro.txt de una carpeta de respaldo (si la unidad sigue accesible)."""
    line = elapsed_line(mark_shown=False)
    if not line:
        return
    if label:
        line = f"{line} ({label})"
    try:
        with open(long_path(Path(folder) / runs.LOG_NAME), "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


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

    normalizer = LyricsNormalizer(
        mode, encoding, strip_unknown=strip_unknown_headers,
        offset_policy=offset_policy.value, skip_near_empty=skip_near_empty,
        allow_full_rewrite=allow_full_rewrite,
    )
    _execute("normalize-lyrics", normalizer, path, apply, diff, show_limit, only or [], include_hidden,
             verify.value, console, error_console, progress)


def _execute(command, processor, path, apply, diff, limit, only, include_hidden, verify,
             console, error_console, progress) -> None:
    """
    Ejecución en dos pasadas común a normalize-lyrics y convert-lyrics:
    planificación en disco, aplicación con diario y respaldo, y reporte.
    """
    from choconostle.converter import ConversionAbort

    pending = pending_sessions(path)
    if pending:
        print_copyable(error_console, str(PendingWritesError(pending)), "yellow")
        if apply:
            raise typer.Exit(code=2)

    processor.verify = verify  # con --verify full, el plan guarda el hash de todo el audio
    execution = runs.Run.create(path, command, dict(processor.options(), verify=verify), temporary=not apply)
    keep_folder = apply
    resume_hint = f'choconostle {command} "{path}" --resume "{execution.folder}"'
    try:
        progress.start_plan(count_files(path, include_hidden))
        try:
            totals = runs.plan_library(execution, processor, path, only, include_hidden, progress)
        except runs.StopRun as stop:
            progress.stop()
            keep_folder = False  # no se aplicó nada
            print_copyable(error_console, f"SE DETUVO: {stop}", "red")
            raise typer.Exit(code=3)
        except ConversionAbort as exc:
            progress.stop()
            keep_folder = False
            print_copyable(error_console, f"Se detuvo antes de modificar nada (--on-unencodable error): {exc}", "red")
            raise typer.Exit(code=2)
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
                summary = runs.apply_run(execution, processor, path, progress, verify=verify)
            except runs.InsufficientSpace as exc:
                progress.stop()
                print_copyable(error_console, str(exc), "red")
                error_console.print("Cuando haya espacio:")
                print_copyable(error_console, resume_hint)
                raise typer.Exit(code=2)
            except KeyboardInterrupt:
                progress.stop()
                error_console.print("Interrumpido. Para continuar:", style="yellow")
                print_copyable(error_console, resume_hint)
                raise typer.Exit(code=130)
            finally:
                progress.stop()
        _report(execution, console, error_console, path, limit, diff, apply,
                summary or (runs.ApplySummary() if apply else None), _option_lines(execution.state["options"]))
        _exit_for(summary)
    finally:
        if not keep_folder:
            shutil.rmtree(execution.folder, ignore_errors=True)
        else:
            _log_elapsed(execution.folder)


def _option_lines(options: dict) -> list[str]:
    lines = [f"Política de offset: {options['offset_policy']}"] if "offset_policy" in options else []
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
        # La unidad no se puede leer: se usa la copia en memoria de lo que se
        # confirmó en el diario (incluye lo de ejecuciones anteriores si es --resume).
        confirmed = getattr(execution, "confirmed", {}) or {}
        applied_count = sum(1 for status in confirmed.values() if status == runs.APPLIED)
        failed_count = len(confirmed) - applied_count
        pending = execution.state.get("totals", {}).get("entries", 0) - len(confirmed)
        error_console.print("Resumen según lo confirmado en el diario (la unidad no se puede leer ahora):",
                            markup=False)
        error_console.print(f"  Aplicadas (archivos): {applied_count}", markup=False)
        if failed_count:
            error_console.print(f"  Con error (archivos): {failed_count}", markup=False)
        if pending > 0:
            error_console.print(f"  Sin aplicar (pendientes): {pending}", markup=False)
        error_console.print("El resto no se modificó o se restauró; el diario en la tarjeta dice qué terminó.",
                            markup=False)
        error_console.print("Cuando vuelvas a conectar la unidad, para continuar:")
        print_copyable(error_console, f'choconostle {execution.state["command"]} "{path}" --resume "{execution.folder}"')


def _exit_for(summary) -> None:
    if summary is None:
        return
    if summary.stopped:
        raise typer.Exit(code=3)
    if summary.failed:
        raise typer.Exit(code=1)


def _resume(path, folder, console, error_console, progress, show_limit, diff,
            command: str = "normalize-lyrics") -> None:
    try:
        execution = runs.Run(folder)
    except (FileNotFoundError, ValueError) as exc:
        print_copyable(error_console, f"No se puede reanudar: {exc}", "red")
        raise typer.Exit(code=2)
    options = execution.state["options"]
    if execution.state.get("command") != command:
        print_copyable(error_console, f"No se puede reanudar: la ejecución es de {execution.state.get('command')}; "
                                      f"usa choconostle {execution.state.get('command')} --resume.", "red")
        raise typer.Exit(code=2)
    normalizer = runs.processor_for(execution)
    try:
        problems = runs.resume_check(execution, path, normalizer, command, progress=progress)
    except OSError as exc:
        progress.stop()
        print_copyable(error_console, f"No se puede reanudar: la biblioteca o su respaldo no están accesibles ({exc}). "
                                      "No se modificó nada; vuelve a intentarlo cuando la unidad esté conectada.", "red")
        raise typer.Exit(code=3)
    progress.stop()
    if problems:
        error_console.print("No se puede reanudar con seguridad; no se modificó nada:", style="red")
        for problem in problems:
            print_copyable(error_console, f"  - {problem}", "red")
        raise typer.Exit(code=2)
    legacy = execution.legacy_audio_plans()
    if legacy:
        error_console.print(
            f"Aviso: el plan es de una versión anterior y no guarda la huella del audio de "
            f"{plural(legacy, 'archivo')}. Para esos archivos se usa la protección anterior: "
            "solo se comprueba que el tamaño, la fecha de modificación y las etiquetas no hayan cambiado.",
            style="yellow", markup=False)
    _intents, done = execution.outcome()
    try:
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
    finally:
        _log_elapsed(execution.folder, "reanudación")


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
        # expand=True: cada actualización ocupa el ancho completo de la terminal
        # (rellena con espacios) y el texto variable se recorta con «…». Así no
        # quedan restos de un nombre anterior más largo en las consolas que no
        # borran la línea antes de redibujarla.
        self.progress = Progress(
            SpinnerColumn(), TextColumn("{task.description}"),
            BarColumn(bar_width=None, table_column=Column(ratio=1)), MofNCompleteColumn(),
            TextColumn("{task.fields[stats]}", table_column=Column(ratio=2, no_wrap=True, overflow="ellipsis")),
            TimeElapsedColumn(), TextColumn("restante (estimado)"), TimeRemainingColumn(),
            console=self.console, transient=True, expand=True,
        )
        self.progress.start()
        self.task = self.progress.add_task(description, total=total, completed=completed, stats="")

    def start_plan(self, total: int) -> None:
        self._start("Planificando", total)

    # Interfaz genérica (revert, comprobación de --resume, clean-backups).
    def start(self, description: str, total: int | None, completed: int = 0) -> None:
        self._description = description
        self._start(description, total, completed)

    def tick(self, count: int = 1, current: str = "") -> None:
        if self.progress is not None:
            # Solo el nombre del archivo: si no cabe, se recorta por el final con «…».
            name = current.replace("\\", "/").rsplit("/", 1)[-1] if current else ""
            self.progress.update(self.task, advance=count, stats=name)

    def step(self, text: str) -> None:
        """Paso en curso dentro del archivo actual (p. ej. una verificación larga)."""
        if self.progress is not None:
            self.progress.update(self.task, stats=text)

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


class Eol(str, Enum):
    lf = "lf"
    crlf = "crlf"
    keep = "keep"


class Id3Encoding(str, Enum):
    latin1 = "latin1"
    utf16 = "utf16"
    utf8 = "utf8"


class OnUnencodable(str, Enum):
    skip = "skip"
    error = "error"


@app.command("convert-lyrics")
def convert_lyrics(
    path: Path = typer.Argument(..., help="Carpeta de la biblioteca musical."),
    to: str = typer.Option(
        "utf8", "--to",
        help="Codificación de destino de los .lrc/.txt: utf8 (sin BOM, por defecto), utf8-bom o cualquier "
             "códec de Python (cp1252, shift_jis, utf-16...). No afecta a las letras incrustadas.",
    ),
    eol: Eol = typer.Option(
        Eol.lf, "--eol",
        help="Saltos de línea de los .lrc/.txt: lf (por defecto), crlf o keep (conservar, incluso mezclados). "
             "No afecta a las letras incrustadas.",
    ),
    source_encoding: Optional[str] = typer.Option(
        None, "--source-encoding",
        help="Codificación de origen de los archivos de 8 bits cuya detección no es fiable (p. ej. cp1252). "
             "Nunca se aplica a archivos con BOM, UTF-8 válido o UTF-16.",
    ),
    prefer_encoding: Optional[str] = typer.Option(
        None, "--prefer-encoding",
        help="Desempata cuando la detección da candidatos empatados de familias distintas "
             "(p. ej. cp1252 frente a cp1250 en español). Solo se usa si está entre los empatados.",
    ),
    replace_char: Optional[List[str]] = typer.Option(
        None, "--replace-char",
        help="Sustitución DE=A (se puede repetir). Admite \\uXXXX y \\= para un '=' literal. "
             "Nunca toca las marcas de tiempo. También se aplica a las letras incrustadas.",
    ),
    replace_map: Optional[Path] = typer.Option(
        None, "--replace-map",
        help="Archivo UTF-8 con una sustitución por línea (DE=A o DE<TAB>A; # para comentarios).",
    ),
    id3_encoding: Optional[Id3Encoding] = typer.Option(
        None, "--id3-encoding",
        help="Codificación de los frames de letra ID3 (USLT, SYLT, TXXX de letra): latin1, utf16 o utf8 "
             "(utf8 solo en ID3v2.4; no se cambia la versión del tag).",
    ),
    on_unencodable: OnUnencodable = typer.Option(
        OnUnencodable.skip, "--on-unencodable",
        help="Si el destino no puede representar algún carácter: skip (omitir el archivo y listarlo, "
             "por defecto) o error (detener todo antes de modificar nada). Nunca se sustituye por '?'.",
    ),
    allow_full_rewrite: bool = typer.Option(
        False, "--allow-full-rewrite",
        help="Permite reescribir el archivo de audio completo cuando la letra no cabe en el relleno "
             "(p. ej. ID3 Latin-1 -> UTF-16) y siempre en Ogg/Opus. Por defecto se omiten.",
    ),
    only: Optional[List[str]] = typer.Option(
        None, "--only", "-o", help="Limita a una carpeta (ruta) o álbum (nombre). Se puede repetir.",
    ),
    apply: bool = typer.Option(False, "--apply", help="Aplica los cambios. Sin esta opción solo se simula."),
    diff: bool = typer.Option(False, "--diff", help="Muestra las diferencias línea por línea."),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-l",
        help="Máximo de canciones por lista en pantalla (0 = sin límite); igual que en normalize-lyrics.",
    ),
    include_hidden: bool = typer.Option(False, "--include-hidden",
                                        help="Incluye carpetas y archivos ocultos (que empiezan con '.')."),
    no_progress: bool = typer.Option(False, "--no-progress", help="No muestra el progreso."),
    resume: Optional[Path] = typer.Option(
        None, "--resume", help="Continúa una ejecución interrumpida de convert-lyrics (carpeta de respaldo).",
    ),
    verify: Verify = typer.Option(
        Verify.auto, "--verify",
        help="Verificación tras escribir en archivos de audio: auto (por defecto), full o quick.",
    ),
) -> None:
    """Convierte codificación, saltos de línea y caracteres de las letras (con simulación y respaldo)."""
    from choconostle.converter import LyricsConverter
    from choconostle.textio import ReplaceRuleError, load_replace_map, parse_replace_rule

    _safe_streams()
    console = Console(highlight=False)
    error_console = Console(stderr=True, highlight=False)
    path = path.expanduser()
    if not path.is_dir():
        print_copyable(error_console, f"No es una carpeta: {path}", "red")
        raise typer.Exit(code=2)
    progress = _RunProgress(error_console, enabled=not no_progress and error_console.is_terminal)
    if resume is not None:
        _resume(path, resume.expanduser(), console, error_console, progress, limit, diff, "convert-lyrics")
        return

    try:
        target = parse_target_encoding(to)
        if target is None:
            raise EncodingOptionError("--to keep no es válido en convert-lyrics: indica una codificación.")
        for name in (source_encoding, prefer_encoding):
            if name is not None and parse_target_encoding(name) is None:
                raise EncodingOptionError("keep no es una codificación de origen.")
        rules = [parse_replace_rule(value) for value in replace_char or []]
        if replace_map is not None:
            rules += load_replace_map(replace_map.expanduser())
    except (EncodingOptionError, ReplaceRuleError, OSError) as exc:
        print_copyable(error_console, str(exc), "red")
        raise typer.Exit(code=2)

    converter = LyricsConverter(
        to, eol.value, source_encoding, prefer_encoding, rules,
        id3_encoding.value if id3_encoding else None, on_unencodable.value, allow_full_rewrite,
    )
    _execute("convert-lyrics", converter, path, apply, diff, limit, only or [], include_hidden,
             verify.value, console, error_console, progress)


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
    no_progress: bool = typer.Option(False, "--no-progress", help="No muestra el progreso."),
) -> None:
    """Restaura las letras originales desde una carpeta de respaldo (normalize-lyrics o convert-lyrics)."""
    _safe_streams()
    console = Console(highlight=False)
    error_console = Console(stderr=True, highlight=False)
    progress = _RunProgress(error_console, enabled=not no_progress and error_console.is_terminal)
    try:
        folder = backup.resolve_backup(folder.expanduser(), latest=latest)
        if latest:
            console.print("Respaldo más reciente:")
            print_copyable(console, str(folder))
        try:
            results = backup.revert(folder, force=force, dry_run=dry_run, progress=progress)
        finally:
            progress.stop()
    except backup.RevertNoSpace as exc:
        print_copyable(error_console, str(exc), "red")
        raise typer.Exit(code=2)
    except backup.RevertStopped as stop:
        print_revert(stop.results, folder, console=console, dry_run=dry_run)
        if not dry_run:
            _log_revert_elapsed(folder)
        console.print()
        print_copyable(console, f"SE DETUVO: {stop}", "bold red")
        console.print("Lo restaurado hasta aquí está confirmado. Vuelve a ejecutar revert"
                      + (" cuando la unidad esté conectada:" if stop.kind == "device" else
                         " cuando haya espacio:" if stop.kind == "space" else ":"), markup=False)
        print_copyable(console, f'choconostle revert "{folder}"')
        raise typer.Exit(code=3)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print_copyable(error_console, f"No se puede revertir: {exc}", "red")
        raise typer.Exit(code=2)
    except OSError as exc:
        print_copyable(error_console, f"No se puede revertir: la biblioteca o el respaldo no están accesibles "
                                      f"({exc}). Vuelve a ejecutar revert cuando la unidad esté conectada.", "red")
        raise typer.Exit(code=3)
    print_revert(results, folder, console=console, dry_run=dry_run)
    if not dry_run:
        _log_revert_elapsed(folder)
    if any(result.status in (backup.REVERT_CONFLICT, backup.REVERT_ERROR) for result in results):
        raise typer.Exit(code=1)


def _log_revert_elapsed(folder: Path) -> None:
    """Tiempo total de revert: en el revert_<fecha>.txt recién escrito y en registro.txt."""
    from datetime import datetime
    line = elapsed_line(mark_shown=False)
    if not line:
        return
    try:
        logs = sorted(Path(folder).glob("revert_*.txt"))
        if logs:
            with open(long_path(logs[-1]), "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError:
        pass
    _log_elapsed(folder, f"revert del {datetime.now().isoformat(timespec='seconds')}")


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
    no_progress: bool = typer.Option(False, "--no-progress", help="No muestra el progreso."),
) -> None:
    """Borra respaldos antiguos de ChoconostleLRCTool_back (nunca los incompletos o reanudables)."""
    _safe_streams()
    console = Console(highlight=False)
    path = path.expanduser()
    stopped = None
    error_console = Console(stderr=True, highlight=False)
    progress = _RunProgress(error_console, enabled=not no_progress and error_console.is_terminal)
    try:
        try:
            remove, keep = runs.clean_backups(path, older_than, apply=apply, progress=progress)
        finally:
            progress.stop()
    except runs.CleanStopped as stop:
        remove, keep, stopped = stop.remove, stop.keep, stop
    except OSError as exc:
        print_copyable(console, f"No se pueden revisar los respaldos: la unidad no está accesible ({exc}). "
                                f"Vuelve a ejecutar clean-backups cuando esté conectada.", "red")
        raise typer.Exit(code=3)
    title = "BORRADOS" if apply else "SIMULACIÓN (no se borró nada)"
    console.print(f"[bold]clean-backups - {title}[/bold]")
    print_copyable(console, f"Respaldos de más de {older_than} días en {path / 'ChoconostleLRCTool_back'}")
    console.print()
    label = "Borrados" if apply else "Se borrarían"
    deleted = [info for info in remove if info.deleted] if apply else remove
    console.print(f"{label} ({len(deleted)}, {format_size(sum(i.size for i in deleted))}):", markup=False)
    for info in deleted:
        when = info.created.strftime("%Y-%m-%d %H:%M") if info.created else "?"
        console.print(Text(f"  {info.folder.name}  {when}  {format_size(info.size)}  ({info.state})"))
    failed = [info for info in remove if apply and not info.deleted]
    if failed:
        console.print(f"No se pudieron borrar ({len(failed)}; se reintentará en la próxima ejecución):",
                      markup=False)
        for info in failed:
            print_copyable(console, f"  {info.folder.name}: {info.error or 'no se llegó a intentar'}", "red")
    console.print(f"Se conservan ({len(keep)}):", markup=False)
    for info in keep:
        console.print(Text(f"  {info.folder.name}  {info.state}: {info.keep_reason}",
                           style="yellow" if "reanudable" in (info.keep_reason or "")
                           or "interrumpidas" in (info.keep_reason or "") else ""))
    if remove and not apply:
        console.print()
        console.print("Para borrarlos, repite el comando con --apply.", markup=False)
    if stopped is not None:
        console.print()
        print_copyable(console, f"SE DETUVO: {stopped}", "bold red")
        console.print("Vuelve a ejecutar cuando la unidad esté conectada; terminará los borrados a medias:",
                      markup=False)
        print_copyable(console, f'choconostle clean-backups "{path}" --older-than {older_than} --apply')
        raise typer.Exit(code=3)
    if failed:
        raise typer.Exit(code=1)


class _GalleryProgress:
    """Progreso de fix-gallery: carpetas encontradas y luego «N de M»."""

    def __init__(self, console: Console, enabled: bool):
        self.enabled = enabled
        self.console = console
        self.progress = None
        self.task = None

    def _open(self, *columns, description: str, total) -> None:
        self.stop()
        if not self.enabled:
            return
        self.progress = Progress(*columns, console=self.console, transient=True)
        self.progress.start()
        self.task = self.progress.add_task(description, total=total)

    def searching(self) -> None:
        self._open(SpinnerColumn(), TextColumn("{task.description}"), description="Buscando carpetas...",
                   total=None)

    def found(self, count: int) -> None:
        if self.progress is not None:
            self.progress.update(self.task, description=f"Buscando carpetas... {count}")

    def start(self, description: str, total: int) -> None:
        self._open(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(),
                   TimeElapsedColumn(), description=description, total=total)

    def advance(self, count: int) -> None:
        if self.progress is not None:
            self.progress.update(self.task, advance=count)

    def stop(self) -> None:
        if self.progress is not None:
            self.progress.stop()
            self.progress = None


def _print_list(console: Console, title: str, items: list[str], limit: int) -> None:
    console.print(f"{title} ({len(items)}):", markup=False)
    shown = items if not limit else items[:limit]
    for item in shown:
        print_copyable(console, f"  {item}")
    if len(shown) < len(items):
        console.print(f"  ... y {len(items) - len(shown)} más (usa --limit 0 para verlas todas)", markup=False)


@app.command("fix-gallery")
def fix_gallery(
    path: Path = typer.Argument(..., help="Carpeta de la biblioteca musical (o de un álbum)."),
    apply: bool = typer.Option(
        False, "--apply",
        help="Crea (o, con --remove, quita) los .nomedia. Sin esta opción solo se simula.",
    ),
    all_folders: bool = typer.Option(
        False, "--all-folders",
        help="Pone .nomedia en todas las carpetas con audio, tengan o no imágenes.",
    ),
    include_root: bool = typer.Option(
        False, "--include-root",
        help="Incluye la carpeta raíz indicada y las carpetas Music, Pictures, DCIM y Download.",
    ),
    remove: bool = typer.Option(
        False, "--remove",
        help="Quita solo los .nomedia que creó fix-gallery (nunca los que ya existían).",
    ),
    only: Optional[List[str]] = typer.Option(
        None, "--only", "-o", help="Limita a una carpeta (ruta) o álbum (nombre). Se puede repetir.",
    ),
    limit: int = typer.Option(
        20, "--limit", "-l", help="Máximo de carpetas por lista en pantalla (0 = todas).",
    ),
    include_hidden: bool = typer.Option(
        False, "--include-hidden", help="Incluye carpetas ocultas (que empiezan con '.').",
    ),
    no_progress: bool = typer.Option(False, "--no-progress", help="No muestra el progreso."),
) -> None:
    """Crea .nomedia en las carpetas de álbum para que las galerías no muestren las portadas."""
    from choconostle import gallery

    _safe_streams()
    console = Console(highlight=False)
    error_console = Console(stderr=True, highlight=False)
    path = path.expanduser()
    try:
        is_dir = stat.S_ISDIR(os.stat(long_path(path)).st_mode)
    except (FileNotFoundError, NotADirectoryError):
        is_dir = False
    except OSError as exc:
        print_copyable(error_console, f"La unidad no está accesible ({exc}). Vuelve a ejecutar fix-gallery "
                                      f"cuando esté conectada.", "red")
        raise typer.Exit(code=3)
    if not is_dir:
        print_copyable(error_console, f"No es una carpeta: {path}", "red")
        raise typer.Exit(code=2)
    if remove and (all_folders or include_root):
        error_console.print("--remove no se combina con --all-folders ni con --include-root.", style="red",
                            markup=False)
        raise typer.Exit(code=2)
    progress = _GalleryProgress(error_console, enabled=not no_progress and error_console.is_terminal)
    if remove:
        result = gallery.run_remove(path, only or [], apply=apply, include_hidden=include_hidden,
                                    progress=progress)
    else:
        result = gallery.run_create(path, only or [], apply=apply, all_folders=all_folders,
                                    include_root=include_root, include_hidden=include_hidden, progress=progress)
    if result.missing_albums:
        error_console.print(f"No se encontró una carpeta ni un álbum llamado: {', '.join(result.missing_albums)}",
                            style="red", markup=False)
        raise typer.Exit(code=2)

    action = "quitar" if remove else "crear"
    title = ("APLICADO" if apply else "SIMULACIÓN (no se modificó nada)")
    console.print(f"[bold]fix-gallery ({action} .nomedia) - {title}[/bold]")
    print_copyable(console, f"Biblioteca: {path}")
    if remove:
        print_copyable(console, f"Lista de lo creado: {gallery.record_path(path)}")
    else:
        console.print("Modo: " + ("todas las carpetas con audio (--all-folders)" if all_folders
                                  else "carpetas con imágenes"), markup=False)
    if result.root_note:
        console.print(result.root_note, style="yellow", markup=False)
    console.print()
    if remove:
        _print_list(console, "Quitados" if apply else "Se quitarían", result.removed, limit)
        if result.gone:
            _print_list(console, "Ya no estaban", result.gone, limit)
        if result.kept:
            _print_list(console, "Se conservan", [f"{rel}: {why}" for rel, why in result.kept], limit)
    else:
        _print_list(console, "Creados" if apply else "Se crearían", result.created, limit)
        if result.protected:
            _print_list(console, "Omitidas por protección", [f"{rel}: {why}" for rel, why in result.protected],
                        limit)
    if result.errors:
        console.print(f"Con error ({len(result.errors)}):", style="red", markup=False)
        for rel, message in result.errors:
            print_copyable(console, f"  {rel}: {message}", "red")
    if result.record_error:
        print_copyable(console, f"No se pudo guardar la lista de lo creado: {result.record_error}", "red")
    console.print()
    if remove:
        console.print(f"Resumen: revisadas {result.reviewed}, {'quitadas' if apply else 'se quitarían'} "
                      f"{len(result.removed)}, ya no estaban {len(result.gone)}, conservadas {len(result.kept)}, "
                      f"con error {len(result.errors)}", markup=False)
    else:
        console.print(f"Resumen: carpetas revisadas {result.reviewed}, {'creadas' if apply else 'se crearían'} "
                      f"{len(result.created)}, ya existentes {len(result.existing)}, omitidas {result.skipped} "
                      f"(sin {'audio' if all_folders else 'imágenes'} {result.not_matching}, protegidas "
                      f"{len(result.protected)}), con error {len(result.errors)}", markup=False)
    print_elapsed(console)
    if not apply and (result.removed if remove else result.created):
        console.print("Para aplicarlo, repite el comando con --apply.", markup=False)
    if result.stopped is not None:
        console.print()
        print_copyable(console, f"SE DETUVO: {result.stopped}", "bold red")
        console.print("Vuelve a ejecutar cuando la unidad esté conectada; seguirá donde quedó:", markup=False)
        args = ["choconostle", "fix-gallery", f'"{path}"']
        args += [flag for flag, on in [("--all-folders", all_folders), ("--include-root", include_root),
                                       ("--remove", remove), ("--apply", apply)] if on]
        args += [f'--only "{value}"' for value in only or []]
        print_copyable(console, " ".join(args))
        raise typer.Exit(code=3)
    if result.errors:
        raise typer.Exit(code=1)


@app.command()
def welcome(
    ctx: typer.Context,
    no_banner: bool = typer.Option(False, "--no-banner", help="No muestra el banner (muestra la ayuda)."),
) -> None:
    """Muestra el banner de bienvenida (solo en una terminal interactiva)."""
    _show_banner_or_help(ctx, no_banner or bool((ctx.obj or {}).get("no_banner")))


@app.command()
def version() -> None:
    """Muestra la versión del programa."""
    typer.echo(f"{APP_NAME} {APP_VERSION} ({APP_CODENAME})")


def main() -> None:
    """Inicia la aplicación."""
    app()


if __name__ == "__main__":
    main()
