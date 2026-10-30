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
choconostle revert ~/Música --latest        # el respaldo más reciente de la biblioteca

# Si la ejecución se detuvo (sin espacio, tarjeta SD desconectada, Ctrl+C...)
choconostle normalize-lyrics ~/Música --resume ~/Música/ChoconostleLRCTool_back/2026-10-15_20-30-00

# Si solo quieres dejar a salvo un archivo que quedó a medias, sin continuar
choconostle recover ~/Música/ChoconostleLRCTool_back/2026-10-15_20-30-00

# Convertir a UTF-8 sin BOM con saltos LF (ver «Convertir letras»)
choconostle convert-lyrics ~/Música --apply

# Borrar respaldos de más de 30 días (simulación; con --apply los borra)
choconostle clean-backups ~/Música --older-than 30
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
| `--allow-full-rewrite` | Permite reescribir el archivo de audio completo cuando la letra no cabe en el relleno (y siempre en Ogg/Opus). Por defecto se omiten. |
| `--only CARPETA_O_ÁLBUM` | Limita a una carpeta (ruta absoluta o relativa a la biblioteca) o a un álbum (nombre según las etiquetas). Se puede repetir. |
| `--diff` | Muestra las diferencias línea por línea. Los caracteres invisibles se ven como `⟨U+200B⟩`. Con `--diff` se muestra la lista completa. |
| `--limit N` | Máximo de canciones por lista en pantalla (0 = todas). Por defecto: 20 en la simulación; todas con `--diff`; con `--apply`, todas hasta 50 entradas y, si hay más, solo el resumen, los fallos y la ruta de `registro.txt`. Si se corta, se indica cuántas faltan. `registro.txt` siempre tiene la lista completa. |
| `--resume CARPETA` | Continúa una ejecución detenida (ver «Bibliotecas grandes»). |
| `--verify auto\|full\|quick` | Verificación tras escribir en archivos de audio (ver «Bibliotecas grandes»). Por defecto `auto`. |
| `--no-progress` | No muestra la barra de progreso. |

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

### Letras incrustadas: solo se tocan los bytes de la letra

mutagen, al guardar, vuelve a escribir **todas** las etiquetas: en ID3 añade terminadores y reordena frames, en APEv2 ordena los campos por tamaño y en M4A añade un átomo `free`. Por eso las letras incrustadas se editan **byte a byte**: solo cambian el frame/campo/átomo de la letra y los campos de tamaño o relleno imprescindibles. Todo lo demás (otras etiquetas, portadas, audio) queda idéntico.

| Formato | Cómo se escribe | Si la letra crece y no cabe |
|---|---|---|
| MP3, WAV, AIFF (ID3v2.3 / v2.4) | Solo el frame `USLT`/`SYLT`/`TXXX` de letra, con su misma codificación, idioma, descripción y terminadores. El tag conserva su tamaño usando el relleno. Cada valor de un `TXXX` de letra se procesa por separado (nunca se unen). | Reescritura completa (MP3); en WAV/AIFF se omite. |
| FLAC | Solo el comentario de letra y el tamaño del bloque; el bloque `PADDING` compensa la diferencia. | Reescritura completa. |
| M4A | Solo el átomo `data` de `©lyr` y los tamaños de los átomos que lo contienen. La diferencia la absorbe un `free` contiguo, o el archivo cambia de tamaño al final si `moov` va después de `mdat`. **Los offsets del audio nunca se tocan.** | Si `moov` va antes de `mdat` y no hay relleno: se omite («M4A sin relleno»). |
| WavPack, APE (APEv2) | Solo el campo de letra y los tamaños de cabecera y pie, sin reordenar campos. El tag está al final: el audio no se mueve. | — |
| Ogg Vorbis, Opus | Siempre **reescritura completa**: el comentario va en las primeras páginas y cambiar su tamaño renumera todas las demás. | — |
| Matroska (`.mka`) | Solo lectura. | — |

**Reescritura completa.** Cuando hay que desplazar el audio, el archivo se escribe en una copia temporal junto al original, se verifica y se reemplaza de forma atómica. Necesita espacio libre del tamaño del archivo. **Por defecto esos archivos se omiten**: `--diff` muestra «reescritura completa, requiere X libres» y `--allow-full-rewrite` la permite.

**Se omiten, con el motivo contado en el resumen:** ID3v2.2 (mutagen lo convertiría a 2.3/2.4), ID3 con unsynchronisation, CRC o pie, frames de letra comprimidos o cifrados, frames de letra que no se pueden reconstruir idénticos, M4A sin relleno y reescrituras completas sin `--allow-full-rewrite`.

