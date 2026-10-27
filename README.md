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
| `--strip-headers` | Quita las cabeceras LRC conocidas (lista abajo) y conserva todas las marcas de tiempo. |
| `--standardize-headers` | Deja solo `[ar:]`, `[ti:]`, `[al:]` y `[length:]`, en ese orden y sin duplicados. Los valores salen de las etiquetas de la canción (artista, título, álbum) y de la duración del audio. **Si falta un dato, esa cabecera no se escribe**: nunca se inventan datos. Las demás cabeceras conocidas (`[by:]`, `[re:]`...) se quitan. |

**Solo cambia lo que se pide.** Las líneas que no son cabeceras se conservan byte por byte: codificación, BOM, saltos de línea (incluso mezclados CRLF/LF/CR), espacios y caracteres invisibles. Si no hay nada que quitar, el archivo no se reescribe. Las líneas se separan solo por CRLF, CR y LF (U+2028 y similares son parte del texto).

#### Cabeceras conocidas

`[ar:]` `[ti:]` `[al:]` `[au:]` `[lr:]` `[by:]` `[length:]` `[offset:]` `[re:]` `[ve:]` `[tool:]` `[la:]` `[lang:]` `[language:]` `[id:]` `[key:]` `[hash:]` `[sign:]` `[total:]` `[encoding:]` `[kana:]` `[#:]`

- Se reconocen sin distinguir mayúsculas, con sangría y con espacios antes de `:`, en cualquier posición del archivo.
- **`[ ti : valor ]`, con espacios dentro del corchete, no se reconoce como cabecera** y se conserva.
- Pueden ir precedidas de U+200B, U+FEFF, U+200E, U+200F o U+2060: esos caracteres se quitan junto con la cabecera. En el resto de la letra no se tocan.
- Se quitan también las líneas vacías que quedan al inicio justo después de las cabeceras retiradas.
- `[Coro: Artista]`, `[Verso 1]` y otras etiquetas entre corchetes dentro de la letra son texto.

#### Cabeceras desconocidas

Las líneas con forma `[palabra:valor]` del **bloque inicial** que no están en la lista (p. ej. `[xtrack:7]`) **se conservan** y se listan en la sección «Desconocidos / requieren decisión». El bloque inicial son las líneas anteriores a la primera línea de letra (con o sin marca de tiempo); puede incluir líneas vacías.

Con `--strip-unknown-headers` se quitan, pero **solo las del bloque inicial**. Una línea `[Coro: Artista]` a mitad de la letra nunca se toca. Todo lo que se quita aparece en `--diff` y en `registro.txt`. Ojo: si una letra *empieza* con `[Coro: Artista]`, esa línea sí forma parte del bloque inicial.

#### `[offset:]`

- Si hay **un único** `[offset:]` válido (`+500`, `-300`, `250`), se aplica a las marcas de línea `[mm:ss.xx]` y por palabra `<mm:ss.xx>` antes de quitarlo. Un offset positivo adelanta la letra. Las marcas que quedarían en negativo se dejan en `00:00` (con aviso). Es el único caso en que se modifican líneas de la letra.
- Si el offset **no se puede aplicar con seguridad**, el archivo **no se toca** (ni cabeceras ni marcas) y se lista en «Desconocidos / requieren decisión»:
  - **dos o más** `[offset:]`: se resuelve con `--offset-policy first|last|sum` (por defecto `skip`). `sum` suma todos los valores; es la política recomendada si decides resolverlo.
  - `[offset:]` **inválido** (p. ej. `[offset:medio segundo]`): nunca se aplica, con ninguna política. Corrígelo a mano.
  - marcas de tiempo inválidas (`[00:61.00]`) o marcas `[mm:ss]` dentro del texto (estilo QQ) en un archivo con offset.

#### Letras casi vacías y vacías

- Las letras **casi vacías** (2 líneas con texto o menos, p. ej. solo `[00:00.00]Instrumental`) **se procesan con un aviso**. `--skip-near-empty` las omite.
- Si al quitar las cabeceras **no quedaría letra** (archivo con solo cabeceras), no se escribe y se avisa.

#### Letras incrustadas

