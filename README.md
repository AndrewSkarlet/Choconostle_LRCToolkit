# Choconostle_LRCToolkit

[English version](README.en.md)

> ⚠️ **Versión candidata (1.0.0rc1), no estable.** Antes de usar `--apply`, haz una copia de tu biblioteca y ejecuta siempre primero la simulación (el mismo comando sin `--apply`). La herramienta guarda respaldos de lo que modifica, pero una copia propia es la única protección ante cualquier imprevisto. Qué se probó y qué no: [docs/PENDIENTES.md](docs/PENDIENTES.md).

Toolkit para analizar, reparar y organizar bibliotecas musicales con archivos LRC.

Versión actual: **1.0.0rc1 (Xoconostle)**, versión candidata.

| Comando | Qué hace |
|---|---|
| `scan` | Escanea la biblioteca y muestra un reporte. No modifica nada. |
| `normalize-lyrics` | Quita o estandariza las cabeceras de las letras, con respaldo. |
| `convert-lyrics` | Cambia la codificación, los saltos de línea o caracteres concretos de las letras, con respaldo. |
| `fix-gallery` | Crea `.nomedia` en las carpetas de álbum para que las galerías no muestren las portadas. |
| `revert` | Deshace una ejecución desde su respaldo. |
| `recover` | Resuelve escrituras interrumpidas sin continuar la ejecución. |
| `clean-backups` | Borra respaldos antiguos. |
| `welcome`, `version` | Bienvenida y versión. |

Todo comando que escribe es una **simulación por defecto**: nada se modifica sin `--apply`.

## Qué revisa

**Formato real de cada pista**, leído del contenido y no de la extensión: FLAC, WAV, AIFF, APE, WavPack, MP3, AAC/M4A (incluido ALAC), Opus, Ogg Vorbis y Matroska (`.mka`). Clasifica cada pista como con pérdida o sin pérdida e indica si el audio es Dolby (AC-3, E-AC-3, TrueHD, AC-4), aunque venga dentro de `.m4a`, `.mp4`, `.mka` o `.wav`. Avisa cuando la extensión no corresponde al contenido (por ejemplo, un FLAC renombrado a `.mp3`).

**Letras:**

- Externas: `.lrc` o `.txt` con el mismo nombre que la canción.
- Incrustadas: MP3 USLT/SYLT, FLAC/Ogg LYRICS/UNSYNCEDLYRICS, M4A ©lyr, APE/WavPack Lyrics y Matroska LYRICS.
- Separa letras sincronizadas (con marcas de tiempo) de sin sincronizar, sin importar la extensión.
- Problemas que se pueden corregir con `normalize-lyrics` y `convert-lyrics`: cabeceras LRC (`[ar:]`, `[ti:]`, `[al:]`, `[length:]`, `[offset:]`...), BOM y codificaciones distintas de UTF-8. Algunos reproductores (por ejemplo, Poweramp en Android) no cargan letras con cabeceras.
- Instrumentales (`[instrumental:true]`): se cuentan aparte y no se marcan como vacías.
- **Letras sospechosas** (solo aviso, ver más abajo): con URL o dominio, el mismo texto en muchas canciones distintas y letras muy cortas que no parecen letra. También en el JSON (`suspicious_lyrics`).

**Portadas:** `Cover.jpg`/`Folder.jpg` (también `.jpeg`, `.png`, `.webp`; sin distinguir mayúsculas) y portada incrustada.

**Álbumes,** por carpeta o por etiqueta. Las subcarpetas `CD1`, `Disc 2`, `Disco 1`... cuentan como un solo álbum. Reporta álbumes con:

- formatos mezclados (por ejemplo, FLAC con una pista M4A);
- calidad mezclada (bits o kHz distintos);
- sin portada.

**Formatos sin letras incrustadas** (WAV, AIFF, AAC/AC-3 sin contenedor): se indican como información, no como error. En esos casos usa un `.lrc` externo.

También lista archivos `.lrc` sin canción, audio no compatible (WMA, DSD...) y archivos que no se pudieron leer.

## Instalación

Requiere Python 3.9 o superior (probado en 3.14 y 3.15). No necesita compilador: `mutagen`, `typer` y `rich` son Python puro, y `charset-normalizer` usa una versión compilada si existe para tu sistema y, si no, la de Python puro.

### Linux / Windows

```bash
git clone https://github.com/AndrewSkarlet/Choconostle_LRCToolkit.git
cd Choconostle_LRCToolkit
python -m venv .venv
# Linux:   source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -e .
```

O sin clonar:

```bash
pip install git+https://github.com/AndrewSkarlet/Choconostle_LRCToolkit.git@v1.0.0-rc1
```

### Android (Termux)

```bash
pkg install python git
termux-setup-storage          # permite leer /sdcard
git clone https://github.com/AndrewSkarlet/Choconostle_LRCToolkit.git
cd Choconostle_LRCToolkit
pip install -e .
```

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
| `--json ARCHIVO`, `-j` | Guarda el reporte completo en JSON, con cada pista, sus letras y sus problemas. |
| `--limit N`, `-l` | Máximo de elementos por lista en pantalla (20 por defecto; 0 = todos). |
| `--include-hidden` | Incluye carpetas y archivos ocultos (que empiezan con `.`). |
| `--no-progress` | No muestra el indicador de progreso. |

`choconostle version` muestra la versión.

### Bienvenida

`choconostle` sin argumentos, o `choconostle welcome`, muestra un banner corto con el nombre, la versión, la descripción, los comandos y un consejo («empieza con scan; nada se modifica sin --apply»). Es solo ASCII y mide como máximo 40 columnas, para Termux y las consolas de Windows con otra codificación.

- No aparece con los demás comandos, ni cuando la salida no es una terminal interactiva (por ejemplo, redirigida a un archivo): en esos casos se muestra la ayuda.
- `--no-banner` (`choconostle --no-banner`) o la variable de entorno `CHOCONOSTLE_NO_BANNER` (con cualquier valor) lo apagan.

## Normalizar letras (normalize-lyrics)

Algunos reproductores no cargan letras con cabeceras LRC (`[ti:]`, `[ar:]`, `[by:]`...). `normalize-lyrics` las corrige en todas las copias de la letra:

- el archivo `.lrc` o `.txt`;
- las etiquetas LYRICS y UNSYNCEDLYRICS (FLAC, Ogg, Opus);
- USLT, SYLT y TXXX:LYRICS (MP3, WAV, AIFF);
- ©lyr (M4A);
- Lyrics (APE, WavPack).

