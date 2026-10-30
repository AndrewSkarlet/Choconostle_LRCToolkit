#!/usr/bin/env python3
"""
medir_rendimiento.py — Memoria y tiempo de Choconostle_LRCToolkit con
bibliotecas de tamaño creciente.

Las bibliotecas se arman copiando N veces la salida de generar_casos.py
(que se usa como biblioteca, sin modificarlo), más dos variantes de
tamaño hechas con sus mismas funciones: una letra de unos 100 KB y un MP3
con una portada incrustada de 5 MB.

Cada comando se ejecuta en un proceso aparte, así el pico de memoria es
solo el de ese comando. Se mide:
  - pico de memoria del proceso (RSS; en Windows, PeakWorkingSetSize);
  - pico de Python con --tracemalloc (más lento: no usar para el tiempo);
  - tiempo total y por archivo;
  - archivos escaneados, entradas planificadas, aplicadas, omitidas y con error;
  - tamaño del plan, del diario y del respaldo.

Uso:
    python tools/medir_rendimiento.py [--destino CARPETA] [--tamanos 1,10,30,60]
    python tools/medir_rendimiento.py --ruta-real CARPETA [--max-archivos 2000] [--max-mb 2000]

--destino es dónde se crean las carpetas de medición (por ejemplo, en la
SD); por defecto, una carpeta temporal. Se borran al terminar cada tamaño.

--ruta-real copia primero hasta --max-archivos archivos y --max-mb MB de
esa carpeta a --destino y mide sobre la copia (normalize-lyrics --diff,
--apply y revert). La carpeta original solo se lee; al terminar se
comprueba que el tamaño y la fecha de cada archivo copiado no cambiaron.

Requisitos: ffmpeg en el PATH (para generar_casos.py) y choconostle
instalado (pip install -e .).
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
BACKUP_DIR = "ChoconostleLRCTool_back"
COVER_SIZE = 5 * 1024 * 1024
BIG_LYRICS_LINES = 2500  # unos 100 KB


def load_generator():
    spec = importlib.util.spec_from_file_location("generar_casos", TOOLS / "generar_casos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Bibliotecas
# ---------------------------------------------------------------------------
def build_base(target: Path) -> None:
    """Casos de generar_casos.py más las dos variantes de tamaño."""
    gen = load_generator()
    gen.build(target)
    folder = target / "99_variantes"
    lines = [(f"{i // 6000:02d}:{i // 100 % 60:02d}.{i % 100:02d}",
              f"Línea {i} de una letra larga con acentos, ñandú y pingüino")
             for i in range(0, BIG_LYRICS_LINES * 37, 37)]
    gen.song(folder, "01 letra de 100 KB", gen.synced(lines, gen.HDR_STD))
    # APIC: codificación, MIME, tipo (3 = portada), descripción vacía, datos.
    cover = b"\xff\xd8\xff\xe0" + os.urandom(COVER_SIZE - 4)
    apic = gen.Frame("APIC", b"\x00image/jpeg\x00\x03\x00" + cover)
    std = gen.synced(gen.ES, gen.HDR_STD)
    gen.make_mp3(folder / "02 portada de 5 MB.mp3", gen.basic_id3("02") + [apic, gen.USLT(std)])


def build_library(base: Path, target: Path, copies: int) -> int:
    for index in range(1, copies + 1):
        shutil.copytree(base, target / f"copia_{index:03d}")
    return count_files(target)


def count_files(root: Path) -> int:
    return sum(len(files) for _dirpath, _dirs, files in os.walk(root))


def tree_size(root: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.stat(os.path.join(dirpath, name)).st_size
    return total


def copy_real(source: Path, target: Path, max_files: int, max_bytes: int) -> dict[str, tuple[int, int]]:
    """
    Copia hasta max_files archivos y max_bytes bytes de source (solo lectura).
    Retorna {ruta original: (tamaño, mtime_ns)} para comprobar después que
    no cambió nada.
    """
    copied: dict[str, tuple[int, int]] = {}
    total = 0
    for dirpath, dirnames, files in os.walk(source):
        dirnames[:] = sorted(d for d in dirnames if d != BACKUP_DIR)
        for name in sorted(files):
            if len(copied) >= max_files:
                return copied
            path = Path(dirpath) / name
            info = os.stat(path)
            if total + info.st_size > max_bytes:
                continue
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            copied[str(path)] = (info.st_size, info.st_mtime_ns)
            total += info.st_size
    return copied


# ---------------------------------------------------------------------------
# Proceso de medición
# ---------------------------------------------------------------------------
def peak_rss() -> int:
    """Pico de memoria del proceso actual, en bytes (solo biblioteca estándar)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        return counters.PeakWorkingSetSize
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def worker(spec: dict) -> None:
    """Ejecuta un comando de la CLI en este proceso y escribe la medición en JSON."""
    if spec["trace"]:
        import tracemalloc
        tracemalloc.start()
    from choconostle.cli import app
    code = 0
    with open(spec["output"], "w", encoding="utf-8") as output, \
            contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        start = time.perf_counter()
        try:
            result = app(spec["args"], standalone_mode=False)
            code = result if isinstance(result, int) else 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:  # noqa: BLE001 - se anota y se sigue con la medición
            print(f"EXCEPCIÓN: {exc!r}")
            code = -1
        elapsed = time.perf_counter() - start
    data = {"seconds": elapsed, "rss": peak_rss(), "code": code}
    if spec["trace"]:
        data["python_peak"] = tracemalloc.get_traced_memory()[1]
    Path(spec["result"]).write_text(json.dumps(data), encoding="utf-8")


