# Changelog

## Sin publicar - Fase 2.1

### Pendiente
- Etapa 4 (`convert-lyrics`): opción de desempate de codificación, p. ej. `--prefer-encoding cp1252`. Serviría cuando charset-normalizer devuelve candidatos empatados de familias distintas (como cp1250 y cp1252 en español) y hoy el archivo se considera ambiguo.
- Etapa 6: medir memoria y tiempo con bibliotecas sintéticas de tamaño creciente. Sigue creciendo con la biblioteca la tabla de resultados por entrada que se arma al reanudar, revertir y mostrar el reporte (un diccionario de identificadores).
- Decidir si `--verify quick` debe ser el valor predeterminado en tarjetas SD (ver la medición en el README).

### Etapa 3: bibliotecas grandes, reanudación y limpieza

#### Agregado
- Ejecución en dos pasadas, con todo en disco:
  - `estado.json`, `plan.jsonl`, `diario.jsonl` (intent/done con fsync), `originales/`, `pendiente/` y `registro.txt`, que se escribe a medida que avanza.
  - El escáner recorre carpeta por carpeta (`scanner.iter_folders`) y la simulación usa una carpeta temporal fuera de la biblioteca.
- Progreso con archivos procesados, cambios, errores, tiempo transcurrido y tiempo restante estimado.
- `--resume CARPETA`: continúa una ejecución detenida solo si el diario, el respaldo y los archivos ya procesados son coherentes; si no, explica por qué y no toca nada.
- Comprobación de espacio libre antes de aplicar. Si el disco se llena (ENOSPC), la ejecución se detiene y el archivo en curso se restaura.
- Desconexión de la unidad (EIO, ENODEV, biblioteca inaccesible): la ejecución se detiene sin dar por aplicado lo que no se confirmó.
- Rutas largas en Windows (prefijo `\\?\`).
- `--verify full|quick` y `tools/medir_verificacion.py`.
- Comando `clean-backups RUTA --older-than DÍAS [--apply]`: es una simulación por defecto y nunca borra ejecuciones incompletas, reanudables o con escrituras pendientes.
- Pruebas: corte en cada paso del diario (inicio, copia, intent, escritura, después de escribir, done) para .lrc, MP3, FLAC, M4A y Opus, y a mitad de una escritura de bytes. También: falta de espacio antes de empezar y a mitad, desconexión simulada con la CLI, archivos modificados entre planificación y aplicación, negativas de `--resume`, `clean-backups`, frames repetidos, rutas largas y `--verify quick`.

#### Cambiado
- `--apply` muestra la lista completa de canciones, con el mismo criterio que `--diff`. `--limit N` la acorta, y `registro.txt` siempre la tiene entera.
- Con `--apply` y nada que modificar, el encabezado dice «APLICADO: no había nada que aplicar» y no se crea respaldo.
- Varias letras del mismo tipo en un archivo tienen etiquetas distintas («USLT [eng]», «LYRICS #2»...) en el diff, el registro y `revert`.
- El reporte de `scan` ya no dice que `normalize-lyrics` no modifica las letras casi vacías.
- Al restaurar un archivo tras una escritura fallida también se restaura su fecha de modificación.

#### Correcciones tras la prueba en Windows
- Desconexión en Windows: además de 21, 483, 1117 y 1167, se reconocen 15 (ERROR_INVALID_DRIVE), 55 (ERROR_DEV_NOT_EXIST), 121 (ERROR_SEM_TIMEOUT) y 1128 (ERROR_DEVICE_REMOVED). Cuando el error trae `winerror`, se decide solo por él. Así un acceso denegado (WinError 5) sigue siendo un fallo de ese archivo y no detiene la ejecución.
- Si la unidad desaparece durante la planificación, la ejecución se detiene sin aplicar nada (código 3). Si desaparece antes del reporte final, se muestra un resumen con el comando para reanudar.
- La prueba de desconexión ya no renombra la carpeta (en Windows falla con WinError 5): simula que toda operación sobre la biblioteca falla. Se prueba con EIO y con WinError 1167, cada código de Windows por separado, la desaparición de la letra de unidad, WinError 5 y la desconexión durante la planificación.
- Las rutas y comandos para copiar se imprimen sin que Rich los parta en varias líneas.
- `revert`: si no encuentra el respaldo, nombra `estado.json` (no `manifiesto.json`) y sugiere comprobar que la ruta esté en una sola línea. Con `--latest` acepta la carpeta de la biblioteca (o `ChoconostleLRCTool_back`) y usa el respaldo más reciente.

#### Incompatibilidades
- Las ejecuciones nuevas usan el formato 3 (`estado.json`, `plan.jsonl`, `diario.jsonl`) en lugar de `manifiesto.json`. `revert` sigue leyendo los formatos 1 y 2.
- Un error de E/S (EIO) detiene toda la ejecución en lugar de marcar solo ese archivo como fallido.

### Etapa 2: letras incrustadas editadas byte a byte

#### Agregado
- Paquete `rawtags`: edición byte a byte de letras en ID3v2.3/2.4 (MP3, WAV, AIFF), FLAC, MP4/M4A y APEv2 (WavPack, APE). Solo cambian la letra y los campos de tamaño o relleno; las demás etiquetas, las portadas y el audio quedan idénticos.
- Escritura verificada:
  - Antes de escribir se comprueba que el archivo no cambió desde la planificación.
  - Tras escribir se relee y se comprueban la región, las etiquetas ajenas a la letra (byte a byte) y el hash del audio. Si algo no coincide, se restaura el original.
- Diario de escrituras (`pendiente/` en el respaldo) y comando `recover` para archivos que quedaron a medias tras una interrupción. `revert` recupera antes de revertir; `--apply` no empieza si hay escrituras sin resolver.
- `--allow-full-rewrite`: permite reescribir el archivo completo (copia temporal verificada y reemplazo atómico) cuando la letra no cabe en el relleno. `--diff` muestra «reescritura completa, requiere X libres».
- Resumen «Archivos de audio omitidos por motivo».
- `revert` restaura las letras incrustadas idénticas byte a byte (parches inversos verificados con SHA-256) y la fecha de modificación.
- Pruebas: tag sin relleno, letra más larga que el relleno, portada de 2 MB, ID3v2.3 y v2.4 (UTF-16, Latin-1, UTF-8), TXXX con varios valores, ID3v2.2/unsynchronisation/frame comprimido, M4A con `moov` antes de `mdat`, interrupción a mitad de escritura y recuperación (MP3, FLAC, WavPack, M4A), error de E/S, fallo de verificación y archivo cambiado entre planificación y aplicación.

#### Corregido
- Al guardar MP3, M4A y WavPack ya no se reescriben frames ni campos ajenos a la letra. Antes se añadían terminadores a TIT2/TPE1, se reordenaban frames, se añadía un átomo `free` o se cambiaba el orden de los campos APEv2. Ahora `revert` deja toda la biblioteca de casos idéntica byte a byte.
- Los TXXX de letra con varios valores ya no se unen en uno.

#### Incompatibilidades con la v0.2.0
- **Ogg Vorbis y Opus ya no se modifican por defecto**: requieren `--allow-full-rewrite`, porque cambiar el comentario obliga a reescribir el archivo completo.
- Algunos archivos que antes se guardaban con mutagen ahora se omiten con un motivo: ID3v2.2 (antes se convertía a 2.3/2.4), unsynchronisation, frames comprimidos, M4A sin relleno, y letras que no caben en el relleno sin `--allow-full-rewrite`.
- Si el texto nuevo de un frame ID3 en Latin-1 no cabe en Latin-1, ya no se cambia la codificación del frame a UTF-16: se omite. Cambiarla será tarea de `convert-lyrics --id3-encoding`.
- El manifiesto pasa a la versión 2 (con `edits` y parches). `revert` sigue leyendo la versión 1.

### Etapa 1: normalize-lyrics conserva los bytes

#### Agregado
- `--strip-unknown-headers`: quita también las líneas `[palabra:valor]` desconocidas del inicio (p. ej. `[xtrack:7]`).
- `--offset-policy skip|first|last|sum` para archivos con dos o más `[offset:]` (por defecto `skip`).
- `--skip-near-empty` para omitir las letras casi vacías.
- `--encoding` acepta cualquier códec de texto de Python (`cp1252`, `shift_jis`, `gbk`...). Usa la misma función de conversión que usará `convert-lyrics`. Si un carácter no cabe, el archivo se omite y se lista (nunca se sustituye por `?`).
- Detección de la codificación de origen con `charset-normalizer` (nueva dependencia, Python puro). Una detección ambigua no se da por buena.
- Aviso de posible mojibake (sin corregirlo).
- Sección «Desconocidos / requieren decisión» en el reporte: offsets que no se aplicaron y cabeceras desconocidas que se conservan.
- `--diff` y `registro.txt` muestran los caracteres invisibles como `⟨U+200B⟩`, indican la codificación de origen y marcan la vista como aproximada si no se pudo confirmar.
- Pruebas con la biblioteca de `tools/generar_casos.py`, generada en una carpeta temporal.
- Familias de codificaciones compatibles (cp932/Shift-JIS, cp949/EUC-KR, GB18030/GBK, cp950/Big5, EUC-JP, cp1252/Latin-1).
- Prueba de la detección con charset-normalizer en Python puro (sin la extensión compilada), como en Termux.

#### Corregido
- Con charset-normalizer 3.5.2, un `.lrc` en EUC-KR se marcaba como vista aproximada. La decodificación como EUC-JIS-2004 quedaba a 0.1 de caos, justo en el margen de empate (inclusivo, 0.1). Ahora el empate es una diferencia menor que 0.05 y los candidatos de una misma familia compatible no se consideran rivales.

#### Cambiado
- `[lr:]` se añade a la lista de cabeceras conocidas (`[hash:]` ya estaba).
- Las cabeceras se reconocen también precedidas de U+200B, U+FEFF, U+200E, U+200F o U+2060; esos caracteres solo se quitan junto con la cabecera.
- Las líneas se separan solo por CRLF, CR y LF, también en el análisis de `scan`.
- La ayuda de `--strip-headers` y `--standardize-headers` muestra los corchetes (`[ti:]`, `[ar:]`...).
- `generar_casos.py`: el caso «13 ascii puro» es ASCII también en las cabeceras.

#### Incompatibilidades con la v0.2.0
- **`--encoding` pasa de `utf8` a `keep` por defecto.** `normalize-lyrics` ya no convierte a UTF-8 ni quita el BOM, salvo que se pida con `--encoding utf8`.
- Se conservan los saltos de línea originales (CRLF, CR o mezclados): ya no se convierten a LF, ni en archivos ni en letras incrustadas. Tampoco se añade un salto de línea final.
- Con dos o más `[offset:]` el archivo ya no se modifica por defecto (antes se aplicaba el último y se borraban todos).
- Un `[offset:]` inválido ya no se borra: el archivo no se toca y se lista.
- Un offset no se aplica si el archivo tiene marcas inválidas (`[00:61.00]`) o marcas `[mm:ss]` dentro del texto: el archivo no se toca y se lista.
- `[lr:]` ahora se quita.
- Las letras casi vacías ahora se procesan, con un aviso (antes no se modificaban).
- Un archivo con solo cabeceras ya no queda vacío: no se escribe y se avisa.
- U+FEFF al inicio de una letra incrustada solo se quita si va antes de una cabecera.
- U+2028, U+0085 y otros separadores Unicode ya no parten líneas. Esto puede cambiar el conteo de letras casi vacías.
- Los archivos de 8 bits que no se pueden decodificar con certeza ya no se marcan como error al quitar cabeceras: se procesan byte a byte.
- `--limit` no tiene límite por defecto con `--diff`.

## v0.2.0 - Fase 2: normalización de letras

### Agregado
- Comando `normalize-lyrics` (módulo `LyricsNormalizer`) con dos modos:
  - `--strip-headers`: quita las cabeceras LRC y aplica `[offset:]` a las marcas de tiempo antes de quitarlo.
  - `--standardize-headers`: deja solo `[ar:]`, `[ti:]`, `[al:]` y `[length:]`, con datos de las etiquetas (nunca inventados).
- Se aplica a todas las copias de la letra: `.lrc`/`.txt`, `LYRICS`, `UNSYNCEDLYRICS`, `USLT`, `SYLT`, `TXXX:LYRICS`, `©lyr` y APEv2.
- Simulación por defecto; `--apply` para modificar. Opciones `--encoding utf8|utf8-bom|keep`, `--only`, `--diff`.
- Letras casi vacías marcadas en `scan` y en `normalize-lyrics`, sin modificarlas.
- Respaldo en `ChoconostleLRCTool_back/<fecha-hora>/` con originales, `registro.txt` y `manifiesto.json`.
- Comando `revert` con detección de conflictos, `--force` y `--dry-run`.
- Pruebas de apply + revert que verifican que letras, etiquetas y audio quedan idénticos.

### Cambiado
- La versión de ID3 (2.3 o 2.4) se conserva al guardar.
- El escáner ignora la carpeta de respaldos.

## v0.1.0 - Fase 1: escaneo y reporte

### Agregado
- Comando `choconostle scan RUTA` con reporte en terminal y exportación a JSON (`--json`).
- Detección del códec real por contenido: FLAC, WAV, AIFF, APE, WavPack, MP3, AAC/M4A, ALAC, Opus, Ogg Vorbis y Matroska (.mka).
- Clasificación con pérdida / sin pérdida y detección de audio Dolby (AC-3, E-AC-3, TrueHD, AC-4) dentro de .m4a, .mp4, .mka y .wav.
- Aviso cuando la extensión no corresponde al contenido real.
- Letras externas (.lrc/.txt) e incrustadas (USLT, SYLT, LYRICS, UNSYNCEDLYRICS, ©lyr, APEv2, Matroska).
- Separación de letras sincronizadas y sin sincronizar, sin importar la extensión.
- Detección de cabeceras LRC, BOM y codificaciones distintas de UTF-8 (para la Fase 2).
- Portadas Cover/Folder y portadas incrustadas.
- Conteo de álbumes por carpeta y por etiqueta; las subcarpetas CD1/CD2 cuentan como un álbum.
- Reporte de álbumes con formatos mezclados, calidad mezclada o sin portada.
- Formatos sin soporte de letras incrustadas (WAV, AIFF, AAC/AC-3 sin contenedor) reportados como información, no como error.
- Pruebas con pytest.

### Cambiado
- Dependencias declaradas solo en `pyproject.toml`; se eliminó `requirements.txt`.
- `models/Readme.txt` reemplazado por `models/__init__.py`.

## v0.0.1 - Xoconostle Init

### Día 1
- Estructura del proyecto creada.
- Git configurado.
- Entorno virtual configurado.
- Arquitectura definida.
- Primer arranque del programa.