Mismas reglas de cabeceras y caracteres invisibles. Se conservan los saltos de línea internos. Si el texto empieza con U+FEFF, solo se quita cuando lo que sigue es una cabecera conocida. `SYLT` es binario (texto + tiempo): solo se quitan las entradas que sean cabeceras; un `SYLT` con `[offset:]` requiere decisión.

### Opciones

| Opción | Descripción |
|---|---|
| `--apply` | Aplica los cambios. Sin ella solo se simula. |
| `--encoding keep` | (Predeterminado) Conserva la codificación, el BOM y los bytes de cada archivo. |
| `--encoding utf8` / `utf8-bom` | Convierte los `.lrc`/`.txt` a UTF-8 sin o con BOM. |
| `--encoding CÓDEC` | Cualquier códec de texto de Python (`cp1252`, `shift_jis`, `gbk`...). |
| `--strip-unknown-headers` | Quita también las cabeceras desconocidas del inicio. |
| `--offset-policy skip\|first\|last\|sum` | Qué hacer con dos o más `[offset:]` (por defecto `skip`). |
| `--skip-near-empty` | Omite las letras casi vacías. |
| `--only CARPETA_O_ÁLBUM` | Limita a una carpeta (ruta absoluta o relativa a la biblioteca) o a un álbum (nombre según las etiquetas). Se puede repetir. |
| `--diff` | Muestra las diferencias línea por línea. Los caracteres invisibles se ven como `⟨U+200B⟩`. Con `--diff` se muestra la lista completa. |
| `--limit N` | Máximo de canciones por lista en pantalla (0 = todas). Por defecto 20, o todas con `--diff`. Si se corta, se indica cuántas faltan. |

Con `--encoding` distinto de `keep`, un archivo se convierte **solo si todos sus caracteres caben** en la codificación de destino; si no, se omite y se lista con los caracteres que faltan (nunca se sustituyen por `?`). Tampoco se convierte un archivo cuya codificación de origen no se pueda confirmar. `--encoding` no cambia los saltos de línea. Para eso y para indicar la codificación de origen está `convert-lyrics`.

#### Codificación de origen

- BOM, UTF-8 válido y UTF-16 sin BOM se reconocen con certeza.
- Para los demás archivos (8 bits) se usa `charset-normalizer` como ayuda; la decisión la toma el programa:
  - Dos candidatos están **empatados** si su «caos» (la medida de charset-normalizer) difiere en menos de 0.05.
  - La detección es **fiable** si, entre los candidatos empatados que decodifican y recodifican los bytes sin cambios, todos dan el mismo texto o todos son de la misma **familia compatible**. Las familias son: Shift-JIS/cp932, EUC-KR/cp949, GBK/GB18030/GB2312, Big5/cp950, EUC-JP y Windows-1252/Latin-1. En una familia se usa la más amplia. Por eso un EUC-KR puede aparecer como «EUC-KR (cp949)».
  - Si no es fiable, es **ambigua**. Ejemplo: un `.lrc` en Windows-1252 con `ñ` empata con Windows-1250, donde ese byte es `ń`.
- La vista es **aproximada** solo cuando la codificación de origen no se puede confirmar: detección ambigua, archivo casi todo UTF-8 con bytes inválidos, o sin candidatos. Aun así, el archivo se modifica byte a byte.
- Quitar cabeceras **no depende** de la detección: las cabeceras y marcas son ASCII y se procesan byte a byte, así que un archivo Shift-JIS o Windows-1252 conserva todos sus bytes aunque la codificación sea ambigua.
- En `--diff` y `registro.txt` se indica la codificación detectada. Si no es fiable, la vista se marca como **aproximada**.
- Si el texto parece mojibake (`CanciÃ³n`), se avisa, pero **no se corrige**.

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
├── textio.py       Líneas sin pérdida, detección y conversión de codificación, diff
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

`tests/test_casos_generados.py` genera la biblioteca de casos de `tools/generar_casos.py` (ver `tools/CASOS.md`) en una carpeta temporal y comprueba simulación, `--apply` y `revert` sobre ella. También necesita `ffmpeg`.

## Licencia

MIT. Ver [LICENSE](LICENSE).
