# Choconostle LRC Toolkit

[Versión en español](README.md)

> **⚠️ Before using `--apply`, make a copy of your music library.** Always run the simulation first (the same command without `--apply`) and review what would change. The tool keeps backups of what it modifies, but your own copy is the only protection against the unexpected.

Choconostle analyzes, repairs and organizes music libraries that use LRC lyrics files: it reports formats, lyrics, albums and covers, cleans up lyric headers, converts lyric encodings and hides cover images from gallery apps.

**Status: release candidate `1.0.0rc1`. Not stable yet.** See [Tested / Not tested](#tested--not-tested) before relying on it.

> **The program's interface (messages, reports, help texts) is currently in Spanish.** Only this README is in English. Command names and options are the same in both.

This is a short version. The full documentation is in the [Spanish README](README.md); each section below links to the matching part.

## Installation

Requires Python 3.9 or later. All dependencies are pure Python. Some automated tests also need `ffmpeg`.

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

> **⚠️ Warning:** apps that read Android's media index (MediaStore) also stop listing the **songs** in folders with `.nomedia`. Try it on one album with your music app before applying it to the whole library. This has not been tested on a real Android device yet.

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

Other commands: `recover` (leaves each interrupted write as the original or as applied, without resuming the run), `welcome` and `version`.

## Tested / Not tested

**Tested:**
- The automated test suite: on Linux for 1.0.0rc1, and on Windows for version 0.3.0 (the rc1 run on Windows is pending). Disconnection, interruption and disk-full scenarios are **simulated**, in both Linux-like and Windows-like path behavior (see [Pruebas](README.md#pruebas) and `tests/COBERTURA.md`).
- With version 0.3.0, the author ran apply and `revert` cycles on real FLAC files on Windows (internal disk and SD cards via USB, including removing the card in the middle of a run) and on Android with Termux (internal storage). Files were byte-identical after `revert`. The rc1 changes have not been re-run on those setups yet.

**Not tested** (from [docs/PENDIENTES.md](docs/PENDIENTES.md)):
- SD card from the phone, large libraries on the phone, `convert-lyrics` in Termux, CPU and battery use.
- NAS and ARM; charset-normalizer in pure Python outside Linux x86.
- A real full disk (only simulated).
- The ID3 editor with real MP3 files that have headers (only generated MP3 files).
- Performance measurements on Windows and on an SD card. `revert` speed after the rc1 change has not been re-measured on an SD card.
- `fix-gallery` on a real Android device, and how each music app reacts to `.nomedia`.
- The rc1 progress-line fix in Windows consoles.
- `[Errno 22] Invalid argument` with invalid FAT file names.
- Audio and tags after `--resume` following a real disconnection.

**Known and unresolved:**
- `[Errno 22] Invalid argument`, seen when a real SD card was removed, is not treated as a disconnection: only that file fails (exit code 1).
- `tests/test_memoria.py` is slow on Windows (45–57 s). Once it failed inside a full run on Linux while passing on its own; the cause is unknown.
- Memory grows by about 420 bytes per file in `revert` and about 1.3 KB per file in `scan`.

**Not in 1.0.0rc1:** a library organizer (renaming and sorting files), a full English README and translated messages, and better performance on slow cards (every write is synced to disk).

## Reporting a bug

Open an issue at <https://github.com/AndrewSkarlet/Choconostle_LRCToolkit/issues> and include:

- the output of `choconostle version`, your operating system and Python version;
- the exact command and its full output (it is in Spanish; paste it as is);
- for runs with `--apply`, the `registro.txt` file from the backup folder (`ChoconostleLRCTool_back/<date-time>/`).

Do not attach music files you are not allowed to share. Remove personal paths if needed.

## License

MIT. See [LICENSE](LICENSE).
