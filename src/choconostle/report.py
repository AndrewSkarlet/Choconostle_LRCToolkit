"""
report.py

Genera el reporte de la biblioteca a partir de un escaneo.

Responsabilidades:
- Calcular estadísticas (formatos, letras, álbumes, portadas).
- Mostrar el reporte en la terminal.
- Exportar el reporte completo a JSON (entrada para la Fase 2).

Autor: Andrew
Licencia: MIT
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from choconostle.albums import GROUP_BY_FOLDER, GROUP_BY_TAG, group_albums
from choconostle.config import APP_NAME, APP_VERSION
from choconostle.models.album import Album
from choconostle.models.lyrics import SOURCE_EXTERNAL, LyricsInfo
from choconostle.models.track import LYRICS_NONE, LYRICS_SYNCED, LYRICS_UNSYNCED, Track
from choconostle.scanner import LibraryScan
from choconostle.utils import format_duration, format_quality, format_size, percent, plural

ENCODING_NAMES = {
    "utf-8": "UTF-8",
    "ascii": "ASCII (compatible con UTF-8)",
    "utf-16": "UTF-16",
    "utf-16-le": "UTF-16 LE",
    "utf-16-be": "UTF-16 BE",
    "utf-32-le": "UTF-32 LE",
    "utf-32-be": "UTF-32 BE",
    "cp1252": "Windows-1252 (probable)",
    "latin-1": "Latin-1",
}

# --------------------------------------------------------------------------
# Construcción del reporte (datos)
# --------------------------------------------------------------------------

def _rel(path: Path | str | None, root: Path) -> str | None:
    if path is None:
        return None
    path = Path(path)
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def lyrics_kind(lyrics: LyricsInfo) -> str:
    """"lrc", "txt" o "embedded"."""
    if lyrics.source == SOURCE_EXTERNAL:
        return Path(lyrics.location).suffix.lower().lstrip(".") or "lrc"
    return "embedded"


def lyrics_issues(lyrics: LyricsInfo) -> list[str]:
    issues = []
    if lyrics.headers:
        issues.append("cabeceras: " + ", ".join(f"[{name}:]" for name in lyrics.headers))
    if lyrics.has_bom:
        issues.append("BOM")
    if not lyrics.is_utf8:
        issues.append("codificación " + ENCODING_NAMES.get(lyrics.encoding, lyrics.encoding))
    return issues


def _format_counter(counter: Counter, label=lambda key: str(key)) -> str:
    return ", ".join(f"{label(key)} x{count}" for key, count in counter.most_common())


def _quality_label(key: tuple) -> str:
    bits, rate = key
    return format_quality(bits, rate)


def _album_dict(album: Album, root: Path) -> dict:
    return {
        "name": album.name,
        "folders": [_rel(folder, root) for folder in album.folders],
        "tracks": len(album.tracks),
        "formats": dict(album.formats),
        "qualities": {_quality_label(key): count for key, count in album.qualities.items()},
        "folder_covers": [_rel(cover, root) for cover in album.folder_covers],
        "tracks_with_embedded_cover": album.embedded_cover_count,
        "mixed_formats": album.has_mixed_formats,
        "mixed_quality": album.has_mixed_quality,
        "missing_cover": album.missing_cover,
    }


def build_report(scan: LibraryScan, group_by: str = GROUP_BY_FOLDER) -> dict:
    """Construye el reporte completo como un diccionario serializable a JSON."""
    root = scan.root
    tracks = [track for track in scan.tracks if not track.error]
    failed = [track for track in scan.tracks if track.error]

    albums_by_folder = group_albums(scan, GROUP_BY_FOLDER)
    albums_by_tag = group_albums(scan, GROUP_BY_TAG)
    albums = albums_by_tag if group_by == GROUP_BY_TAG else albums_by_folder

    # Formatos.
    formats: dict[str, dict] = {}
    for track in tracks:
        entry = formats.setdefault(track.format_label, {
            "format": track.format_label,
            "codec": track.codec,
            "container": track.container,
            "lossless": track.lossless,
            "dolby": track.dolby,
            "tag_support": track.tag_support,
            "embedded_lyrics_supported": track.embedded_lyrics_supported,
            "tracks": 0,
        })
        entry["tracks"] += 1

    # Letras por canción.
    status = Counter(track.lyrics_status for track in tracks)

    # Letras por tipo de fuente (lrc / txt / incrustada).
    found: dict[str, Counter] = {"lrc": Counter(), "txt": Counter(), "embedded": Counter()}
    to_fix: list[dict] = []
    nearly_empty: list[dict] = []
    header_counts: Counter = Counter()
    issue_counts = Counter()

    def register(lyrics: LyricsInfo, track: Track | None) -> None:
        kind = lyrics_kind(lyrics)
        state = "empty" if lyrics.empty else ("synced" if lyrics.synced else "unsynced")
        found.setdefault(kind, Counter())[state] += 1
        header_counts.update(lyrics.headers)
        if lyrics.headers:
            issue_counts["headers"] += 1
        if lyrics.has_bom:
            issue_counts["bom"] += 1
        if not lyrics.is_utf8:
            issue_counts["not_utf8"] += 1
        if lyrics.nearly_empty and not lyrics.error:
            nearly_empty.append({
                "track": _rel(track.filepath, root) if track else None,
                "location": (_rel(lyrics.location, root) if lyrics.source == SOURCE_EXTERNAL
                             else lyrics.location),
                "source": lyrics.source,
                "content_lines": lyrics.content_lines,
            })
        if lyrics.needs_fix:
            location = (_rel(lyrics.location, root) if lyrics.source == SOURCE_EXTERNAL
                        else lyrics.location)
            to_fix.append({
                "track": _rel(track.filepath, root) if track else None,
                "source": lyrics.source,
                "kind": kind,
                "location": location,
                "synced": lyrics.synced,
                "headers": list(lyrics.headers),
                "has_bom": lyrics.has_bom,
                "encoding": lyrics.encoding,
                "is_utf8": lyrics.is_utf8,
                "issues": lyrics_issues(lyrics),
            })

    for track in tracks:
        for lyrics in track.lyrics:
            register(lyrics, track)
    for lyrics in scan.orphan_lyrics:
        register(lyrics, None)

    no_embedded_support = [track for track in tracks if not track.embedded_lyrics_supported]
    no_embedded_by_format = Counter(track.format_label for track in no_embedded_support)

    lossless = sum(1 for track in tracks if track.lossless is True)
    lossy = sum(1 for track in tracks if track.lossless is False)

    return {
        "app": {"name": APP_NAME, "version": APP_VERSION},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "group_by": group_by,
        "summary": {
            "tracks": len(tracks),
            "unreadable": len(failed),
            "total_size": sum(track.size for track in tracks),
            "total_duration": sum(track.duration or 0 for track in tracks),
            "albums_by_folder": len(albums_by_folder),
            "albums_by_tag": len(albums_by_tag),
            "lossless": lossless,
            "lossy": lossy,
            "unknown_quality": len(tracks) - lossless - lossy,
            "dolby": sum(1 for track in tracks if track.dolby),
            "lyrics_synced": status[LYRICS_SYNCED],
            "lyrics_unsynced": status[LYRICS_UNSYNCED],
            "lyrics_none": status[LYRICS_NONE],
            "tracks_with_cover": sum(1 for track in tracks if track.has_cover),
            "tracks_with_embedded_cover": sum(1 for track in tracks if track.has_embedded_cover),
            "albums_mixed_formats": sum(1 for album in albums if album.has_mixed_formats),
            "albums_mixed_quality": sum(1 for album in albums if album.has_mixed_quality),
            "albums_missing_cover": sum(1 for album in albums if album.missing_cover),
            "orphan_lrc": len(scan.orphan_lyrics),
            "unmatched_txt": len(scan.unmatched_txt),
            "extension_mismatch": sum(1 for track in tracks if track.extension_mismatch),
            "unsupported_audio": len(scan.unsupported_audio),
            "other_files": scan.other_files,
        },
        "formats": sorted(formats.values(), key=lambda entry: -entry["tracks"]),
        "lyrics_found": {kind: dict(counter) for kind, counter in found.items()},
        "lyrics_issues": {
            "with_headers": issue_counts["headers"],
            "with_bom": issue_counts["bom"],
            "not_utf8": issue_counts["not_utf8"],
            "header_counts": dict(header_counts.most_common()),
        },
        "lyrics_to_fix": to_fix,
        "lyrics_nearly_empty": nearly_empty,
        "no_embedded_lyrics_support": {
            "tracks": len(no_embedded_support),
            "by_format": dict(no_embedded_by_format),
            "without_external_lyrics": sum(1 for track in no_embedded_support if not track.has_lyrics),
            "files": [_rel(track.filepath, root) for track in no_embedded_support],
        },
        "albums": [_album_dict(album, root) for album in albums],
        "extension_mismatch": [
            {"path": _rel(track.filepath, root), "detected": track.format_label}
            for track in tracks if track.extension_mismatch
        ],
        "orphan_lrc": [_rel(lyrics.location, root) for lyrics in scan.orphan_lyrics],
        "unmatched_txt": [_rel(path, root) for path in scan.unmatched_txt],
        "unsupported_audio": [_rel(path, root) for path in scan.unsupported_audio],
        "errors": [
            {"path": _rel(track.filepath, root), "error": track.error} for track in failed
        ] + [{"path": None, "error": message} for message in scan.walk_errors],
        "tracks": [track.to_dict(root) for track in scan.tracks],
    }


def write_json(report: dict, path: Path) -> None:
    """Guarda el reporte en JSON (UTF-8, sin BOM)."""
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# Presentación en terminal
# --------------------------------------------------------------------------

def _limited(items: list, limit: int) -> tuple[list, int]:
    if limit <= 0 or len(items) <= limit:
        return items, 0
    return items[:limit], len(items) - limit


def _more(console: Console, hidden: int, total: int | None = None, what: str = "elementos") -> None:
    if not hidden:
        return
    if total is None:
        console.print(f"  ... y {hidden} más (usa --limit 0 o --json para verlos todos)", style="dim")
    else:
        console.print(f"  ... y {hidden} más: se muestran {total - hidden} de {total} {what}. "
                      "Usa --limit 0 para ver la lista completa.", style="yellow")


def print_copyable(console: Console, text: str, style: str | None = None) -> None:
    """
    Imprime una línea que el usuario puede copiar (rutas, comandos) sin que
    Rich la parta al ancho de la terminal. Si es más larga que la ventana,
    la terminal la muestra en varias filas, pero se copia como una sola línea.
    """
    console.print(Text(text, style=style or ""), soft_wrap=True)


def _section(console: Console, title: str) -> None:
    console.print()
    console.rule(f"[bold]{title}[/bold]", align="left")


def print_report(report: dict, console: Console | None = None, limit: int = 20) -> None:
    """Muestra el reporte en la terminal."""
    console = console or Console()
    summary = report["summary"]
    total = summary["tracks"]

    console.print(
        f"[bold]{report['app']['name']} {report['app']['version']}[/bold] - Reporte de biblioteca"
    )
    console.print(f"Carpeta: {report['root']}")

    # Resumen ----------------------------------------------------------
    _section(console, "Resumen")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Canciones", str(total))
    if summary["unreadable"]:
        table.add_row("No se pudieron leer", f"[red]{summary['unreadable']}[/red]")
    table.add_row("Tamaño total", format_size(summary["total_size"]))
    table.add_row("Duración total", format_duration(summary["total_duration"]))
    table.add_row("Álbumes (por carpeta)", str(summary["albums_by_folder"]))
    table.add_row("Álbumes (por etiqueta)", str(summary["albums_by_tag"]))
    table.add_row("Sin pérdida", f"{summary['lossless']} ({percent(summary['lossless'], total)})")
    table.add_row("Con pérdida", f"{summary['lossy']} ({percent(summary['lossy'], total)})")
    if summary["unknown_quality"]:
        table.add_row("Pérdida desconocida", str(summary["unknown_quality"]))
    if summary["dolby"]:
        table.add_row("Audio Dolby", str(summary["dolby"]))
    table.add_row("Con portada", f"{summary['tracks_with_cover']} ({percent(summary['tracks_with_cover'], total)})")
    console.print(table)

    # Formatos ---------------------------------------------------------
    if report["formats"]:
        _section(console, "Formatos (códec real)")
        # Solo tres columnas para que quepa en la terminal de un teléfono (Termux).
        table = Table(box=None, padding=(0, 2), header_style="bold")
        table.add_column("Formato")
        table.add_column("Tipo")
        table.add_column("Pistas", justify="right")
        for entry in report["formats"]:
            kind = {True: "Sin pérdida", False: "Con pérdida"}.get(entry["lossless"], "Desconocido")
            if entry["dolby"]:
                kind += ", Dolby"
            table.add_row(Text(entry["format"]), kind, str(entry["tracks"]))
        console.print(table)

    # Letras -----------------------------------------------------------
    _section(console, "Letras por canción")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Sincronizada (con marcas de tiempo)",
                  f"{summary['lyrics_synced']} ({percent(summary['lyrics_synced'], total)})")
    table.add_row("Solo sin sincronizar",
                  f"{summary['lyrics_unsynced']} ({percent(summary['lyrics_unsynced'], total)})")
    table.add_row("Sin letra", f"{summary['lyrics_none']} ({percent(summary['lyrics_none'], total)})")
    console.print(table)

    found = report["lyrics_found"]
    if any(found.values()):
        console.print()
        table = Table(box=None, padding=(0, 2), header_style="bold")
        table.add_column("Letras encontradas")
        table.add_column("Sincronizadas", justify="right")
        table.add_column("Sin sincronizar", justify="right")
        table.add_column("Vacías", justify="right")
        names = {"lrc": "Archivos .lrc", "txt": "Archivos .txt", "embedded": "Incrustadas"}
        for kind, counts in found.items():
            if not counts:
                continue
            table.add_row(
                names.get(kind, kind),
                str(counts.get("synced", 0)),
                str(counts.get("unsynced", 0)),
                str(counts.get("empty", 0)),
            )
        console.print(table)

    # Letras a corregir ------------------------------------------------
    issues = report["lyrics_issues"]
    to_fix = report["lyrics_to_fix"]
    if to_fix:
        _section(console, f"Letras a corregir en la Fase 2 ({len(to_fix)})")
        console.print(
            f"Con cabeceras: {issues['with_headers']}   Con BOM: {issues['with_bom']}   "
            f"No UTF-8: {issues['not_utf8']}"
        )
        if issues["header_counts"]:
            console.print(
                "Cabeceras más comunes: "
                + ", ".join(f"[{name}:] x{count}" for name, count in issues["header_counts"].items()),
                markup=False,
            )
        console.print(
            "Poweramp (Android) no carga letras con cabeceras; la Fase 2 las corregirá.",
            style="dim",
        )
        shown, hidden = _limited(to_fix, limit)
        table = Table(box=None, padding=(0, 2), header_style="bold")
        table.add_column("Letra")
        table.add_column("Problemas")
        for item in shown:
            if item["source"] == SOURCE_EXTERNAL:
                name = item["location"]
            else:
                name = f"{item['track']} [{item['location']}]"
            # Text() evita que "[ar:]" o "[2019] Álbum" se interpreten como markup.
            table.add_row(Text(name), Text("; ".join(item["issues"])))
        console.print(table)
        _more(console, hidden)

    nearly = report["lyrics_nearly_empty"]
    if nearly:
        _section(console, f"Letras casi vacías ({len(nearly)})")
        console.print("Pocas o ninguna línea con texto. normalize-lyrics las procesa con un aviso "
                      "(--skip-near-empty las omite); si quedarían vacías, no las escribe.", style="dim")
        shown, hidden = _limited(nearly, limit)
        for item in shown:
            name = item["location"] if item["source"] == SOURCE_EXTERNAL else f"{item['track']} [{item['location']}]"
            console.print(Text(f"  {name}: {plural(item['content_lines'], 'línea')}"))
        _more(console, hidden)

    # Álbumes ----------------------------------------------------------
    albums = report["albums"]
    group_label = "por etiqueta" if report["group_by"] == GROUP_BY_TAG else "por carpeta"

    def album_section(title: str, flag: str, detail, note: str | None = None) -> None:
        selected = [album for album in albums if album[flag]]
        if not selected:
            return
        _section(console, f"{title} ({len(selected)}, {group_label})")
        if note:
            console.print(note, style="dim")
        shown, hidden = _limited(selected, limit)
        for album in shown:
            console.print(f"  {album['name']}", markup=False, highlight=False)
            console.print(f"      {detail(album)}", style="dim", markup=False, highlight=False)
        _more(console, hidden)

    album_section(
        "Álbumes con formatos mezclados", "mixed_formats",
        lambda album: _format_counter(Counter(album["formats"])),
    )
    album_section(
        "Álbumes con calidad mezclada", "mixed_quality",
        lambda album: _format_counter(Counter(album["qualities"])),
    )
    album_section(
        "Álbumes sin portada", "missing_cover",
        lambda album: plural(album["tracks"], "pista"),
        note="Sin Cover.jpg/Folder.jpg ni portada incrustada en ninguna pista.",
    )

    # Formatos sin letra incrustada -----------------------------------
    no_support = report["no_embedded_lyrics_support"]
    if no_support["tracks"]:
        _section(console, "Formatos sin letras incrustadas (informativo, no es error)")
        tag_support = {entry["format"]: entry["tag_support"] for entry in report["formats"]}
        tag_names = {"limited": "etiquetas limitadas", "none": "sin etiquetas"}
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column()
        table.add_column(justify="right")
        table.add_column(style="dim")
        for name, count in Counter(no_support["by_format"]).most_common():
            table.add_row(Text(name), plural(count, "pista"), tag_names.get(tag_support.get(name), ""))
        console.print(table)
        console.print(
            "Estos formatos no admiten letras incrustadas: usa un .lrc externo. "
            f"Sin letra externa: {plural(no_support['without_external_lyrics'], 'pista')}.",
            style="dim",
        )

    # Otros ------------------------------------------------------------
    if report["extension_mismatch"]:
        _section(console, f"Extensión distinta al contenido real ({len(report['extension_mismatch'])})")
        shown, hidden = _limited(report["extension_mismatch"], limit)
        for item in shown:
            console.print(f"  {item['path']}  ->  {item['detected']}", markup=False, highlight=False)
        _more(console, hidden)

    if report["orphan_lrc"]:
        _section(console, f"Archivos .lrc sin canción ({len(report['orphan_lrc'])})")
        shown, hidden = _limited(report["orphan_lrc"], limit)
        for path in shown:
            console.print(f"  {path}", markup=False, highlight=False)
        _more(console, hidden)
    if report["unmatched_txt"]:
        console.print(
            f"\n{len(report['unmatched_txt'])} archivos .txt sin canción con el mismo nombre "
            "(pueden no ser letras; se listan en el JSON).",
            style="dim",
        )

    if report["unsupported_audio"]:
        _section(console, f"Audio no compatible con esta versión ({len(report['unsupported_audio'])})")
        shown, hidden = _limited(report["unsupported_audio"], limit)
        for path in shown:
            console.print(f"  {path}", markup=False, highlight=False)
        _more(console, hidden)

    if report["errors"]:
        _section(console, f"Errores ({len(report['errors'])})")
        shown, hidden = _limited(report["errors"], limit)
        for item in shown:
            prefix = f"{item['path']}: " if item["path"] else ""
            console.print(f"  {prefix}{item['error']}", style="red", markup=False, highlight=False)
        _more(console, hidden)

    console.print()


# --------------------------------------------------------------------------
# normalize-lyrics y revert
# --------------------------------------------------------------------------

APPLY_LIST_MAX = 50


def convert_option_lines(options: dict) -> list[str]:
    """Opciones de convert-lyrics para el encabezado del reporte."""
    from choconostle.textio import describe_rule, encoding_label, parse_target_encoding
    target = parse_target_encoding(options["to"])
    eol = {"lf": "LF", "crlf": "CRLF", "keep": "se conservan"}[options["eol"]]
    from choconostle.converter import WIDE_UNICODE_WARNING, wide_unicode
    lines = [f"Archivos .lrc/.txt: {target.label}; saltos de línea: {eol}",
             "Codificación de origen: " + (f"{encoding_label(options['source_encoding'])} (--source-encoding, "
                                           "para archivos de 8 bits)" if options["source_encoding"]
                                           else "detectada (solo se convierte si es fiable)")]
    if options.get("prefer_encoding"):
        lines.append(f"Desempate: {encoding_label(options['prefer_encoding'])} (--prefer-encoding)")
    rules = options.get("replacements") or []
    if rules:
        lines.append("Sustituciones: " + ", ".join(describe_rule(tuple(rule)) for rule in rules))
    if options.get("id3_encoding"):
        lines.append(f"Frames de letra ID3: {options['id3_encoding']} (--id3-encoding)")
    if not rules and not options.get("id3_encoding"):
        lines.append("Letras incrustadas: no se tocan (solo cambian con --replace-char o --id3-encoding)")
    lines.append(f"Caracteres que no caben en el destino: {'omitir el archivo' if options['on_unencodable'] == 'skip' else 'detener todo'}")
    if wide_unicode(target.codec):
        lines.append(f"AVISO: {WIDE_UNICODE_WARNING}")
    return lines


def print_run_report(
    run,
    console: Console | None = None,
    limit: int | None = None,
    show_diff: bool = False,
    applied: bool = False,
    summary=None,
    options: list[str] | None = None,
) -> None:
    """
    Reporte de normalize-lyrics o convert-lyrics leído desde el plan y el
    diario en disco (simulación o resultado de --apply). Cada sección
    recorre el plan sin cargarlo entero en memoria.
    """
    from choconostle.normalizer import MODE_STRIP, skip_reason_label

    console = console or Console()
    totals = run.state["totals"]
    # Sin --limit: todo con --diff; con --apply, todo hasta APPLY_LIST_MAX entradas y
    # si hay más, solo el resumen (la lista completa queda en registro.txt).
    summary_only = False
    if limit is None:
        if show_diff:
            limit = 0
        elif applied:
            summary_only = totals["entries"] > APPLY_LIST_MAX
            limit = 20 if summary_only else 0
        else:
            limit = 20
    statuses = totals["statuses"]
    root = run.library_root()
    _intents, done = run.outcome() if applied else ({}, {})
    nothing = totals["entries"] == 0
    options_state = run.state["options"]

    if applied and nothing:
        title = "APLICADO: no había nada que aplicar"
    elif applied:
        title = "APLICADO" if run.phase == "completed" else "APLICADO PARCIALMENTE (se detuvo)"
    else:
        title = "SIMULACIÓN (no se modificó nada)"
    command = run.state.get("command", "normalize-lyrics")
    console.print(f"[bold]{command} - {title}[/bold]")
    if command == "convert-lyrics":
        for line in convert_option_lines(options_state):
            console.print(line, markup=False)
    else:
        mode = options_state["mode"]
        console.print(f"Modo: {'quitar cabeceras' if mode == MODE_STRIP else 'estandarizar cabeceras (ar, ti, al, length)'}",
                      markup=False)
        console.print(f"Codificación de archivos .lrc/.txt: {options_state['encoding']}", markup=False)
    for option in options or []:
        console.print(option, markup=False)
    print_copyable(console, f"Biblioteca: {root}")

    _section(console, "Resumen")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Letras revisadas", str(totals["lyrics"]))
    changes = statuses.get("change", 0)
    table.add_row("A modificar" if not applied else "Planeadas",
                  f"{changes} ({plural(totals['files_changed'], 'archivo')}, "
                  f"{plural(totals['embedded_changed'], 'incrustada')}) en "
                  f"{plural(totals['songs_changed'], 'canción', 'canciones')}")
    if applied and summary is not None:
        applied_count = failed_count = 0
        for event in done.values():
            if event["status"] == "applied":
                applied_count += 1
            else:
                failed_count += 1
        table.add_row("Aplicadas (archivos)", str(applied_count))
        if failed_count:
            table.add_row("Con error (archivos)", f"[red]{failed_count}[/red]")
        pending = totals["entries"] - len(done)
        if pending > 0:
            table.add_row("Sin aplicar (pendientes)", f"[yellow]{pending}[/yellow]")
    table.add_row("Sin cambios", str(statuses.get("unchanged", 0)))
    if statuses.get("decision"):
        table.add_row("Requieren decisión (no se tocan)", f"[yellow]{statuses['decision']}[/yellow]")
    if totals["unknown"]:
        table.add_row("Con cabeceras desconocidas (se conservan)", str(totals["unknown"]))
    if command != "convert-lyrics":
        table.add_row("Casi vacías (aviso)", str(totals["nearly_empty"]))
    rewrites = totals.get("full_rewrites") or {}
    if rewrites:
        detail = ", ".join(f"{ext.upper()}: {count}" for ext, count in sorted(rewrites.items()))
        allowed = options_state.get("allow_full_rewrite")
        table.add_row("Necesitarían reescritura completa",
                      f"[yellow]{sum(rewrites.values())}[/yellow] ({detail})"
                      + ("" if allowed else " - se omiten sin --allow-full-rewrite"))
    if statuses.get("skipped"):
        table.add_row("Omitidas", str(statuses["skipped"]))
    if statuses.get("error"):
        table.add_row("Errores", f"[red]{statuses['error']}[/red]")
    console.print(table)

    def lyric_items(record):
        if record["type"] == "file":
            yield record, record["path"]
        else:
            for slot in record["slots"]:
                yield slot, f"{record['path']} [{slot['label']}]"

    # Cambios, agrupados por canción.
    if changes and summary_only:
        _section(console, "Cambios")
        console.print(f"{plural(totals['entries'], 'entrada')} en "
                      f"{plural(totals['songs_changed'], 'canción', 'canciones')}: con más de {APPLY_LIST_MAX} "
                      "solo se listan aquí las que fallaron o quedaron sin aplicar. La lista completa está en:",
                      markup=False)
        print_copyable(console, str(run.folder / "registro.txt"))
        console.print("Usa --limit 0 para verla aquí.", markup=False)
    if changes:
        if not summary_only:
            _section(console, "Cambios" if applied else "Cambios que se aplicarían")
        shown_songs = total_songs = 0
        current = None
        for record in run.plan_records():
            if record["status"] != "change":
                continue
            if summary_only and done.get(record["id"], {}).get("status") == "applied":
                continue
            song = record.get("track") or record["path"]
            if song != current:
                current = song
                total_songs += 1
                if limit and shown_songs >= limit:
                    continue
                shown_songs += 1
                console.print(Text(song, style="bold"))
            elif limit and shown_songs >= limit and total_songs > limit:
                continue
            result = done.get(record["id"])
            table = Table(show_header=False, box=None, padding=(0, 1, 0, 3))
            table.add_column()
            table.add_column()
            entries = [record] if record["type"] == "file" else \
                [slot for slot in record["slots"] if slot["status"] == "change"]
            for entry in entries:
                table.add_row(Text(entry["label"]), Text("; ".join(entry["details"])))
                if command == "convert-lyrics" and entry.get("source_encoding"):
                    table.add_row(Text(""), Text(f"origen: {entry['source_encoding']}", style="dim"))
                for warning in entry["warnings"]:
                    table.add_row(Text(""), Text(f"aviso: {warning}", style="yellow"))
            if applied:
                if result is None:
                    table.add_row(Text(""), Text("sin aplicar (la ejecución se detuvo antes)", style="yellow"))
                elif result["status"] != "applied":
                    table.add_row(Text(""), Text(f"FALLÓ: {result.get('error')}", style="red"))
            console.print(table)
            if show_diff:
                for entry in entries:
                    heading = f"   {entry['label']}:"
                    if entry.get("source_encoding"):
                        heading += f" ({entry['source_encoding']})"
                    console.print(Text(heading, style="bold dim"))
                    if entry.get("approximate"):
                        console.print(Text("     vista aproximada: la codificación no se pudo confirmar",
                                           style="yellow"))
                    for line in entry.get("diff", []):
                        style = "green" if line.startswith("+") else "red" if line.startswith("-") else "dim"
                        console.print(Text("     " + line, style=style))
        if not summary_only:
            _more(console, total_songs - shown_songs, total_songs, "canciones")

    def listing(title: str, select, style: str | None = None, text=lambda item: item["message"]) -> None:
        count = sum(1 for record in run.plan_records() for item, _where in lyric_items(record) if select(item))
        if not count:
            return
        _section(console, f"{title} ({count})")
        shown = 0
        for record in run.plan_records():
            for item, where in lyric_items(record):
                if not select(item):
                    continue
                if limit and shown >= limit:
                    break
                shown += 1
                console.print(Text(f"  {where}: {text(item)}", style=style or ""))
        _more(console, count - shown, count)

    listing("Desconocidos / requieren decisión: offsets (no se tocaron)",
            lambda item: item["status"] == "decision", "yellow")
    listing("Desconocidos / requieren decisión: cabeceras desconocidas que se conservan "
            "(--strip-unknown-headers para quitarlas)", lambda item: bool(item["unknown"]),
            text=lambda item: " ".join(f"[{name}:]" for name in item["unknown"]))
    listing("Avisos en letras sin cambios",
            lambda item: item["warnings"] and item["status"] == "unchanged", "dim",
            text=lambda item: " ".join(item["warnings"]))
    if totals["skip_reasons"]:
        _section(console, "Archivos de audio omitidos por motivo")
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(justify="right")
        table.add_column()
        for reason, count in sorted(totals["skip_reasons"].items(), key=lambda entry: (-entry[1], entry[0])):
            table.add_row(str(count), Text(skip_reason_label(reason)))
        console.print(table)
    listing("Omitidas", lambda item: item["status"] == "skipped", "dim")
    listing("Errores", lambda item: item["status"] == "error", "red")

    console.print()
    if not applied:
        if changes:
            console.print("Para aplicar los cambios, repite el comando con --apply. Antes se guardará "
                          "un respaldo en:", markup=False)
            print_copyable(console, str(root / "ChoconostleLRCTool_back"))
        else:
            console.print("No hay nada que modificar.")
        return
    if nothing:
        console.print("No había nada que modificar: no se creó ningún respaldo.")
        return
    if summary is not None and summary.stopped:
        console.print(Text(f"SE DETUVO: {summary.stopped}", style="bold red"))
        console.print(Text("Los archivos marcados como aplicados están confirmados en el diario; "
                           "el resto no se modificó o se restauró."))
        console.print("Para continuar:")
        print_copyable(console, f'choconostle {command} "{root}" --resume "{run.folder}"')
    console.print("Respaldo guardado en:")
    print_copyable(console, str(run.folder))
    console.print("Para deshacer:")
    print_copyable(console, f'choconostle revert "{run.folder}"')


def skipped_by_reason(changes: list) -> list[tuple[str, set]]:
    """[(motivo, {archivos})] de las letras incrustadas omitidas, de mayor a menor."""
    from choconostle.normalizer import STATUS_SKIPPED, skip_reason_label
    groups: dict[str, set] = {}
    for change in changes:
        if change.status == STATUS_SKIPPED and change.skip_reason:
            groups.setdefault(skip_reason_label(change.skip_reason), set()).add(change.path)
    return sorted(groups.items(), key=lambda entry: (-len(entry[1]), entry[0]))


def print_revert(results: list, folder: Path, console: Console | None = None,
                 dry_run: bool = False) -> None:
    from choconostle.backup import REVERT_ALREADY, REVERT_CONFLICT, REVERT_ERROR, REVERT_RESTORED

    console = console or Console()
    title = "SIMULACIÓN (no se modificó nada)" if dry_run else "resultado"
    console.print(f"[bold]revert - {title}[/bold]")
    print_copyable(console, f"Respaldo: {folder}")
    counts = Counter(result.status for result in results)
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Se restaurarían" if dry_run else "Restauradas", str(counts[REVERT_RESTORED]))
    table.add_row("Ya estaban como el original", str(counts[REVERT_ALREADY]))
    if counts[REVERT_CONFLICT]:
        table.add_row("Conflictos (no se tocaron)", f"[yellow]{counts[REVERT_CONFLICT]}[/yellow]")
    if counts[REVERT_ERROR]:
        table.add_row("Errores", f"[red]{counts[REVERT_ERROR]}[/red]")
    console.print(table)
    for result in results:
        if result.status in (REVERT_CONFLICT, REVERT_ERROR):
            item = result.item
            where = item["path"] if item["kind"] == "file" else f"{item['path']} [{item['label']}]"
            style = "yellow" if result.status == REVERT_CONFLICT else "red"
            console.print(Text(f"  {where}: {result.message}", style=style))