No toca el audio ni las demás etiquetas.

```bash
# 1. Simulación (por defecto): muestra qué cambiaría, no modifica nada
choconostle normalize-lyrics ~/Música --strip-headers
choconostle normalize-lyrics ~/Música --strip-headers --diff     # con diferencias línea por línea

# 2. Aplicar
choconostle normalize-lyrics ~/Música --strip-headers --apply

# 3. Deshacer, si hace falta
choconostle revert ~/Música/ChoconostleLRCTool_back/2026-10-15_20-30-00
choconostle revert ~/Música --latest        # el respaldo más reciente de la biblioteca

# Si la ejecución se detuvo (sin espacio, tarjeta SD desconectada, Ctrl+C...)
choconostle normalize-lyrics ~/Música --resume ~/Música/ChoconostleLRCTool_back/2026-10-15_20-30-00

# Si solo quieres dejar a salvo un archivo que quedó a medias, sin continuar
choconostle recover ~/Música/ChoconostleLRCTool_back/2026-10-15_20-30-00
```

### Modos (elige uno)

| Modo | Qué hace |
|---|---|
| `--strip-headers` | Quita las cabeceras LRC conocidas (lista abajo) y conserva todas las marcas de tiempo. |
| `--standardize-headers` | Deja solo `[ar:]`, `[ti:]`, `[al:]` y `[length:]`, en ese orden y sin duplicados. Los valores salen de las etiquetas de la canción (artista, título, álbum) y de la duración del audio. Si falta un dato, esa cabecera no se escribe: nunca se inventan datos. Las demás cabeceras conocidas (`[by:]`, `[re:]`...) se quitan. |

Solo cambia lo que se pide. Las líneas que no son cabeceras se conservan byte por byte: codificación, BOM, saltos de línea (incluso mezclados CRLF/LF/CR), espacios y caracteres invisibles. Si no hay nada que quitar, el archivo no se reescribe. Las líneas se separan solo por CRLF, CR y LF (U+2028 y similares son parte del texto).

### Cabeceras conocidas

`[ar:]` `[ti:]` `[al:]` `[au:]` `[lr:]` `[by:]` `[length:]` `[offset:]` `[re:]` `[ve:]` `[tool:]` `[la:]` `[lang:]` `[language:]` `[id:]` `[key:]` `[hash:]` `[sign:]` `[total:]` `[encoding:]` `[kana:]` `[#:]`

- Se reconocen sin distinguir mayúsculas, con sangría y con espacios antes de `:`, en cualquier posición del archivo.
- `[ ti : valor ]`, con espacios dentro del corchete, no se reconoce como cabecera y se conserva.
- Pueden ir precedidas de U+200B, U+FEFF, U+200E, U+200F o U+2060: esos caracteres se quitan junto con la cabecera. En el resto de la letra no se tocan.
- Se quitan también las líneas vacías que quedan al inicio justo después de las cabeceras retiradas.
- `[Coro: Artista]`, `[Verso 1]` y otras etiquetas entre corchetes dentro de la letra son texto.

### Cabeceras desconocidas

Las líneas con forma `[palabra:valor]` del bloque inicial que no están en la lista (por ejemplo, `[xtrack:7]`) se conservan y se listan en la sección «Desconocidos / requieren decisión». El bloque inicial son las líneas anteriores a la primera línea de letra (con o sin marca de tiempo); puede incluir líneas vacías.

Con `--strip-unknown-headers` se quitan, pero solo las del bloque inicial. Todo lo que se quita aparece en `--diff` y en `registro.txt`.

### Secciones, instrumentales y datos extendidos (SpotiFLAC)

Estas líneas parecen cabeceras, pero no son desconocidas:

- **Etiquetas de sección** estilo Genius: `[Intro: Pitbull & Lil Jon]`, `[Chorus]`, `[Verse 1]`, `[Pre-Chorus]`... En inglés: Intro, Verse, Pre-Chorus, Chorus, Post-Chorus, Bridge, Outro, Hook, Refrain, Interlude, Breakdown y Drop. En español: Intro, Verso, Precoro, Coro, Estribillo, Puente, Outro e Interludio. Con o sin número y con o sin «: artista», sin distinguir mayúsculas. Son **letra**: nunca se quitan (tampoco con `--strip-unknown-headers`) y terminan el bloque inicial. No cuentan como línea con texto para «casi vacía».
- **`[instrumental:true]`**: se conserva siempre, no se marca como vacía ni casi vacía y se cuenta aparte como «Instrumentales» (también en `scan`).
- **Datos extendidos de SpotiFLAC**: `[x-romaji:...]`, `[x-romaji-words:...]`, `[x-translation:...]` (formato `tiempo_ms:base64`) y cualquier otra `[x-...:]`. Con `--strip-headers` y con `--standardize-headers` se quitan **solo** si están en el bloque inicial, antes de la primera línea de letra (una sección también es letra). Si aparecen después, no se tocan. En `--diff` («quita 4 datos extendidos (SpotiFLAC)»), en el resumen y en `--export` se cuentan como «datos extendidos (SpotiFLAC)».

### Letras sospechosas

`scan` y la simulación de `normalize-lyrics` muestran la sección «Letras sospechosas». Solo es un aviso: no se modifica nada.

- **Con URL o dominio:** `http://`, `https://`, `www.` y dominios terminados en `.com`, `.net`, `.org`, `.info`, `.xyz`, `.top`, `.site`, `.online`, `.club`, `.biz`, `.lyrics`, `.ru` o `.cn`. Sin `www.`, las terminaciones ambiguas como `.es`, `.me` o `.co` no cuentan («mira.Es la vida»).
- **Mismo texto en muchas canciones distintas:** se compara sin marcas de tiempo, cabeceras, secciones, mayúsculas ni espacios. Por defecto, 5 canciones o más; se cambia con `--repeat-threshold N`. Cada grupo muestra el título y la ruta de cada canción, para distinguir remixes y versiones (Slowed, Sped Up) de publicidad o textos de relleno.
- **Muy cortas, no parecen letra:** menos de 40 letras en total. Una letra «casi vacía» (2 líneas con texto o menos) sale solo en su sección, nunca en las dos; las instrumentales no cuentan.

En la vista compacta solo se indica cuántas hay; la lista completa está en `--export` y en el JSON de `scan` (`suspicious_lyrics`).

