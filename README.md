# Choconostle_LRCToolkit

Toolkit para analizar, reparar y organizar bibliotecas musicales con archivos LRC.

Versión actual: **0.1.0 (Xoconostle)**, Fase 1: escaneo y reporte. No modifica ningún archivo de tu biblioteca.

## Qué revisa

- **Formato real de cada pista**, leído del contenido y no de la extensión: FLAC, WAV, AIFF, APE, WavPack, MP3, AAC/M4A (incluido ALAC), Opus, Ogg Vorbis y Matroska (.mka). Clasifica cada pista como **con pérdida** o **sin pérdida** e indica si el audio es **Dolby** (AC-3, E-AC-3, TrueHD, AC-4), aunque venga dentro de .m4a, .mp4, .mka o .wav. Avisa cuando la extensión no corresponde al contenido (p. ej. un FLAC renombrado a .mp3).
- **Letras**:
  - Externas: `.lrc` o `.txt` con el mismo nombre que la canción.
  - Incrustadas: MP3 `USLT`/`SYLT`, FLAC/Ogg `LYRICS`/`UNSYNCEDLYRICS`, M4A `©lyr`, APE/WavPack `Lyrics` y Matroska `LYRICS`.
  - Separa letras **sincronizadas** (con marcas de tiempo) de **sin sincronizar**, sin importar la extensión.
- **Problemas en letras**, a corregir en la Fase 2: cabeceras LRC (`[ar:]`, `[ti:]`, `[al:]`, `[length:]`, `[offset:]`...), BOM y codificaciones distintas de UTF-8. Poweramp en Android no carga letras con cabeceras.
- **Portadas**: `Cover.jpg`/`Folder.jpg` (también .jpeg, .png, .webp; sin distinguir mayúsculas) y portada incrustada.
- **Álbumes**, por carpeta o por etiqueta. Las subcarpetas `CD1`, `Disc 2`, `Disco 1`... cuentan como un solo álbum. Reporta álbumes con:
  - formatos mezclados (p. ej. FLAC con una pista M4A);
  - calidad mezclada (bits o kHz distintos);
  - sin portada.
- **Formatos sin letras incrustadas** (WAV, AIFF, AAC/AC-3 sin contenedor): se indican como información, no como error. En esos casos usa un `.lrc` externo.
- Archivos `.lrc` sin canción, audio no compatible (WMA, DSD...) y archivos que no se pudieron leer.

## Instalación

Requiere Python 3.9 o superior.

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
termux-setup-storage          # permite leer /sdcard
git clone https://github.com/AndrewSkarlet/Choconostle_LRCToolkit.git
cd Choconostle_LRCToolkit
pip install -e .
```

Todas las dependencias (mutagen, typer, rich) son Python puro, sin compilación.

## Uso

```bash
choconostle scan RUTA_DE_LA_BIBLIOTECA
```

Ejemplos:

```bash
choconostle scan ~/Música
choconostle scan "D:\Música" --json reporte.json
choconostle scan /sdcard/Music --group-by tag --limit 0
python -m choconostle scan ~/Música      # sin instalar el comando
```

| Opción | Descripción |
|---|---|
| `--group-by folder\|tag`, `-g` | Agrupa los álbumes por carpeta (predeterminado) o por etiqueta (artista del álbum + álbum). El resumen siempre muestra ambos conteos. |
| `--json ARCHIVO`, `-j` | Guarda el reporte completo en JSON, con cada pista, sus letras y sus problemas. Es la entrada prevista para la Fase 2. |
| `--limit N`, `-l` | Máximo de elementos por lista en pantalla (20 por defecto; 0 = todos). |
| `--include-hidden` | Incluye carpetas y archivos ocultos (que empiezan con `.`). |
| `--no-progress` | No muestra el indicador de progreso. |

`choconostle version` muestra la versión.

## Estructura

```
src/choconostle/
├── cli.py          Comandos (typer)
├── config.py       Configuración: extensiones, nombres de portada, cabeceras LRC
├── scanner.py      Recorre carpetas y asocia letras y portadas a cada pista
├── audio.py        Detecta el códec real, con/sin pérdida, Dolby
├── tags.py         Lee etiquetas, letras y portadas incrustadas
├── matroska.py     Lector mínimo de .mka (mutagen no lo soporta)
├── lrc.py          Análisis de letras: marcas de tiempo, cabeceras, BOM, codificación
├── albums.py       Agrupa pistas en álbumes
├── report.py       Reporte en terminal y JSON
├── utils.py        Formato de tamaños, duraciones, calidad
├── rename.py       (Fase futura)
└── models/         Track, LyricsInfo, Album
```

## Pruebas

```bash
pip install -e ".[dev]"
pytest
```

Las pruebas de FLAC, MP3, WAV y APE generan los archivos en Python puro. Las de M4A, Opus, Ogg, WavPack, AIFF, Matroska y Dolby usan `ffmpeg` y se omiten si no está instalado.

## Licencia

MIT. Ver [LICENSE](LICENSE).