**Antes y después de cada escritura:**
1. Se comprueba que el archivo no cambió desde la planificación: tamaño, fecha de modificación y bytes de las etiquetas.
2. Se calcula el hash de todo lo que está fuera de la región de etiquetas (el audio).
3. Se guarda en el diario (`pendiente/` en el respaldo) la parte que se va a sobrescribir.
4. Tras escribir se relee el archivo y se comprueba que la región quedó como estaba prevista, que todas las etiquetas que no son letras son idénticas byte a byte y que el hash del audio no cambió. Si algo no coincide, se restaura el original y se informa del error.

Esto significa leer cada archivo de audio modificado dos veces completo.

**Interrupciones.** Si la escritura se corta (corte de luz, tarjeta SD desconectada), el diario conserva lo necesario para recuperar el archivo. `choconostle recover <carpeta-de-respaldo>` deja cada archivo como el original o como quedó aplicado. `revert` hace lo mismo antes de revertir, y `normalize-lyrics --apply` se niega a empezar mientras haya escrituras sin resolver.

### Bibliotecas grandes (tarjeta SD)

`normalize-lyrics` trabaja en **dos pasadas** y guarda todo en disco, no en memoria:

1. **Planificación.** Recorre la biblioteca carpeta por carpeta. Lee las etiquetas, nunca el audio completo, y escribe cada cambio en `plan.jsonl`. En memoria solo están la carpeta actual y los totales.
2. **Aplicación.** Lee el plan y aplica cada entrada. Antes de escribir comprueba que el original no cambió desde la planificación y que el resultado recalculado es exactamente el planeado. Un archivo modificado por otro programa en medio se marca como error y no se toca.

En la terminal se ven los archivos procesados, los cambios, los errores, el tiempo transcurrido y el tiempo **restante estimado**.

**Espacio libre.** Antes de aplicar se calcula el espacio necesario: copias de respaldo y parches, más el temporal más grande (una reescritura completa necesita el tamaño del archivo), más un margen de 16 MB. Si no hay suficiente, no se modifica nada. Si el disco se llena a mitad de ejecución, el archivo en curso se restaura y la ejecución se detiene.

**Desconexión de la tarjeta SD.** La ejecución se detiene en seguida (código de salida 3) cuando:
- hay un error de dispositivo: EIO, ENODEV, ENXIO, ESTALE, EROFS o ENOMEDIUM en Linux, macOS y Android;
- Windows devuelve uno de estos `winerror`:
  - 15 ERROR_INVALID_DRIVE;
  - 21 ERROR_NOT_READY;
  - 55 ERROR_DEV_NOT_EXIST;
  - 121 ERROR_SEM_TIMEOUT;
  - 483 ERROR_DEVICE_HARDWARE_ERROR;
  - 1117 ERROR_IO_DEVICE;
  - 1128 ERROR_DEVICE_REMOVED;
  - 1167 ERROR_DEVICE_NOT_CONNECTED;
- desaparecen la letra de unidad, el punto de montaje o la carpeta de respaldo.

Solo cuentan como aplicados los archivos confirmados en el diario. Si la unidad desaparece durante la planificación, no se modifica nada. Un **acceso denegado** (WinError 5, EACCES) no se trata como desconexión: es un fallo de ese archivo y la ejecución sigue.

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

Medición con 120 MP3 de 24 MB (2,94 GB), con la caché vaciada antes de cada pasada (`tools/medir_verificacion.py`):

| | `--verify full` | `--verify quick` |
|---|---|---|
| Leído por el programa | 6,0 GB (2× el audio) | 0,75 GB |
| Leído realmente del disco | 2,94 GB (1× el audio) | 0,50 GB |
| Tiempo (disco interno) | 8,05 s (0,067 s por MP3) | 2,05 s (0,017 s por MP3) |

La segunda lectura de `full` sale de la caché del sistema, no del disco. Por eso el costo real es leer en frío cada archivo modificado una vez, y esa relectura no comprueba el soporte físico (con ninguno de los dos modos). Estimación para una tarjeta SD que lee entre 20 y 90 MB/s, si se modificaran los 234 GB:
- `full`: entre 45 minutos y 3,3 horas.
- `quick`: unos 4 MB por archivo; con archivos de 24 MB, alrededor de una sexta parte de ese tiempo.