### `[offset:]`

- Si hay un único `[offset:]` válido (`+500`, `-300`, `250`), se aplica a las marcas de línea `[mm:ss.xx]` y por palabra `<mm:ss.xx>` antes de quitarlo. Un offset positivo adelanta la letra. Las marcas que quedarían en negativo se dejan en `00:00` (con aviso). Es el único caso en que se modifican líneas de la letra.
- Si el offset no se puede aplicar con seguridad, el archivo no se toca (ni cabeceras ni marcas) y se lista en «Desconocidos / requieren decisión»:
  - dos o más `[offset:]`: se resuelve con `--offset-policy first|last|sum` (por defecto `skip`). `sum` suma todos los valores; es la política recomendada si decides resolverlo;
  - `[offset:]` inválido (por ejemplo, `[offset:medio segundo]`): nunca se aplica, con ninguna política. Corrígelo a mano;
  - marcas de tiempo inválidas (`[00:61.00]`) o marcas `[mm:ss]` dentro del texto (estilo QQ) en un archivo con offset.

### Letras casi vacías y vacías

- Las letras casi vacías (2 líneas con texto o menos, por ejemplo solo `[00:00.00]Instrumental`) se procesan con un aviso. `--skip-near-empty` las omite.
- Si al quitar las cabeceras no quedaría letra (archivo con solo cabeceras), no se escribe y se avisa.

### Letras incrustadas

Mismas reglas de cabeceras y caracteres invisibles. Se conservan los saltos de línea internos. Si el texto empieza con U+FEFF, solo se quita cuando lo que sigue es una cabecera conocida. SYLT es binario (texto + tiempo): solo se quitan las entradas que sean cabeceras; un SYLT con `[offset:]` requiere decisión.

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
| `--allow-full-rewrite` | Permite reescribir el archivo de audio completo cuando la letra no cabe en el relleno (y siempre en Ogg/Opus). Por defecto se omiten. |
| `--only CARPETA_O_ÁLBUM` | Limita a una carpeta (ruta absoluta o relativa a la biblioteca) o a un álbum (nombre según las etiquetas). Se puede repetir. |
| `--diff` | Muestra las diferencias línea por línea. Los caracteres invisibles se ven como `⟨U+200B⟩`. Con `--diff` se muestra la lista completa. |
| `--limit N` | Máximo de canciones por lista en pantalla (0 = todas). Por defecto: 20 en la simulación; todas con `--diff`; con `--apply`, todas hasta 50 entradas y, si hay más, solo el resumen, los fallos y la ruta de `registro.txt`. Si se corta, se indica cuántas faltan. `registro.txt` siempre tiene la lista completa. |
| `--resume CARPETA` | Continúa una ejecución detenida (ver «Bibliotecas grandes»). |
| `--verify auto\|full\|quick` | Verificación tras escribir en archivos de audio (ver «Bibliotecas grandes»). Por defecto `auto`. |
| `--no-progress` | No muestra la barra de progreso. |
| `--compact` / `--full` | Fuerza la vista compacta o la completa (ver «Vista compacta»). |
| `--export ARCHIVO` | Guarda la lista completa (archivos, cabeceras y diferencias) en un archivo de texto, también en la simulación. |
| `--no-input` | No pregunta «¿Guardar la lista completa?» al terminar la simulación. |
| `--repeat-threshold N` | Letras sospechosas: avisa si el mismo texto está en N canciones distintas o más (por defecto 5). |

Con `--encoding` distinto de `keep`, un archivo se convierte solo si todos sus caracteres caben en la codificación de destino; si no, se omite y se lista con los caracteres que faltan (nunca se sustituyen por `?`). Tampoco se convierte un archivo cuya codificación de origen no se pueda confirmar. `--encoding` no cambia los saltos de línea: para eso, y para indicar la codificación de origen, está `convert-lyrics`.

### Codificación de origen

- BOM, UTF-8 válido y UTF-16 sin BOM se reconocen con certeza.
- Para los demás archivos (8 bits) se usa `charset-normalizer` como ayuda; la decisión la toma el programa:
  - Dos candidatos están empatados si su «caos» (la medida de `charset-normalizer`) difiere en menos de 0.05.
  - La detección es fiable si, entre los candidatos empatados que decodifican y recodifican los bytes sin cambios, todos dan el mismo texto o todos son de la misma familia compatible. Las familias son: Shift-JIS/cp932, EUC-KR/cp949, GBK/GB18030/GB2312, Big5/cp950, EUC-JP y Windows-1252/Latin-1. En una familia se usa la más amplia. Por eso un EUC-KR puede aparecer como «EUC-KR (cp949)».
  - Si no es fiable, es ambigua. Ejemplo: un `.lrc` en Windows-1252 con `ñ` empata con Windows-1250, donde ese byte es `ń`.
- La vista es aproximada solo cuando la codificación de origen no se puede confirmar: detección ambigua, archivo casi todo UTF-8 con bytes inválidos, o sin candidatos. Aun así, el archivo se modifica byte a byte.
- Quitar cabeceras no depende de la detección: las cabeceras y marcas son ASCII y se procesan byte a byte, así que un archivo Shift-JIS o Windows-1252 conserva todos sus bytes aunque la codificación sea ambigua.
- En `--diff` y `registro.txt` se indica la codificación detectada. Si no es fiable, la vista se marca como aproximada.
- Si el texto parece mojibake (`CanciÃ³n`), se avisa, pero no se corrige.

### Letras incrustadas: solo se tocan los bytes de la letra

`mutagen`, al guardar, vuelve a escribir todas las etiquetas: en ID3 añade terminadores y reordena frames, en APEv2 ordena los campos por tamaño y en M4A añade un átomo `free`. Por eso las letras incrustadas se editan byte a byte: solo cambian el frame/campo/átomo de la letra y los campos de tamaño o relleno imprescindibles. Todo lo demás (otras etiquetas, portadas, audio) queda idéntico. Esto se comprobó con archivos reales en FLAC y M4A, y con archivos generados en los demás formatos (ver [docs/PENDIENTES.md](docs/PENDIENTES.md)).

