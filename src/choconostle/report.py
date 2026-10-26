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


def _more(console: Console, hidden: int) -> None:
    if hidden:
        console.print(f"  ... y {hidden} más (usa --limit 0 o --json para verlos todos)", style="dim")


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
        console.print("Pocas o ninguna línea con texto. normalize-lyrics no las modifica.", style="dim")
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

def _change_where(change, root: Path) -> str:
    """Ruta de la canción (o del archivo de letra si no tiene canción)."""
    path = change.track_path or change.path
    return _rel(path, root)


def print_normalize_plan(
    changes: list,
    root: Path,
    mode: str,
    encoding: str,
    console: Console | None = None,
    limit: int = 20,
    show_diff: bool = False,
    session=None,
) -> None:
    """Muestra el plan de normalize-lyrics (simulación) o el resultado (--apply)."""
    from choconostle.backup import ITEM_FAILED, _diff
    from choconostle.normalizer import (
        KIND_FILE, MODE_STRIP, STATUS_CHANGE, STATUS_ERROR, STATUS_NEARLY_EMPTY,
        STATUS_SKIPPED, STATUS_UNCHANGED,
    )

    console = console or Console()
    by_status: dict[str, list] = {}
    for change in changes:
        by_status.setdefault(change.status, []).append(change)
    to_change = by_status.get(STATUS_CHANGE, [])

    title = "APLICADO" if session is not None else "SIMULACIÓN (no se modificó nada)"
    console.print(f"[bold]normalize-lyrics - {title}[/bold]")
    mode_name = "quitar cabeceras" if mode == MODE_STRIP else "estandarizar cabeceras (ar, ti, al, length)"
    console.print(f"Modo: {mode_name}", markup=False)
    console.print(f"Codificación de archivos .lrc/.txt: {encoding}", markup=False)
    console.print(Text(f"Biblioteca: {root}"))

    _section(console, "Resumen")
    files = sum(1 for change in to_change if change.kind == KIND_FILE)
    songs = {change.track_path or change.path for change in to_change}
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Letras revisadas", str(len(changes)))
    table.add_row(
        "Modificadas" if session is not None else "A modificar",
        f"{len(to_change)} ({plural(files, 'archivo')}, {plural(len(to_change) - files, 'incrustada')}) "
        f"en {plural(len(songs), 'canción', 'canciones')}",
    )
    table.add_row("Sin cambios", str(len(by_status.get(STATUS_UNCHANGED, []))))
    table.add_row("Casi vacías (no se tocan)", str(len(by_status.get(STATUS_NEARLY_EMPTY, []))))
    if by_status.get(STATUS_SKIPPED):
        table.add_row("Omitidas", str(len(by_status[STATUS_SKIPPED])))
    if by_status.get(STATUS_ERROR):
        table.add_row("Errores", f"[red]{len(by_status[STATUS_ERROR])}[/red]")
    console.print(table)

    if to_change:
        _section(console, "Cambios" if session is not None else "Cambios que se aplicarían")
        groups: dict[str, list] = {}
        for change in to_change:
            groups.setdefault(_change_where(change, root), []).append(change)
        names = list(groups)
        shown, hidden = _limited(names, limit)
        for name in shown:
            console.print(Text(name, style="bold"))
            table = Table(show_header=False, box=None, padding=(0, 1, 0, 3))
            table.add_column()
            table.add_column()
            for change in groups[name]:
                table.add_row(Text(change.label), Text("; ".join(change.details)))
            console.print(table)
            if show_diff:
                for change in groups[name]:
                    console.print(Text(f"   {change.label}:", style="bold dim"))
                    for line in _diff(change.original_text, change.new_text)[2:]:
                        style = "green" if line.startswith("+") else "red" if line.startswith("-") else "dim"
                        console.print(Text("     " + line, style=style))
        _more(console, hidden)

    def listing(title: str, items: list, style: str | None = None) -> None:
        if not items:
            return
        _section(console, f"{title} ({len(items)})")
        shown, hidden = _limited(items, limit)
        for change in shown:
            label = "" if change.kind == KIND_FILE else f" [{change.label}]"
            where = _rel(change.path, root) + label
            console.print(Text(f"  {where}: {change.message}", style=style or ""))
        _more(console, hidden)

    listing("Letras casi vacías: se marcan y no se modifican", by_status.get(STATUS_NEARLY_EMPTY, []))
    listing("Omitidas", by_status.get(STATUS_SKIPPED, []), "dim")
    listing("Errores", by_status.get(STATUS_ERROR, []), "red")

    console.print()
    if session is None:
        if to_change:
            console.print(
                "Para aplicar los cambios, repite el comando con --apply. "
                f"Antes se guardará un respaldo en {root / 'ChoconostleLRCTool_back'}.",
                markup=False,
            )
        else:
            console.print("No hay nada que modificar.")
        return

    failed = [item for item in session.manifest["items"] if item["status"] == ITEM_FAILED]
    if failed:
        _section(console, f"No se pudieron aplicar ({len(failed)})")
        for item in failed:
            console.print(Text(f"  {item['path']} [{item['label']}]: {item['error']}", style="red"))
        console.print()
    console.print(Text(f"Respaldo guardado en: {session.folder}"))
    console.print(Text(f'Para deshacer: choconostle revert "{session.folder}"'))


def print_revert(results: list, folder: Path, console: Console | None = None,
                 dry_run: bool = False) -> None:
    from choconostle.backup import REVERT_ALREADY, REVERT_CONFLICT, REVERT_ERROR, REVERT_RESTORED

    console = console or Console()
    title = "SIMULACIÓN (no se modificó nada)" if dry_run else "resultado"
    console.print(f"[bold]revert - {title}[/bold]")
    console.print(Text(f"Respaldo: {folder}"))
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
