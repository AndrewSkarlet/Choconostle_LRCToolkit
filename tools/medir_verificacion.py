#!/usr/bin/env python3
"""
medir_verificacion.py — Costo de verificar las escrituras en archivos de
audio grandes (--verify full frente a --verify quick).

Crea una biblioteca sintética con las funciones de generar_casos.py: MP3 a
320 kbps con tag ID3v2.4 (USLT con cabeceras y una portada de 500 KB) y un
.lrc al lado. Luego, para cada modo de verificación:

1. vacía la caché del sistema para esos archivos (posix_fadvise), como si
   se leyeran por primera vez de la tarjeta SD;
2. planifica y aplica normalize-lyrics --strip-headers;
3. mide el tiempo y los bytes leídos (de llamadas al sistema y del disco
   real, /proc/self/io);
4. revierte, para que el siguiente modo parta de la misma biblioteca.

Solo funciona en Linux (usa /proc y posix_fadvise). Requiere ffmpeg.

Uso:
    python tools/medir_verificacion.py CARPETA_DESTINO [--archivos 120] [--minutos 10]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from choconostle import backup  # noqa: E402
from choconostle import run as runs  # noqa: E402
from choconostle.normalizer import MODE_STRIP, LyricsNormalizer  # noqa: E402


def load_generator():
    spec = importlib.util.spec_from_file_location("generar_casos", HERE / "generar_casos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(root: Path, files: int, minutes: int) -> int:
    gen = load_generator()
    gen.DUR = minutes * 60
    template = root / "plantilla.mp3"
    gen.make_other(template, ["-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "0",
                              "-write_id3v1", "0"])
    cover = gen.Frame("APIC", b"\x00image/jpeg\x00\x03\x00" + os.urandom(500_000))
    lyrics = gen.synced(gen.ES, gen.HDR_STD)
    audio = template.read_bytes()
    template.unlink()
    total = 0
    for number in range(files):
        album = root / "lib" / f"Album {number // 12 + 1:02d}"
        album.mkdir(parents=True, exist_ok=True)
        tag = gen.id3_tag(gen.basic_id3(f"Pista {number + 1}") + [gen.USLT(lyrics), cover], 4)
        path = album / f"{number % 12 + 1:02d} Pista.mp3"
        path.write_bytes(tag + audio)
        (album / f"{number % 12 + 1:02d} Pista.lrc").write_text(lyrics, encoding="utf-8")
        total += path.stat().st_size
    return total


def drop_cache(root: Path) -> None:
    os.sync()
    for path in root.rglob("*"):
        if path.is_file():
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.posix_fadvise(descriptor, 0, 0, os.POSIX_FADV_DONTNEED)
            finally:
                os.close(descriptor)


def io_counters() -> dict:
    values = {}
    for line in Path("/proc/self/io").read_text().splitlines():
        key, value = line.split(":")
        values[key] = int(value)
    return values


def measure(lib: Path, verify: str) -> dict:
    normalizer = LyricsNormalizer(MODE_STRIP)
    drop_cache(lib)
    start_io, start = io_counters(), time.perf_counter()
    execution = runs.Run.create(lib, "normalize-lyrics", dict(normalizer.options(), verify=verify))
    totals = runs.plan_library(execution, normalizer, lib)
    plan_time = time.perf_counter() - start
    plan_io = io_counters()

    drop_cache(lib)
    apply_io, start = io_counters(), time.perf_counter()
    summary = runs.apply_run(execution, normalizer, lib, verify=verify)
    apply_time = time.perf_counter() - start
    end_io = io_counters()
    assert summary.failed == 0 and summary.stopped is None, summary

    results = backup.revert(execution.folder)
    assert {r.status for r in results} == {backup.REVERT_RESTORED}
    shutil.rmtree(execution.folder)
    return {
        "verify": verify, "entries": totals.entries,
        "plan_s": round(plan_time, 2),
        "plan_read_disk_mb": round((plan_io["read_bytes"] - start_io["read_bytes"]) / 1e6, 1),
        "apply_s": round(apply_time, 2),
        "apply_read_calls_mb": round((end_io["rchar"] - apply_io["rchar"]) / 1e6, 1),
        "apply_read_disk_mb": round((end_io["read_bytes"] - apply_io["read_bytes"]) / 1e6, 1),
        "apply_write_disk_mb": round((end_io["write_bytes"] - apply_io["write_bytes"]) / 1e6, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("destino", type=Path)
    parser.add_argument("--archivos", type=int, default=120)
    parser.add_argument("--minutos", type=int, default=10)
    args = parser.parse_args()
    if not shutil.which("ffmpeg"):
        sys.exit("Se necesita ffmpeg en el PATH.")
    if args.destino.exists():
        sys.exit(f"{args.destino} ya existe; bórrala o elige otro destino.")
    size = build(args.destino, args.archivos, args.minutos)
    lib = args.destino / "lib"
    print(f"Biblioteca: {args.archivos} MP3 + {args.archivos} .lrc, {size / 1e9:.2f} GB de audio")
    rows = [measure(lib, verify) for verify in ("full", "quick")]
    for row in rows:
        row["audio_mb"] = round(size / 1e6, 1)
        audio_files = row["entries"] // 2
        row["apply_s_per_mp3"] = round(row["apply_s"] / audio_files, 3) if audio_files else None
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