| Formato | Cómo se escribe | Si la letra crece y no cabe |
|---|---|---|
| MP3, WAV, AIFF (ID3v2.3 / v2.4) | Solo el frame USLT/SYLT/TXXX de letra, con su misma codificación, idioma, descripción y terminadores. El tag conserva su tamaño usando el relleno. Cada valor de un TXXX de letra se procesa por separado (nunca se unen). | Reescritura completa (MP3); en WAV/AIFF se omite. |
| FLAC | Solo el comentario de letra y el tamaño del bloque; el bloque PADDING compensa la diferencia. | Reescritura completa. |
| M4A | Solo el átomo `data` de ©lyr y los tamaños de los átomos que lo contienen. La diferencia la absorbe un `free` contiguo, o el archivo cambia de tamaño al final si `moov` va después de `mdat`. Los offsets del audio nunca se tocan. | Si `moov` va antes de `mdat` y no hay relleno: se omite («M4A sin relleno»). |
| WavPack, APE (APEv2) | Solo el campo de letra y los tamaños de cabecera y pie, sin reordenar campos. El tag está al final: el audio no se mueve. | — |
| Ogg Vorbis, Opus | Siempre reescritura completa: el comentario va en las primeras páginas y cambiar su tamaño renumera todas las demás. | — |
| Matroska (`.mka`) | Solo lectura. | — |

**Reescritura completa.** Cuando hay que desplazar el audio, el archivo se escribe en una copia temporal junto al original, se verifica y se reemplaza de forma atómica. Necesita espacio libre del tamaño del archivo. Por defecto esos archivos se omiten: `--diff` muestra «reescritura completa, requiere X libres» y `--allow-full-rewrite` la permite.

Se omiten, con el motivo contado en el resumen: ID3v2.2 (mutagen lo convertiría a 2.3/2.4), ID3 con unsynchronisation, CRC o pie, frames de letra comprimidos o cifrados, frames de letra que no se pueden reconstruir idénticos, M4A sin relleno y reescrituras completas sin `--allow-full-rewrite`.

Antes y después de cada escritura:

1. Se comprueba que el archivo no cambió desde la planificación: tamaño, fecha de modificación, bytes de las etiquetas y huella del audio. La huella se guarda en el plan y es el hash del primer y el último MB de lo que está fuera de la región de etiquetas (en Ogg, del archivo entero); con `--verify full` es además el hash de todo el audio. Sirve aunque la fecha no cambie (en Android dos escrituras seguidas pueden quedar con la misma `st_mtime_ns`). Sin `--verify full`, un cambio en el medio de un archivo de más de 2 MB no se detecta.
2. Se calcula el hash de todo lo que está fuera de la región de etiquetas (el audio).
3. Se guarda en el diario (`pendiente/` en el respaldo) la parte que se va a sobrescribir.
4. Tras escribir se relee el archivo y se comprueba que la región quedó como estaba prevista, que todas las etiquetas que no son letras son idénticas byte a byte y que el hash del audio no cambió. Si algo no coincide, se restaura el original y se informa del error.

**Interrupciones.** Si la escritura se corta (corte de luz, tarjeta SD desconectada), el diario conserva lo necesario para recuperar el archivo. `choconostle recover <carpeta-de-respaldo>` deja cada archivo como el original o como quedó aplicado. `revert` hace lo mismo antes de revertir, y `normalize-lyrics --apply` se niega a empezar mientras haya escrituras sin resolver.

## Bibliotecas grandes (tarjeta SD)

`normalize-lyrics` (y `convert-lyrics`) trabajan en dos pasadas y guardan todo en disco, no en memoria:

1. **Planificación.** Recorre la biblioteca carpeta por carpeta. Lee las etiquetas, nunca el audio completo, y escribe cada cambio en `plan.jsonl`. En memoria solo están la carpeta actual y los totales.
2. **Aplicación.** Lee el plan y aplica cada entrada. Antes de escribir comprueba que el original no cambió desde la planificación y que el resultado recalculado es exactamente el planeado. Un archivo modificado por otro programa en medio se marca como error y no se toca.

En la terminal, cada barra muestra el paso, los archivos procesados (N/M) y el tiempo transcurrido, por ejemplo `⠋ Aplicando 1234/4468 · 0:12:40`, más el nombre del archivo en curso en la vista completa (recortado al ancho de la terminal). En las verificaciones largas el paso pasa a «Verificando audio». Todas las barras (`scan`, planificación, aplicación, `revert`, `clean-backups` y `fix-gallery`) usan el mismo formato.

Medido con una biblioteca real en una tarjeta SD desde el teléfono (LG G8, Termux): 6690 letras en 4468 archivos; simulación en 8 min 45 s y `--apply` en 31 min 23 s, con 0 errores y un 8 % de batería sin cargador.

**Espacio libre.** Antes de aplicar se calcula el espacio necesario: copias de respaldo y parches, más el temporal más grande (una reescritura completa necesita el tamaño del archivo), más un margen de 16 MB. Si no hay suficiente, no se modifica nada. Si el disco se llena a mitad de ejecución, el archivo en curso se restaura y la ejecución se detiene.

**Desconexión de la tarjeta SD.** La ejecución se detiene en seguida (código de salida 3) cuando:

- hay un error de dispositivo: EIO, ENODEV, ENXIO, ESTALE, EROFS o ENOMEDIUM en Linux, macOS y Android;
- Windows devuelve uno de estos `winerror`: 15 ERROR_INVALID_DRIVE, 21 ERROR_NOT_READY, 55 ERROR_DEV_NOT_EXIST, 121 ERROR_SEM_TIMEOUT, 483 ERROR_DEVICE_HARDWARE_ERROR, 1117 ERROR_IO_DEVICE, 1128 ERROR_DEVICE_REMOVED, 1167 ERROR_DEVICE_NOT_CONNECTED;
- desaparecen la letra de unidad, el punto de montaje o la carpeta de respaldo.

Solo cuentan como aplicados los archivos confirmados en el diario. Si la unidad desaparece durante la planificación, no se modifica nada. Un acceso denegado (WinError 5, EACCES) no se trata como desconexión: es un fallo de ese archivo y la ejecución sigue.

**`--resume CARPETA`** continúa una ejecución detenida con las opciones guardadas. Antes de continuar comprueba que todo es coherente; si encuentra algo raro, se detiene, explica el motivo y no modifica nada. Comprueba que:

- la ejecución no esté completada y su planificación haya terminado;
- la carpeta pertenezca a esta biblioteca;
- las escrituras byte a byte interrumpidas se puedan recuperar;
- cada archivo ya aplicado siga como lo dejó la herramienta y su copia de respaldo exista y esté íntegra;
- cada archivo que quedó a medias sea exactamente el original o exactamente el resultado planeado.