**Rutas largas en Windows.** Las rutas de 240 caracteres o más reciben el prefijo `\\?\` (o `\\?\UNC\` en red), así funcionan aunque Windows no tenga activado `LongPathsEnabled`. Otros programas (y algunas versiones de mutagen) pueden seguir limitados a 260 caracteres.

### Respaldo y reversión

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
- **Idénticas byte a byte**: los parches se aplican al revés y el resultado se comprueba con SHA-256 contra la región original antes de escribir. Se restaura también la fecha de modificación.
- Solo restaura una letra si sigue como la dejó `normalize-lyrics`. Si la cambiaste después, la marca como **conflicto** y no la toca. En archivos `.lrc`/`.txt`, `--force` la sobrescribe.
- Funciona también con ejecuciones interrumpidas: solo deshace lo que llegó a aplicarse.
- `--dry-run` muestra qué restauraría sin cambiar nada.
- Revertir dos veces no hace nada la segunda vez.
- Los respaldos de versiones anteriores (manifiesto versión 1 y 2) se siguen pudiendo revertir.
- `choconostle revert <biblioteca> --latest` usa el respaldo más reciente. También acepta la carpeta `ChoconostleLRCTool_back`. Sin `--latest`, lista los últimos respaldos para elegir.
- Si la carpeta no es un respaldo, el mensaje indica qué archivo se buscaba (`estado.json`, o `manifiesto.json` en versiones anteriores) y recuerda comprobar que la ruta esté completa y en una sola línea.

Las rutas y comandos que hay que copiar («Para deshacer», «Para continuar», «Respaldo guardado en») se imprimen **sin saltos de línea**, aunque sean más largos que la terminal. La terminal los muestra en varias filas, pero se copian como una sola línea.

**Varias letras del mismo tipo** en un archivo (dos `USLT`, dos `LYRICS`, valores de un `TXXX`) se muestran con etiquetas distintas («USLT [eng]», «USLT [spa]», «LYRICS #1», «LYRICS #2»). Cada una tiene su propio diff, respaldo y reversión.

### Limpieza de respaldos

`choconostle clean-backups RUTA --older-than DÍAS` lista los respaldos con al menos esos días de antigüedad. Solo los borra con `--apply`. **Nunca borra** un respaldo:
- incompleto o reanudable (aplicando, interrumpido, o planificado sin aplicar);
- con escrituras interrumpidas sin resolver;
- con entradas sin confirmar en el diario;
- con una fecha que no se puede leer.

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
| `--to CÓDEC` | Codificación de destino de los `.lrc`/`.txt`: `utf8` (sin BOM, por defecto), `utf8-bom` o cualquier códec de Python (`cp1252`, `shift_jis`, `utf-16`...). |
| `--eol lf\|crlf\|keep` | Saltos de línea de los `.lrc`/`.txt`. Por defecto `lf`; `keep` conserva los originales, aunque estén mezclados. |
| `--source-encoding CÓDEC` | Codificación de origen de los archivos de 8 bits cuya detección no es fiable. Nunca se aplica a archivos con BOM, UTF-8 válido o UTF-16. |
| `--prefer-encoding CÓDEC` | Desempata cuando charset-normalizer devuelve candidatos empatados de familias distintas (p. ej. cp1250 y cp1252). Solo se usa si está entre los empatados. |
| `--replace-char DE=A` | Sustitución (se puede repetir). `\uXXXX` para escribir un carácter por su código, `\=` para un `=` literal; `A` vacío borra. |
| `--replace-map ARCHIVO` | Sustituciones desde un archivo UTF-8: una por línea (`DE=A` o `DE<TAB>A`); `#` para comentarios. |
| `--id3-encoding latin1\|utf16\|utf8` | Codificación de los frames de letra ID3 (`USLT`, `SYLT`, `TXXX` de letra). |
| `--on-unencodable skip\|error` | Si el destino no puede representar algún carácter: `skip` (por defecto) omite el archivo y lo lista; `error` detiene todo antes de modificar nada. |
| `--allow-full-rewrite`, `--only`, `--diff`, `--limit`, `--resume`, `--verify`, `--include-hidden`, `--no-progress` | Igual que en `normalize-lyrics`. |

**Archivos y letras incrustadas.**
- `--to` y `--eol` solo se aplican a los archivos `.lrc`/`.txt`.
- Las letras incrustadas solo cambian con `--replace-char`/`--replace-map` (el texto) o con `--id3-encoding` (la codificación de los frames ID3). Sin esas opciones no se leen ni se tocan.

