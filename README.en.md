# Choconostle LRC Toolkit

[Versión en español](README.md)

> **⚠️ Before using `--apply`, make a copy of your music library.** Always run the simulation first (the same command without `--apply`) and review what would change. The tool keeps backups of what it modifies, but your own copy is the only protection against the unexpected.

Choconostle analyzes, repairs and organizes music libraries that use LRC lyrics files: it reports formats, lyrics, albums and covers, cleans up lyric headers, converts lyric encodings and hides cover images from gallery apps.

**Status: release candidate `1.0.0rc1`. Not stable yet.** See [Tested / Not tested](#tested--not-tested) before relying on it.

> **The program's interface (messages, reports, help texts) is currently in Spanish.** Only this README is in English. Command names and options are the same in both.

This is a short version. The full documentation is in the [Spanish README](README.md); each section below links to the matching part.

## Installation

Requires Python 3.9 or later (tested on 3.14 and 3.15). All dependencies are pure Python. Some automated tests also need `ffmpeg`.

### Linux / Windows

```bash
git clone https://github.com/AndrewSkarlet/Choconostle_LRCToolkit.git
cd Choconostle_LRCToolkit
python -m venv .venv
# Linux:   source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -e .
```

### Android (Termux)

```bash
pkg install python git
termux-setup-storage          # allows reading /sdcard
git clone https://github.com/AndrewSkarlet/Choconostle_LRCToolkit.git
cd Choconostle_LRCToolkit
pip install -e .
```

Run `choconostle` with no arguments for a short welcome screen, or `choconostle --help` for the list of commands.

## Commands

Every command that writes is a **simulation by default**. Nothing is modified without `--apply`.

### `scan`: report (never modifies anything)

```bash
choconostle scan ~/Music --json report.json
```

Reports the real audio format of each track, lossy or lossless, Dolby, external and embedded lyrics, lyric headers, BOM, encodings, covers, and albums with mixed formats or quality. Details: [Qué revisa](README.md#qué-revisa) and [Uso](README.md#uso).

### `normalize-lyrics`: remove or standardize lyric headers

```bash
choconostle normalize-lyrics ~/Music --strip-headers            # simulation
choconostle normalize-lyrics ~/Music --strip-headers --apply
```

Some players do not load lyrics that start with LRC headers (`[ar:]`, `[ti:]`, `[by:]`...). This command fixes `.lrc`/`.txt` files and embedded lyrics. It edits only the bytes of the lyrics and keeps the encoding and line endings by default. Every change is backed up in `ChoconostleLRCTool_back/`. If the run stops (no space, SD card removed, Ctrl+C), it can be resumed with `--resume`. Details: [Normalizar letras](README.md#normalizar-letras-fase-2), [Bibliotecas grandes](README.md#bibliotecas-grandes-tarjeta-sd).

### `convert-lyrics`: change encoding, line endings or characters

```bash
choconostle convert-lyrics ~/Music --to utf8 --eol lf            # simulation
choconostle convert-lyrics ~/Music --replace-char "’='" --apply
```

Same safety system as `normalize-lyrics` (backup, `--resume`, `revert`). Characters that do not fit the target encoding are never replaced with `?`: the file is skipped. Details: [Convertir letras](README.md#convertir-letras-convert-lyrics).

### `fix-gallery`: hide covers from gallery apps

```bash
choconostle fix-gallery /sdcard/Music --only "Artist/Album" --apply
```

Creates an empty `.nomedia` file in album folders. `--remove --apply` removes only the files it created.

> **⚠️ Warning:** apps that read Android's media index (MediaStore) also stop listing the **songs** in folders with `.nomedia`. It was tested on a real Android phone (Termux) with one music app: the covers disappeared from the gallery and the music app still listed the songs. Other music apps may react differently, so try it on one album with your music app before applying it to the whole library.

Details: [Ocultar portadas en la galería](README.md#ocultar-portadas-en-la-galería-fix-gallery).

### `revert`: undo a run

```bash
choconostle revert ~/Music --latest
```

Restores the original lyrics from a backup. Lyrics that changed after the run are reported as conflicts and left alone (unless `--force`). Details: [Respaldo y reversión](README.md#respaldo-y-reversión).

### `clean-backups`: delete old backups

```bash
choconostle clean-backups ~/Music --older-than 30            # simulation
choconostle clean-backups ~/Music --older-than 30 --apply
```

Never deletes incomplete or resumable runs. Details: [Limpieza de respaldos](README.md#limpieza-de-respaldos).

### Compact view (narrow terminals)

For Termux in portrait mode. Applies to `normalize-lyrics`, `convert-lyrics`, `revert`, `clean-backups` and `fix-gallery`.

- **When:** `--compact` forces it and `--full` turns it off (both together are an error). Otherwise `CHOCONOSTLE_COMPACT=1` keeps it on (and `=0` off). Otherwise it turns on by itself when the terminal has fewer than 70 columns. If the width cannot be read (output redirected), the full view is used.
- **Progress:** every bar (full and compact view) shows the step, files done (N/M) and elapsed time, e.g. `⠋ Paso 2/2 · Aplicando 1234/4468 · 0:12:40`. With `--apply`, `normalize-lyrics` and `convert-lyrics` show the phase ("Paso 1/2 · Planificando", "Paso 2/2 · Aplicando") so the second phase does not look like a restart. The full view also shows the current file name, cut to the terminal width; the compact view does not. It respects `--no-progress` and does not animate when the output is not a terminal.
- **Output:** instead of the list of changes, only the summary: to modify, with unknown headers, unchanged, skipped and errors. Errors and conflicts (file and reason), the commands to copy (`--resume`, `revert`, the backup path) and the SD card disconnection notice (exit code 3) are still shown in full.
- **`--export FILE`** saves the full list (files, headers, diffs and suspicious lyrics) to a text file, also in simulation mode and in both views, with a "Guardando la lista en ..." indicator while writing.
- **Save the list?** After a simulation or `--diff`, if input and output are an interactive terminal and `--export` was not used, it asks "¿Guardar la lista completa? (s/N)" and then the path. Default: `~/storage/shared/Download` in Termux if it exists, otherwise the home folder; never the current folder, the library or the repository. `--no-input` turns the question off.
- **Final block (both views):** the summary, the total time, the backup path and the next step. In simulation mode the path is where the backup *will be* saved. The total time is also shown when the command ends with an error, and with `--apply`, `--resume` and `revert` it is written to `registro.txt`.

Details: [Vista compacta](README.md#vista-compacta-terminales-estrechas).

### Sections, instrumentals, SpotiFLAC data and suspicious lyrics

- **Section labels** like `[Intro: Pitbull & Lil Jon]`, `[Chorus]`, `[Verse 1]` (English) or `[Coro]`, `[Verso 2]`, `[Estribillo]` (Spanish) are lyrics: they are never listed as unknown and never removed, not even with `--strip-unknown-headers`.
- **`[instrumental:true]`** is kept and counted separately as "Instrumentales" (also in `scan`).
- **SpotiFLAC extended data** (`[x-romaji:...]`, `[x-translation:...]`, any `[x-...:]`) is removed by `--strip-headers` and `--standardize-headers` **only** in the initial block, before the first lyric line. After that it is never touched.
- **Suspicious lyrics** (report only, nothing is modified), in `scan` (screen and JSON) and the `normalize-lyrics` simulation: lyrics with a URL or domain, the same text in many different songs (`--repeat-threshold N`, default 5, listing each song title to tell remixes and Slowed/Sped Up versions from ads), and very short lyrics that do not look like lyrics (never repeated as "nearly empty").

Details: [Secciones, instrumentales y datos extendidos](README.md#secciones-instrumentales-y-datos-extendidos-spotiflac), [Letras sospechosas](README.md#letras-sospechosas).

Other commands: `recover` (leaves each interrupted write as the original or as applied, without resuming the run), `welcome` and `version`.

## Tested / Not tested

**Tested:**
- With rc2: the full test suite passed 525/525 on Windows and on three Android phones with Termux (Moto Edge 60 Fusion, LG G8, Samsung A31). A real library on an SD card in the phone (LG G8, Termux): 6690 lyrics in 4468 files; simulation in 8 min 45 s, `--apply` in 31 min 23 s, 0 errors, 8 % battery without a charger. A second simulation found nothing left to change, and Poweramp and another app read the lyrics correctly.
- Fixed in rc2: on Android, an external change to the audio only (same size and same `st_mtime_ns`) between planning and applying was not detected. The plan now stores an audio fingerprint.
- The automated test suite on Linux and Windows. On Windows: full suite, 496 of 496 passed on commit `06a7317`; 264 tests of `test_cli`, `test_robustez` and `test_run` passed on `e4b0de8`. Disconnection, interruption and disk-full scenarios are **simulated**, in both Linux-like and Windows-like path behavior (see [Pruebas](README.md#pruebas) and `tests/COBERTURA.md`).
- With version 0.3.0, the author ran apply and `revert` cycles on real FLAC files on Windows (internal disk and SD cards via USB, including removing the card in the middle of a run) and on Android with Termux (internal storage). Files were byte-identical after `revert`.
- With the rc1 version, on Windows: an apply/`revert` cycle with a real removal of a 4 GB SD card (FAT32, USB 2.0 adapter) in the middle of the run, followed by `--resume`. A byte-by-byte comparison of 129 files (audio and tags included) found 0 differences.
- `fix-gallery` on a real Android phone (Termux) with one music app (see the warning above).

**Not tested** (from [docs/PENDIENTES.md](docs/PENDIENTES.md)):
- `convert-lyrics` in Termux, CPU use. What is new in 1.0.0rc3.dev0 has only been tested with the automated suite.
- NAS and ARM; charset-normalizer in pure Python outside Linux x86.
- A real full disk (only simulated).
- The ID3 editor with real MP3 files that have headers (only generated MP3 files).
- `tools/medir_rendimiento.py` (memory and time measurements) on Windows and on an SD card.
- How music apps other than the one tested react to `.nomedia`.

**Known and unresolved:**
- `[Errno 22] Invalid argument` appears when a real SD card is removed. It is reported as a possible disconnection ("La unidad dejó de responder ... ¿se desconectó la tarjeta SD?", exit code 3). Its behavior with invalid FAT file names, which can also cause it, has not been tested.
- `tests/test_memoria.py` is slow on Windows (45–57 s). Once it failed inside a full run on Linux while passing on its own; the cause is unknown.
- Memory grows by about 420 bytes per file in `revert` and about 1.3 KB per file in `scan`.

**Not yet (planned for rc3):** a library organizer (renaming and sorting files), a full English README and translated messages, and better performance on slow cards. Every write is synced to disk: on a 4 GB SD card (FAT32, USB 2.0) a synced write costs about 19 ms per file, against about 1 ms on the internal disk. With 42 files on that card, `revert` took 21–22 s and `--apply` 25 s.

## Reporting a bug

Open an issue at <https://github.com/AndrewSkarlet/Choconostle_LRCToolkit/issues> and include:

- the output of `choconostle version`, your operating system and Python version;
- the exact command and its full output (it is in Spanish; paste it as is);
- for runs with `--apply`, the `registro.txt` file from the backup folder (`ChoconostleLRCTool_back/<date-time>/`).

Do not attach music files you are not allowed to share. Remove personal paths if needed.

## License

MIT. See [LICENSE](LICENSE).