**`--verify`** decide qué se comprueba después de escribir en un archivo de audio:

- `auto` (por defecto): `quick` cuando la edición es en su sitio o al final del archivo (el audio no se escribe) y `full` cuando hay reescritura completa (el audio se copia).
- `full`: el hash de todo el audio, antes y después.
- `quick`: las etiquetas byte a byte, el tamaño y el primer y el último MB del audio.

En ambos casos la región de etiquetas se relee y se verifica completa.

`--verify` también decide la huella del audio que el plan guarda para detectar cambios entre planificar y aplicar. Lectura extra por archivo que se va a modificar (los que no cambian no leen nada más; un archivo de menos de 2 MB se lee entero una vez):

| | Al planificar | Al aplicar, antes de escribir |
|---|---|---|
| `auto` / `quick`, edición en su sitio o al final | 2 MB | 0 (reutiliza el hash de `quick`) |
| `auto`, reescritura completa (y Ogg) | 2 MB | 2 MB |
| `full` | 2 MB + todo el audio | 0 (reutiliza el hash de `full`) |

Un plan de la rc1 (sin huella) se puede reanudar con `--resume`: se avisa de que para esos archivos se usa la protección anterior (tamaño, fecha y etiquetas).

Medición con 120 MP3 de 24 MB (2,94 GB), con la caché vaciada antes de cada pasada (`tools/medir_verificacion.py`):

| | `--verify full` | `--verify quick` |
|---|---|---|
| Leído por el programa | 6,0 GB (2× el audio) | 0,75 GB |
| Leído realmente del disco | 2,94 GB (1× el audio) | 0,50 GB |
| Tiempo (disco interno) | 8,05 s (0,067 s por MP3) | 2,05 s (0,017 s por MP3) |

La segunda lectura de `full` sale de la caché del sistema, no del disco. Por eso el costo real es leer en frío cada archivo modificado una vez, y esa relectura no comprueba el soporte físico (con ninguno de los dos modos).

**Tarjetas lentas.** En una tarjeta SD, el tiempo lo domina la sincronización a disco de cada escritura (respaldo, diario y archivo), que es lo que permite reanudar tras un corte. Medido: una escritura pequeña con sincronización tardó unos 19 ms en una SD FAT32 con adaptador USB 2.0, contra 1 ms en el disco interno. Aplicar 42 archivos tardó 25 s en esa tarjeta, y revertir 28 archivos tardó menos de 1 s en el disco interno.