**Codificación de origen.** Un archivo solo se convierte si su codificación de origen es segura:
- BOM, UTF-8 válido o UTF-16;
- una detección fiable de charset-normalizer (ver «Codificación de origen» en `normalize-lyrics`);
- un empate resuelto con `--prefer-encoding`;
- `--source-encoding` en un archivo de 8 bits.

Si no, se omite y se lista con los candidatos. En `--diff` y en la lista de cambios se indica, por cada archivo, la codificación de origen y si es fiable. Si el texto parece mojibake se avisa, pero no se repara.

**Nunca se sustituyen caracteres por `?`.** Si el destino (`--to` o `--id3-encoding latin1`) no puede representar algún carácter, el archivo se omite y se lista con los caracteres que faltan. Con `--on-unencodable error`, la ejecución se detiene antes de aplicar nada.

**Sustituciones.**
- Se aplican en el orden indicado y **nunca tocan las marcas de tiempo** `[mm:ss.xx]` ni `<mm:ss.xx>`.
- **También se aplican a las cabeceras** (`[ti:Canción]` pasa a `[ti:Cancion]` con `ó=o`), porque son texto de la letra. Es intencional.
- El destino no puede contener `[`, `]`, `<`, `>` ni saltos de línea, para no crear marcas de tiempo ni partir líneas.
- Cada regla se registra con la cantidad de sustituciones que hizo en cada letra.

**Destino UTF-16 o UTF-32.** Se puede pedir (`--to utf-16`, `utf-16-le`, `utf-32`...), pero el encabezado del reporte y cada archivo afectado muestran un aviso: casi ningún reproductor lee letras `.lrc`/`.txt` en esas codificaciones. Se recomienda UTF-8.

**Funciones adicionales que no estaban en la especificación:**
- `--to` acepta cualquier códec de texto de Python, además de los pedidos: UTF-16 y UTF-32 en cualquier orden de bytes (con el aviso anterior), Latin-1, ISO-8859-x, Big5, etc.
- El comando `recover`, para resolver escrituras interrumpidas sin continuar la ejecución (`--resume` ya lo hace al reanudar).
- `tools/medir_verificacion.py`, para medir el costo de `--verify`.

**`--id3-encoding`.**
- Solo se rehacen los frames de letra (codificación, descripción y textos). Los demás frames quedan idénticos byte a byte.
- `utf8` solo es válido en ID3v2.4: en un tag v2.3 el frame se omite, y la versión del tag nunca se cambia.
- Pasar de Latin-1 a UTF-16 suele duplicar el tamaño y no caber en el relleno. Esos archivos necesitan reescritura completa: la simulación los cuenta por formato («Necesitarían reescritura completa: 7 (MP3: 7)») y se omiten salvo con `--allow-full-rewrite`.

## Estructura

```
src/choconostle/
├── cli.py          Comandos (typer)
├── config.py       Configuración: extensiones, nombres de portada, cabeceras LRC
├── scanner.py      Recorre carpetas y asocia letras y portadas a cada pista
├── audio.py        Detecta el códec real, con/sin pérdida, Dolby
├── tags.py         Lee etiquetas, letras y portadas incrustadas
├── matroska.py     Lector mínimo de .mka (mutagen no lo soporta)
├── embedded.py     Elige el editor de letras incrustadas de cada formato
├── rawtags/        Edición byte a byte: id3, flac, mp4, apev2, ogg y writer (escritura verificada, diario)
├── legacy_embedded.py  Edición con mutagen de la v0.2.0 (solo para revertir respaldos antiguos)
├── normalizer.py   Fase 2: LyricsNormalizer (cabeceras, offset, codificación)
├── converter.py    convert-lyrics: codificación, saltos de línea, sustituciones, --id3-encoding
├── textio.py       Líneas sin pérdida, detección y conversión de codificación, diff
├── run.py          Ejecución en dos pasadas: plan en disco, diario, --resume, clean-backups
├── backup.py       Revert (todas las versiones de respaldo) y recover
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

`tests/conftest.py` genera una vez por sesión la biblioteca de casos de `tools/generar_casos.py` (ver `tools/CASOS.md`) en una carpeta temporal; `test_casos_generados.py`, `test_rawtags.py` y `test_run.py` trabajan sobre copias. También necesitan `ffmpeg`.

`tools/medir_verificacion.py` crea una biblioteca sintética grande (Linux, ffmpeg) y mide el costo de `--verify full` frente a `--verify quick`.

## Licencia

MIT. Ver [LICENSE](LICENSE).