def measure(args: list[str], work: Path, name: str, trace: bool) -> dict:
    spec = {"args": args, "trace": trace, "output": str(work / f"{name}.txt"),
            "result": str(work / f"{name}.json")}
    env = dict(os.environ, COLUMNS="160", PYTHONIOENCODING="utf-8")
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--_worker", json.dumps(spec)],
                   check=True, env=env)
    return json.loads(Path(spec["result"]).read_text(encoding="utf-8"))


def latest_run(library: Path) -> Path | None:
    backups = library / BACKUP_DIR
    if not backups.is_dir():
        return None
    runs = sorted(p for p in backups.iterdir() if (p / "estado.json").is_file())
    return runs[-1] if runs else None


def run_counts(folder: Path | None) -> dict:
    if folder is None:
        return {}
    from choconostle.run import Run
    run = Run(folder)
    totals = run.state.get("totals", {})
    _intents, done = run.outcome()
    statuses = totals.get("statuses", {})
    return {"scanned": totals.get("files_seen"), "entries": totals.get("entries"),
            "applied": sum(1 for e in done.values() if e["status"] == "applied"),
            "failed": sum(1 for e in done.values() if e["status"] != "applied"),
            "skipped": statuses.get("skipped", 0), "errors": statuses.get("error", 0),
            "plan_bytes": os.path.getsize(folder / "plan.jsonl"),
            "diary_bytes": os.path.getsize(folder / "diario.jsonl") if (folder / "diario.jsonl").exists() else 0,
            "backup_bytes": tree_size(folder)}


def run_suite(library: Path, work: Path, files: int, label: str, trace: bool, full: bool) -> list[dict]:
    """Comandos medidos sobre una biblioteca. full=False: solo normalize --diff, --apply y revert."""
    lib = str(library)
    steps = []
    if full:
        steps.append(("scan", ["scan", lib, "--no-progress"]))
    steps += [("normalize --diff", ["normalize-lyrics", lib, "--strip-headers", "--diff", "--no-progress"]),
              ("normalize --apply", ["normalize-lyrics", lib, "--strip-headers", "--apply", "--no-progress"]),
              ("revert", None)]
    if full:
        steps += [("convert --diff", ["convert-lyrics", lib, "--diff", "--no-progress"]),
                  ("convert --apply", ["convert-lyrics", lib, "--apply", "--no-progress"]),
                  ("clean-backups", ["clean-backups", lib, "--older-than", "0", "--apply"])]
    rows = []
    applied_run = None
    for index, (name, args) in enumerate(steps):
        if name == "revert":
            if applied_run is None:
                continue
            args = ["revert", str(applied_run)]
        print(f"  [{label}] {name}...", flush=True)
        data = measure(args, work, f"{label}_{index:02d}", trace)
        row = {"size": label, "files": files, "command": name, **data}
        if name.endswith("--apply"):
            applied_run = latest_run(library)
            row.update(run_counts(applied_run))
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------
def mb(value) -> str:
    return "—" if value is None else f"{value / 1048576:.1f}"


def table(rows: list[dict]) -> list[str]:
    out = ["| Tamaño | Archivos | Comando | Tiempo (s) | ms/archivo | Pico RSS (MB) | Pico Python (MB) "
           "| Código | Escaneados | Entradas | Aplicadas | Omitidas | Errores | Plan (MB) | Respaldo (MB) |",
           "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        out.append(
            f"| {r['size']} | {r['files']} | {r['command']} | {r['seconds']:.1f} | "
            f"{1000 * r['seconds'] / max(r['files'], 1):.2f} | {mb(r['rss'])} | {mb(r.get('python_peak'))} | "
            f"{r['code']} | {r.get('scanned', '')} | {r.get('entries', '')} | {r.get('applied', '')} | "
            f"{r.get('skipped', '')} | {(r.get('errors', 0) or 0) + (r.get('failed', 0) or 0) if 'entries' in r else ''} | "
            f"{mb(r['plan_bytes']) if 'plan_bytes' in r else ''} | "
            f"{mb(r['backup_bytes']) if 'backup_bytes' in r else ''} |")
    return out