**Rutas largas en Windows.** Las rutas de 240 caracteres o más reciben el prefijo `\\?\` (o `\\?\UNC\` en red), así funcionan aunque Windows no tenga activado `LongPathsEnabled`. Otros programas pueden seguir limitados a 260 caracteres.

**Memoria y tiempo.** Medido con hasta 13 800 archivos ([docs/RENDIMIENTO.md](docs/RENDIMIENTO.md)):

- `normalize-lyrics` y `convert-lyrics` usan prácticamente la misma memoria con 230 que con 13 800 archivos: unos 57 MB con `--diff` y 67 MB con `--apply`, incluido el intérprete. Crecen menos de 60 bytes por archivo.
- `revert` crece unos 420 bytes por archivo y `scan` unos 1,3 KB por archivo.
- El tiempo es lineal: unos 2 ms por archivo con `--apply` en disco local.

`tools/medir_rendimiento.py` repite la medición en otra carpeta, por ejemplo en la SD. Con `--ruta-real` mide sobre una copia de tu biblioteca, sin modificar el original.

## Vista compacta (terminales estrechas)

Pensada para Termux en vertical. Vale para `normalize-lyrics`, `convert-lyrics`, `revert`, `clean-backups` y `fix-gallery`.

**Cuándo se usa:**

1. `--compact` la fuerza y `--full` la desactiva. Las dos juntas dan error (código 2).
2. Si no se indica ninguna, `CHOCONOSTLE_COMPACT=1` la deja fija (y `CHOCONOSTLE_COMPACT=0`, la completa). Por ejemplo, en `~/.bashrc` de Termux: `export CHOCONOSTLE_COMPACT=1`.
3. Si no, se activa sola cuando la terminal tiene menos de 70 columnas. Si el ancho no se puede leer (salida redirigida a un archivo, por ejemplo), se usa la vista completa.

**Qué cambia:**

- El progreso es una sola línea corta, con el mismo formato que en la vista completa pero sin el nombre del archivo: `⠋ Aplicando 12/340 · 0:02:10`. Respeta `--no-progress` y no se anima si la salida no es una terminal.
- En lugar de la lista de cambios, solo el resumen: a modificar, con desconocidos (cabeceras desconocidas o letras que requieren decisión), sin cambios, omitidas y errores. Si hay letras con cabeceras desconocidas se indica cuántas y se sugiere `--export` para verlas.
- Siguen mostrándose completos los errores y los conflictos (archivo y motivo), los comandos para copiar (`--resume`, `revert`, «Respaldo guardado en»), cada uno en una sola línea, y el aviso de desconexión de la tarjeta (código 3).

**`--export ARCHIVO`** guarda la lista completa en un archivo de texto: archivos, cabeceras, diferencias (como `--diff --limit 0`), letras sospechosas y el bloque final. Funciona también en la simulación y en las dos vistas. En `revert` lista además cada letra con su resultado. Mientras escribe muestra «Guardando la lista en ...».

**«¿Guardar la lista completa? (s/N)».** Al terminar una simulación o `--diff` (también `revert --dry-run`, `clean-backups` y `fix-gallery` sin `--apply`), si la entrada y la salida son una terminal interactiva y no se usó `--export`, se pregunta si se guarda la lista. Si la respuesta es sí, se pide la ruta, con este valor por defecto:

- en Termux, `~/storage/shared/Download` si existe (lo crea `termux-setup-storage`); si no, la carpeta personal;
- el nombre es `choconostle_<comando>_<fecha-hora>.txt`;
- nunca se propone la carpeta actual ni una ruta dentro de la biblioteca o del repositorio (en ese caso, la carpeta temporal del sistema).

Sin terminal (salida redirigida, scripts) no se pregunta nada. `--no-input` desactiva la pregunta.

```bash
choconostle normalize-lyrics /sdcard/Music --strip-headers --compact --export ~/lista.txt
```

**Bloque final (en las dos vistas).** Al final de la salida se muestran el resumen, el tiempo total, la ruta del respaldo y la siguiente acción. En la simulación, la ruta es donde se guardará el respaldo, nunca uno ya creado:

```text
Resumen (42 letras): 12 a modificar, 3 con desconocidos, 25 sin cambios, 2 omitidas, 0 errores
Tiempo total: 3,2 s
Para aplicar, repite el comando con --apply. Antes se guardará un respaldo en:
/sdcard/Music/ChoconostleLRCTool_back
```

Tras `--apply` se muestran «Respaldo guardado en:» y el comando de `revert`; en `revert`, la carpeta de respaldo; en `clean-backups`, la carpeta de respaldos; y en `fix-gallery`, que no hace respaldo, la lista de lo creado (lo que usa `--remove` para deshacerlo). La vista completa no cambia salvo este bloque final.

**Tiempo total.** Se mide desde el inicio del comando y también se muestra cuando termina con error. Con `--apply` y `--resume` se escribe en `registro.txt` de la carpeta de respaldo; `revert` lo escribe en su `revert_<fecha>.txt` y en `registro.txt`.

## Respaldo y reversión

Antes de modificar nada, `--apply` crea:

```
<biblioteca>/ChoconostleLRCTool_back/<fecha-hora>/
├── estado.json       fase (planificada, aplicando, interrumpida, completada), opciones y totales
├── plan.jsonl        un registro por archivo de letra o de audio, con hashes y diferencias
├── diario.jsonl      "intent" antes de escribir y "done" después, con fsync
├── originales/       copia de cada .lrc/.txt y parches de las ediciones incrustadas
├── pendiente/        diario de escrituras byte a byte en curso (vacío si todo terminó)
└── registro.txt      qué se cambió, con las diferencias; se escribe a medida que avanza
```

No se copian archivos de audio ni portadas. De cada letra incrustada se guardan los «parches»: los bytes originales de la letra y de los campos de tamaño o relleno que cambiaron. El escáner ignora esta carpeta.

Cada entrada pasa por estos pasos, y una interrupción en cualquiera de ellos se resuelve con `--resume` o `revert`:

1. copia de respaldo (fsync);
2. `intent` (fsync);
3. escritura;
4. verificación;
5. `done` (fsync).

`choconostle revert <carpeta>` restaura todas las letras del respaldo:

- Idénticas byte a byte: los parches se aplican al revés y el resultado se comprueba con SHA-256 contra la región original antes de escribir. Se restaura también la fecha de modificación.
- Usa la misma verificación con la que se aplicó (guardada en el diario).
- Solo restaura una letra si sigue como la dejó la herramienta. Si la cambiaste después, la marca como conflicto y no la toca. En archivos `.lrc`/`.txt`, `--force` la sobrescribe.
- Funciona también con ejecuciones interrumpidas: solo deshace lo que llegó a aplicarse.
- `--dry-run` muestra qué restauraría sin cambiar nada.
- Revertir dos veces no hace nada la segunda vez.
- Antes de empezar se comprueba el espacio libre (el temporal más grande más un margen).
- Si la unidad se desconecta o se queda sin espacio, `revert` se detiene (código 3) y muestra el comando para repetirlo; al repetirlo continúa donde quedó.
- Un acceso denegado o una copia de respaldo que falta solo afectan a ese archivo (código 1).
- Los respaldos de versiones anteriores (manifiesto versión 1 y 2) se siguen pudiendo revertir.
- `choconostle revert <biblioteca> --latest` usa el respaldo más reciente. También acepta la carpeta `ChoconostleLRCTool_back`. Sin `--latest`, lista los últimos respaldos para elegir.
- Si la carpeta no es un respaldo, el mensaje indica qué archivo se buscaba (`estado.json`, o `manifiesto.json` en versiones anteriores) y recuerda comprobar que la ruta esté completa y en una sola línea.

Las rutas y comandos que hay que copiar («Para deshacer», «Para continuar», «Respaldo guardado en») se imprimen sin saltos de línea, aunque sean más largos que la terminal. La terminal los muestra en varias filas, pero se copian como una sola línea.

Varias letras del mismo tipo en un archivo (dos USLT, dos LYRICS, valores de un TXXX) se muestran con etiquetas distintas («USLT [eng]», «USLT [spa]», «LYRICS #1», «LYRICS #2»). Cada una tiene su propio diff, respaldo y reversión.

## Limpieza de respaldos

`choconostle clean-backups RUTA --older-than DÍAS` lista los respaldos con al menos esos días de antigüedad. Solo los borra con `--apply`.

```bash
choconostle clean-backups ~/Música --older-than 30            # simulación
choconostle clean-backups ~/Música --older-than 30 --apply
```

El borrado es reanudable:

- Cada carpeta se renombra primero a `<nombre>.borrando` y se borra archivo por archivo.
- Si la unidad se desconecta, se detiene (código 3) y la siguiente ejecución termina los borrados a medias.
- Si una carpeta no se puede borrar (por ejemplo, acceso denegado), se sigue con las demás (código 1).

Nunca borra un respaldo:

- incompleto o reanudable (aplicando, interrumpido, o planificado sin aplicar);
- con escrituras interrumpidas sin resolver;
- con entradas sin confirmar en el diario;
- con una fecha que no se puede leer.

Tampoco borra `fix-gallery_creados.json`.

## Convertir letras (convert-lyrics)

`convert-lyrics` cambia la codificación, los saltos de línea y caracteres concretos de las letras. Usa el mismo sistema que `normalize-lyrics`: simulación por defecto, `--apply`, plan en disco, diario, respaldo, `--resume`, `revert` y las mismas comprobaciones antes y después de escribir.

```bash
# Simulación: qué archivos cambiarían y por qué (codificación detectada y si es fiable)
choconostle convert-lyrics ~/Música --diff

# Aplicar con los valores por defecto: UTF-8 sin BOM y saltos LF
choconostle convert-lyrics ~/Música --apply

# Desempatar Windows-1252 frente a Windows-1250 en letras en español
choconostle convert-lyrics ~/Música --prefer-encoding cp1252 --apply

