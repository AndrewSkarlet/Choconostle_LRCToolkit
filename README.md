# Choconostle_LRCToolkit

Toolkit para analizar, reparar y organizar bibliotecas musicales con archivos LRC.

Versión actual: **0.2.0 (Xoconostle)**.

- **Fase 1, `scan`:** escaneo y reporte. No modifica nada.
- **Fase 2, `normalize-lyrics` y `revert`:** quita o estandariza las cabeceras de las letras, con respaldo y reversión.

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

## Normalizar letras (Fase 2)

Poweramp en Android no carga letras con cabeceras LRC (`[ti:]`, `[ar:]`, `[by:]`...). `normalize-lyrics` las corrige en **todas las copias** de la letra:

- el archivo `.lrc` o `.txt`;
- las etiquetas `LYRICS` y `UNSYNCEDLYRICS` (FLAC, Ogg, Opus);
- `USLT`, `SYLT` y `TXXX:LYRICS` (MP3, WAV, AIFF);
- `©lyr` (M4A);
- `Lyrics` (APE, WavPack).

No toca el audio ni las demás etiquetas.

```bash
# 1. Simulación (por defecto): muestra qué cambiaría, no modifica nada
choconostle normalize-lyrics ~/Música --strip-headers
choconostle normalize-lyrics ~/Música --strip-headers --diff     # con diferencias línea por línea

# 2. Aplicar
choconostle normalize-lyrics ~/Música --strip-headers --apply

# 3. Deshacer, si hace falta
choconostle revert ~/Música/ChoconostleLRCTool_back/2026-10-15_20-30-00
```

### Modos (elige uno)

| Modo | Qué hace |
|---|---|
| `--strip-headers` | Quita todas las cabeceras LRC (`[ar:]`, `[ti:]`, `[al:]`, `[by:]`, `[length:]`, `[offset:]`, `[re:]`, `[ve:]`...) y conserva todas las marcas de tiempo. |
| `--standardize-headers` | Deja solo `[ar:]`, `[ti:]`, `[al:]` y `[length:]`, en ese orden y sin duplicados. Los valores salen de las etiquetas de la canción (artista, título, álbum) y de la duración del audio. **Si falta un dato, esa cabecera no se escribe**: nunca se inventan datos. Las demás cabeceras (`[by:]`, `[re:]`...) se quitan. |

En ambos modos:
- Si hay `[offset:]`, se aplica a cada marca de tiempo antes de quitarlo, así la sincronización no cambia. Un offset positivo adelanta la letra, según el formato LRC. Las marcas que quedarían en negativo se dejan en `00:00`.
- Se conservan el formato de cada marca (`[mm:ss.xx]`, `[mm:ss.xxx]`...) y las marcas por palabra `<mm:ss.xx>`.
- Las letras **sin marcas de tiempo** no se tocan, salvo para quitar o estandarizar las cabeceras que ya tengan.
- Las letras **casi vacías** (2 líneas con texto o menos, p. ej. solo `[00:00.00]Instrumental`) se marcan en el reporte y **no se modifican**.
- Los saltos de línea se convierten a LF (`\n`).
- `SYLT` es binario (texto + tiempo): solo se quitan las entradas que sean cabeceras.

### Opciones

| Opción | Descripción |
|---|---|
| `--apply` | Aplica los cambios. Sin ella solo se simula. |
| `--encoding utf8` | (Predeterminado) Guarda los `.lrc`/`.txt` en UTF-8 sin BOM. |
| `--encoding utf8-bom` | UTF-8 con BOM. |
| `--encoding keep` | Conserva la codificación y el BOM de cada archivo. |
| `--only CARPETA_O_ÁLBUM` | Limita a una carpeta (ruta absoluta o relativa a la biblioteca) o a un álbum (nombre según las etiquetas). Se puede repetir. |
| `--diff` | Muestra las diferencias línea por línea. |
| `--limit N` | Máximo de canciones por lista en pantalla (0 = todas). |

Si un archivo no es UTF-8 y su codificación no se puede confirmar (p. ej. un `.lrc` en japonés guardado en Shift-JIS), **se conserva su codificación** para no estropear el texto, y se avisa.

### Respaldo y reversión

Antes de modificar nada, `--apply` crea:

```
<biblioteca>/ChoconostleLRCTool_back/<fecha-hora>/
├── originales/       texto original completo de cada letra modificada
├── registro.txt      qué se cambió, con las diferencias línea por línea
└── manifiesto.json   lo necesario para revertir
```

No se copian archivos de audio. El escáner ignora esta carpeta.

`choconostle revert <carpeta>` restaura todas las letras del respaldo:
- Solo restaura una letra si sigue como la dejó `normalize-lyrics`. Si la cambiaste después, la marca como **conflicto** y no la toca; `--force` la sobrescribe.
- `--dry-run` muestra qué restauraría sin cambiar nada.
- Revertir dos veces no hace nada la segunda vez.
- Matroska (`.mka`) solo se puede leer: sus letras incrustadas se reportan como omitidas.

## Estructura

```
src/choconostle/
├── cli.py          Comandos (typer)
├── config.py       Configuración: extensiones, nombres de portada, cabeceras LRC
├── scanner.py      Recorre carpetas y asocia letras y portadas a cada pista
├── audio.py        Detecta el códec real, con/sin pérdida, Dolby
├── tags.py         Lee etiquetas, letras y portadas incrustadas
├── matroska.py     Lector mínimo de .mka (mutagen no lo soporta)
├── embedded.py     Lee y escribe letras incrustadas (ID3, Vorbis, MP4, APEv2)
├── normalizer.py   Fase 2: LyricsNormalizer (cabeceras, offset, codificación)
├── backup.py       Respaldo, manifiesto y revert
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