def growth(rows: list[dict]) -> list[str]:
    """Pendiente de la memoria entre el tamaño menor y el mayor, por comando."""
    out = ["| Comando | Pico RSS menor → mayor (MB) | Crecimiento (bytes por archivo) |", "|---|---|---:|"]
    for command in dict.fromkeys(r["command"] for r in rows):
        points = sorted((r["files"], r["rss"]) for r in rows if r["command"] == command)
        if len(points) < 2:
            continue
        (f0, m0), (f1, m1) = points[0], points[-1]
        slope = (m1 - m0) / (f1 - f0) if f1 != f0 else 0
        out.append(f"| {command} | {mb(m0)} → {mb(m1)} | {slope:.0f} |")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--destino", type=Path, help="Carpeta donde crear las bibliotecas de medición.")
    parser.add_argument("--tamanos", default="1,10,30,60", help="Copias de la biblioteca de casos (N).")
    parser.add_argument("--tracemalloc", action="store_true", help="Mide también el pico de Python (más lento).")
    parser.add_argument("--ruta-real", type=Path, help="Mide sobre una copia de esta carpeta (no la modifica).")
    parser.add_argument("--max-archivos", type=int, default=2000)
    parser.add_argument("--max-mb", type=int, default=2000)
    parser.add_argument("--salida", type=Path, help="Archivo Markdown con los resultados.")
    parser.add_argument("--_worker", help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options._worker:
        worker(json.loads(options._worker))
        return

    if options.ruta_real and options.destino:
        # Antes de crear nada: la carpeta original solo se lee.
        source, target = options.ruta_real.resolve(), options.destino.resolve()
        if target == source or source in target.parents or target in source.parents:
            sys.exit("--destino no puede estar dentro de --ruta-real ni contenerla.")
    destination = Path(options.destino or tempfile.mkdtemp(prefix="choconostle_medicion_")).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    work = destination / "salidas"
    work.mkdir(exist_ok=True)
    rows: list[dict] = []

    if options.ruta_real:
        source = options.ruta_real.resolve()
        if destination == source or source in destination.parents or destination in source.parents:
            sys.exit("--destino no puede estar dentro de --ruta-real ni contenerla.")
        copy = destination / "copia_real"
        if copy.exists():
            sys.exit(f"{copy} ya existe; bórrala o elige otro destino.")
        print(f"Copiando {source} → {copy} (máx. {options.max_archivos} archivos, {options.max_mb} MB)...")
        copied = copy_real(source, copy, options.max_archivos, options.max_mb * 1048576)
        files = count_files(copy)
        rows += run_suite(copy, work, files, "real", options.tracemalloc, full=False)
        changed = [path for path, (size, mtime) in copied.items()
                   if (lambda st: (st.st_size, st.st_mtime_ns))(os.stat(path)) != (size, mtime)]
        shutil.rmtree(copy)
        note = (f"Original sin cambios: {len(copied)} archivos comprobados (tamaño y fecha)." if not changed
                else f"ATENCIÓN: {len(changed)} archivos del original cambiaron durante la medición.")
    else:
        if not shutil.which("ffmpeg"):
            sys.exit("Se necesita ffmpeg en el PATH.")
        base = destination / "base"
        if base.exists():
            sys.exit(f"{base} ya existe; bórrala o elige otro destino.")
        print("Generando la biblioteca de casos...", flush=True)
        build_base(base)
        for size in [int(value) for value in options.tamanos.split(",")]:
            library = destination / f"medicion_x{size}"
            files = build_library(base, library, size)
            print(f"×{size}: {files} archivos", flush=True)
            rows += run_suite(library, work, files, f"×{size}", options.tracemalloc, full=True)
            shutil.rmtree(library)
        shutil.rmtree(base)
        note = ""

    lines = ["## Resultados", "", f"Python {sys.version.split()[0]}, {sys.platform}.", ""]
    lines += table(rows) + ["", "## Crecimiento de la memoria", ""] + growth(rows)
    if note:
        lines += ["", note]
    report = "\n".join(lines) + "\n"
    print()
    print(report)
    (options.salida or destination / "resultados.md").write_text(report, encoding="utf-8")
    (work / "resultados.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"Salidas de cada comando en {work}")


if __name__ == "__main__":
    main()