# Sustituir el apóstrofo tipográfico, también en las letras incrustadas
choconostle convert-lyrics ~/Música --replace-char "’='" --apply
```

| Opción | Descripción |
|---|---|
| `--to CÓDEC` | Codificación de destino de los `.lrc`/`.txt`: `utf8` (sin BOM, por defecto), `utf8-bom` o cualquier códec de texto de Python (`cp1252`, `shift_jis`, Latin-1, ISO-8859-x, Big5, UTF-16, UTF-32...). |
| `--eol lf\|crlf\|keep` | Saltos de línea de los `.lrc`/`.txt`. Por defecto `lf`; `keep` conserva los originales, aunque estén mezclados. |
| `--source-encoding CÓDEC` | Codificación de origen de los archivos de 8 bits cuya detección no es fiable. Nunca se aplica a archivos con BOM, UTF-8 válido o UTF-16. |
| `--prefer-encoding CÓDEC` | Desempata cuando `charset-normalizer` devuelve candidatos empatados de familias distintas (por ejemplo, cp1250 y cp1252). Solo se usa si está entre los empatados. |
| `--replace-char DE=A` | Sustitución (se puede repetir). `\uXXXX` para escribir un carácter por su código, `\=` para un `=` literal; `A` vacío borra. |
| `--replace-map ARCHIVO` | Sustituciones desde un archivo UTF-8: una por línea (`DE=A` o `DE<TAB>A`); `#` para comentarios. |
| `--id3-encoding latin1\|utf16\|utf8` | Codificación de los frames de letra ID3 (USLT, SYLT, TXXX de letra). |
| `--on-unencodable skip\|error` | Si el destino no puede representar algún carácter: `skip` (por defecto) omite el archivo y lo lista; `error` detiene todo antes de modificar nada. |
| `--allow-full-rewrite`, `--only`, `--diff`, `--limit`, `--resume`, `--verify`, `--include-hidden`, `--no-progress` | Igual que en `normalize-lyrics`. |

**Archivos y letras incrustadas.**

- `--to` y `--eol` solo se aplican a los archivos `.lrc`/`.txt`.
- Las letras incrustadas solo cambian con `--replace-char`/`--replace-map` (el texto) o con `--id3-encoding` (la codificación de los frames ID3). Sin esas opciones no se leen ni se tocan.

**Codificación de origen.** Un archivo solo se convierte si su codificación de origen es segura:

- BOM, UTF-8 válido o UTF-16;
- una detección fiable de `charset-normalizer` (ver «Codificación de origen» en `normalize-lyrics`);
- un empate resuelto con `--prefer-encoding`;
- `--source-encoding` en un archivo de 8 bits.

Si no, se omite y se lista con los candidatos. En `--diff` y en la lista de cambios se indica, por cada archivo, la codificación de origen y si es fiable. Si el texto parece mojibake se avisa, pero no se repara.

**Nunca se sustituyen caracteres por `?`.** Si el destino (`--to` o `--id3-encoding latin1`) no puede representar algún carácter, el archivo se omite y se lista con los caracteres que faltan. Con `--on-unencodable error`, la ejecución se detiene antes de aplicar nada.

**Sustituciones.**

- Se aplican en el orden indicado y nunca tocan las marcas de tiempo `[mm:ss.xx]` ni `<mm:ss.xx>`.
- También se aplican a las cabeceras (`[ti:Canción]` pasa a `[ti:Cancion]` con `ó=o`), porque son texto de la letra. Es intencional.
- El destino no puede contener `[`, `]`, `<`, `>` ni saltos de línea, para no crear marcas de tiempo ni partir líneas.
- Cada regla se registra con la cantidad de sustituciones que hizo en cada letra.

**Destino UTF-16 o UTF-32.** Se puede pedir (`--to utf-16`, `utf-16-le`, `utf-32`...), pero el encabezado del reporte y cada archivo afectado muestran un aviso: casi ningún reproductor lee letras `.lrc`/`.txt` en esas codificaciones. Se recomienda UTF-8.

**`--id3-encoding`.**

- Solo se rehacen los frames de letra (codificación, descripción y textos). Los demás frames quedan idénticos byte a byte.
- `utf8` solo es válido en ID3v2.4: en un tag v2.3 el frame se omite, y la versión del tag nunca se cambia.
- Pasar de Latin-1 a UTF-16 suele duplicar el tamaño y no caber en el relleno. Esos archivos necesitan reescritura completa: la simulación los cuenta por formato («Necesitarían reescritura completa: 7 (MP3: 7)») y se omiten salvo con `--allow-full-rewrite`.

## Ocultar portadas en la galería (fix-gallery)

Las apps de galería de Android muestran las portadas (`cover.jpg`, `folder.png`...) como si fueran fotos. `fix-gallery` crea un archivo vacío `.nomedia` en las carpetas de álbum para ocultarlas. No abre ni modifica audio, letras ni etiquetas.

> ⚠️ **Advertencia (MediaStore).** Android no indexa nada de una carpeta con `.nomedia`: las apps que leen el índice de medios del sistema (MediaStore) dejan de listar también las canciones de esa carpeta. Algunas apps recorren las carpetas por su cuenta y siguen viéndolas. Se probó en un teléfono Android con una app de música, que siguió viendo las canciones; otras apps pueden reaccionar distinto. Prueba primero con tu app de música en un solo álbum (`--only`) antes de aplicarlo a toda la biblioteca. Para deshacerlo: `fix-gallery RUTA --remove --apply`.

```bash
# 1. Simulación (por defecto): qué carpetas recibirían .nomedia
choconostle fix-gallery /sdcard/Music

# 2. Prueba con un solo álbum y revisa tu app de música
choconostle fix-gallery /sdcard/Music --only "Artista/Álbum" --apply

# 3. Toda la biblioteca
choconostle fix-gallery /sdcard/Music --apply

# Deshacer: quita solo los .nomedia que creó fix-gallery
choconostle fix-gallery /sdcard/Music --remove --apply
```

| Opción | Descripción |
|---|---|
| `--apply` | Crea los `.nomedia` (o, con `--remove`, los quita). Sin ella solo se simula. |
| `--all-folders` | Pone `.nomedia` en todas las carpetas con audio, tengan o no imágenes. Por defecto, solo en las carpetas con imágenes (jpg, jpeg, png, webp, bmp, gif, sin distinguir mayúsculas). |
| `--include-root` | Incluye la carpeta raíz indicada y las carpetas Music, Pictures, DCIM y Download. |
| `--remove` | Quita solo los `.nomedia` que creó esta herramienta. Nunca borra uno que ya existía ni uno al que se le escribió contenido. |
| `--only CARPETA_O_ÁLBUM` | Igual que en `normalize-lyrics`. Se puede repetir. |
| `--limit N`, `--include-hidden`, `--no-progress` | Igual que en `scan`. |

- **Carpetas que se omiten.** Una carpeta que ya tiene `.nomedia` no se toca y cuenta como «ya existente», así que repetir el comando no cambia nada.
- **Carpeta raíz.** La carpeta que indicas no recibe `.nomedia` si es una raíz, es decir, si tiene subcarpetas con audio. Si tiene audio directamente y ninguna subcarpeta con audio, es un álbum y se trata como cualquier otro. Las carpetas Music, Pictures, DCIM y Download (en cualquier nivel) nunca se tocan. Las dos protecciones se quitan con `--include-root`, y el reporte indica cuándo la raíz queda fuera.
- **Lista de lo creado.** Se guarda en `ChoconostleLRCTool_back/fix-gallery_creados.json`, que `clean-backups` nunca borra. Se escribe por tandas de 50 carpetas y cada tanda se anota antes de crear sus archivos, así que, si la unidad se desconecta, la ejecución siguiente confirma lo que sí se creó.
- **Desconexión.** Si la unidad desaparece, el comando se detiene con código 3 y muestra cómo repetirlo. Un error en una sola carpeta (por ejemplo, acceso denegado) se lista y da código 1.
- **Resumen.** Carpetas revisadas, creadas, ya existentes, omitidas (sin imágenes y protegidas) y con error. Mientras trabaja muestra una barra con «N de M».

## Probado y no probado

Resumen; la lista completa está en [docs/PENDIENTES.md](docs/PENDIENTES.md).

**Probado por el autor con la versión 1.0.0rc2:**

- Suite automática completa: 525/525 en Windows, Moto Edge 60 Fusion, LG G8 y Samsung A31 (Termux).
- Tarjeta SD desde el teléfono, con la biblioteca real: LG G8 con Termux, 6690 letras en 4468 archivos; simulación en 8 min 45 s, `--apply` en 31 min 23 s, 0 errores, 8 % de batería sin cargador. Una segunda simulación dio 0 a modificar, y Poweramp y otra app leen bien las letras.
- Resuelto: un cambio externo solo en el audio entre planificar y aplicar no se detectaba en Android (misma `st_mtime_ns`); ahora el plan guarda la huella del audio.

**Probado con la versión 1.0.0rc1:**

- Windows: ciclos de `--apply` y `revert` con FLAC y M4A reales, comparados byte a byte; una desconexión real de una tarjeta SD a mitad de ejecución, seguida de `--resume` (129 archivos, 0 diferencias); rutas de más de 260 caracteres; `clean-backups` y `fix-gallery`.
- Android (Termux): `--apply` y `revert` con FLAC reales en la memoria interna; `fix-gallery` en un teléfono con una app de música.

**No probado:** NAS, ARM fuera de Android, un disco lleno real (solo simulado), el editor ID3 con MP3 reales con cabeceras, otras apps de música con `.nomedia`, uso de CPU. Lo nuevo de la 1.0.0rc3.dev0 (secciones, letras sospechosas, barras y pregunta al final) solo con la suite automática.

## Estructura

```
src/choconostle/
├── cli.py              Comandos (typer)
├── config.py           Configuración: extensiones, nombres de portada, cabeceras LRC
├── scanner.py          Recorre carpetas y asocia letras y portadas a cada pista
├── audio.py            Detecta el códec real, con/sin pérdida, Dolby
├── tags.py             Lee etiquetas, letras y portadas incrustadas
├── matroska.py         Lector mínimo de .mka (mutagen no lo soporta)
├── embedded.py         Elige el editor de letras incrustadas de cada formato
├── rawtags/            Edición byte a byte: id3, flac, mp4, apev2, ogg y writer (escritura verificada, diario)
├── legacy_embedded.py  Edición con mutagen de la v0.2.0 (solo para revertir respaldos antiguos)
├── normalizer.py       normalize-lyrics: cabeceras, offset, codificación
├── converter.py        convert-lyrics: codificación, saltos de línea, sustituciones, --id3-encoding
├── textio.py           Líneas sin pérdida, detección y conversión de codificación, diff
├── run.py              Ejecución en dos pasadas: plan en disco, diario, --resume, clean-backups
├── backup.py           revert (todas las versiones de respaldo) y recover
├── gallery.py          fix-gallery: .nomedia en las carpetas de álbum y lista de lo creado
├── lrc.py              Análisis de letras: marcas de tiempo, cabeceras, BOM, codificación
├── albums.py           Agrupa pistas en álbumes
├── report.py           Reporte en terminal y JSON
├── utils.py            Formato de tamaños, duraciones, calidad
└── models/             Track, LyricsInfo, Album
```

## Pruebas

```bash
pip install -e ".[dev]"
pytest
```

Las pruebas de FLAC, MP3, WAV y APE generan los archivos en Python puro. Las de M4A, Opus, Ogg, WavPack, AIFF, Matroska y Dolby usan `ffmpeg` y se omiten si no está instalado.

`tests/conftest.py` genera una vez por sesión la biblioteca de casos de `tools/generar_casos.py` (ver `tools/CASOS.md`) en una carpeta temporal; `test_casos_generados.py`, `test_rawtags.py` y `test_run.py` trabajan sobre copias. También necesitan `ffmpeg`.

`tests/test_memoria.py` comprueba que el pico de memoria de un ciclo completo (planificar, aplicar, reporte, revertir) no crece con el número de archivos. Tarda unos 11 s en Linux y entre 45 y 57 s en Windows. `tools/medir_rendimiento.py` mide memoria y tiempo con bibliotecas de tamaño creciente (ver [docs/RENDIMIENTO.md](docs/RENDIMIENTO.md)).

`tools/medir_verificacion.py` crea una biblioteca sintética grande (Linux, `ffmpeg`) y mide el costo de `--verify full` frente a `--verify quick`.

`tests/COBERTURA.md` resume qué prueba cubre cada situación de riesgo (corte en cada paso del diario, desconexión EIO/WinError 1167/3/5, falta de espacio ENOSPC/WinError 112, archivos modificados, `--resume` con respaldos incompletos o ajenos) para `normalize-lyrics`, `convert-lyrics`, `revert` y `clean-backups`. Todas se ejecutan en dos modos («posix» y «windows») que reproducen cómo se comporta `os.path` en cada sistema.

## Licencia

MIT. Ver [LICENSE](LICENSE). Autor: AndrewSkarlet.
