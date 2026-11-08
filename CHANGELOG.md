# Changelog

## v1.0.0-rc2

### Agregado (commit 2: tiempo total)
- **Tiempo total** al final del resumen de `normalize-lyrics` y `convert-lyrics` (simulación, `--diff`, `--apply` y `--resume`), `revert` y `fix-gallery`: «Tiempo total: 2,3 s», «2 min 05 s» o «1 h 02 min 05 s». Se mide con `time.perf_counter()` desde el inicio del comando y también se muestra cuando termina con error (código 1, 2, 3 o Ctrl+C), en la salida de errores.
- Se escribe en `registro.txt` de la carpeta de respaldo con `--apply` (y «(reanudación)» con `--resume`). `revert` lo escribe en su `revert_<fecha>.txt` y añade «(revert del <fecha>)» a `registro.txt`. La simulación y `fix-gallery` no tienen `registro.txt`: solo se muestra en pantalla.

### Corregido (commit 1: huella del audio en el plan)
- **Un cambio externo entre planificar y aplicar podía pasar sin detectarse.** Solo se comparaban el tamaño, la fecha de modificación y los bytes de las etiquetas; en Android (Termux) dos escrituras seguidas pueden quedar con la misma `st_mtime_ns`, y un byte de audio cambiado no se notaba (`test_file_changed_between_plan_and_apply` fallaba de forma intermitente en tres teléfonos).
  - El plan de `normalize-lyrics` y `convert-lyrics` guarda ahora una **huella del audio** de cada archivo que se va a modificar: el hash del tamaño, el primer y el último MB de lo que está fuera de la región de etiquetas (en Ogg, del archivo entero), igual que `--verify quick`. Antes de escribir se recalcula sobre exactamente los mismos bytes y, si no coincide, el archivo falla con «el audio cambió desde que se planearon los cambios» y no se toca.
  - Con `--verify full` el plan guarda además el SHA-256 de todo el audio, que detecta también cambios en el medio.
  - **Límite:** sin `--verify full`, el hash solo cubre el primer y el último MB; un cambio en el medio de un archivo de más de 2 MB no se detecta (hay una prueba que lo documenta).
  - Lectura extra por archivo que se va a modificar: 2 MB al planificar; al aplicar, 0 con `auto`/`quick` en su sitio (reutiliza el hash que ya se calculaba) y 2 MB en reescrituras completas y Ogg. Con `full`, además, todo el audio una vez al planificar y 0 al aplicar. Los archivos sin cambios no leen nada más.
  - `--resume` sobre un plan de la rc1 (sin huella) avisa de que esos archivos usan la protección anterior.
  - Pruebas nuevas (`tests/test_huella.py`): un byte cambiado tras planificar con la fecha restaurada con `os.utime`, en los dos comandos, con MP3, Ogg y un archivo de menos de 2 MB; un byte en el medio del audio (no se detecta por defecto, sí con `--verify full`); y el aviso de `--resume`. `test_file_changed_between_plan_and_apply` ya no depende de la resolución de mtime.

## v1.0.0-rc1

Versión candidata (`1.0.0rc1` en `pyproject.toml` y `config.py`).

### Cambiado (commit 1: textos y empaquetado, sin cambios de lógica)
- Versión 1.0.0rc1 y clasificador «Development Status :: 4 - Beta».
- `pyproject.toml`: licencia como cadena SPDX (`license = "MIT"`), sin el clasificador de licencia y con `setuptools>=77` para construir (compatible con `requires-python = ">=3.9"`: setuptools 77 requiere Python 3.9 o posterior). `pip install -e .` ya no muestra los avisos de licencia. `LICENSE` no cambia.
- El banner lista todos los comandos de la ayuda: scan, normalize-lyrics, convert-lyrics, revert, recover, clean-backups, fix-gallery, welcome y version.
- `scan`: la sección «Letras a corregir en la Fase 2» pasa a «Letras con cabeceras u otros problemas», y la nota sobre Poweramp se sustituye por «normalize-lyrics y convert-lyrics pueden corregirlas».

### Cambiado (commit 2: progreso, revert y resumen del paro)
- **Progreso «N de M» con indicador animado** en `revert` («Revirtiendo»), en la comprobación previa de `--resume` («Comprobando lo ya aplicado», antes del avance de «Aplicando», que ya existía) y en `clean-backups` («Borrando respaldos»). En las verificaciones largas se indica el paso («verificando el audio completo: archivo»). Respeta `--no-progress` (nuevo en `revert` y `clean-backups`) y no se anima si la salida no es una terminal.
- **`revert` era más lento que `--apply`** (14,5 s frente a 5,2 s con 28 archivos en una SD). Causa: deshacía cada edición incrustada con la verificación completa (hash de todo el audio antes y después de escribir) aunque `--apply` hubiera usado la rápida. Ahora `revert` usa la misma verificación que se usó al aplicar (la de `--verify`, guardada en el diario; `auto` en respaldos antiguos), que sigue comparando byte a byte la región editada y las etiquetas ajenas. Con la biblioteca de casos: 23 ediciones, todas con verificación rápida (antes, todas con la completa). No se ha vuelto a medir en una SD.
- **Resumen del paro tras una desconexión.** Mostraba «Aplicadas 0 / Sin aplicar 42» aunque había archivos aplicados. Causa: con la SD quitada, en Windows `Path.exists()` devuelve False (WinError 21 o 3) en vez de fallar, y el diario y el plan se leían como vacíos. Ahora:
  - leer el diario o el plan falla si tampoco está su carpeta, y no se toma como «vacío»;
  - si la unidad no se puede leer, el resumen («Aplicadas», «Con error», «Sin aplicar») sale de la copia en memoria de los eventos `done` que se confirmaron en el diario, incluidos los de ejecuciones anteriores con `--resume`.
  - Prueba nueva (`test_stop_summary_matches_diary`, en los modos «posix» y «windows», con ENOENT, WinError 21 y EIO) que compara el resumen con los eventos `done` del diario.

### Corregido (ajuste cosmético)
- La línea de progreso dejaba restos del nombre anterior (p. ej. «0:00:00Before).lrc») cuando el nuevo era más corto. No se reproduce en Linux, donde rich borra la línea antes de redibujarla; ocurre en consolas que no lo hacen. Ahora cada actualización ocupa el ancho completo de la terminal (rellena con espacios), no se parte en dos filas y muestra solo el nombre del archivo, recortado con «…» si no cabe.
- `revert` ya no muestra «Recuperando escrituras pendientes» si no hay nada pendiente.

### No probado
- `[Errno 22] Invalid argument`, que apareció al desconectar una SD real, sigue sin tratarse como desconexión. No se probó con nombres de archivo no válidos en FAT, que también pueden darlo.

### Agregado
- Comando `fix-gallery`: crea un `.nomedia` vacío en las carpetas de álbum para que las apps de galería no muestren las portadas. No abre ni modifica audio, letras ni etiquetas.
  - Simulación por defecto y `--apply`. Solo en carpetas con imágenes (jpg, jpeg, png, webp, bmp, gif, sin distinguir mayúsculas) y sin `.nomedia`; `--all-folders` lo pone en todas las carpetas con audio.
  - La carpeta indicada se omite si es una raíz (tiene subcarpetas con audio); si es un álbum, se trata como tal. `Music`, `Pictures`, `DCIM` y `Download` se omiten siempre. `--include-root` quita las dos protecciones.
  - `--remove` quita solo lo que creó la herramienta, según `ChoconostleLRCTool_back/fix-gallery_creados.json`. Nunca borra un `.nomedia` que ya existía ni uno con contenido. `clean-backups` no borra esa lista.
  - Idempotente, `--only`, rutas largas de Windows, código 3 si la unidad desaparece, barra «N de M» y resumen (revisadas, creadas, ya existentes, omitidas y con error).
  - **⚠️ Advertencia:** las apps que leen el índice de medios del sistema (MediaStore) dejan de listar las canciones de las carpetas con `.nomedia`. Prueba con tu app de música en un álbum antes de aplicarlo a toda la biblioteca.
- Banner de bienvenida con `choconostle` sin argumentos o `choconostle welcome`: nombre, versión y nombre clave (igual que `choconostle version`), descripción, comandos y consejo. Solo ASCII y 40 columnas como máximo. No aparece en los demás comandos ni si la salida no es una terminal; `--no-banner` y `CHOCONOSTLE_NO_BANNER` lo apagan.
- README: advertencia de hacer una copia antes de usar `--apply` y de ejecutar siempre primero la simulación.
- `tests/test_fix_gallery.py`, sobre copias de la biblioteca de `tools/generar_casos.py` con portadas añadidas (`cover.jpg`, `COVER.JPG`), en los modos «posix» y «windows».

### Cambiado
- Sin argumentos ya no se muestra la ayuda en una terminal interactiva, sino el banner (la ayuda sigue con `--help`, `--no-banner` o con la salida redirigida).
- Nombre del autor: «AndrewSkarlet» en `LICENSE` (línea de Copyright), `pyproject.toml`, `config.py`, las cabeceras del código y el README.
- `run.fatal_kind` acepta `backups=False` para no exigir la carpeta de respaldos (`fix-gallery` en simulación no la crea).

## v0.3.0 - Fase 2.1: normalización segura, conversión de letras y escalabilidad

Sube la versión menor por las incompatibilidades con la v0.2.0 (ver cada etapa). Los resultados de las pruebas en Windows y Android están en la descripción del PR. Lo que quedó sin hacer o sin probar está en `docs/PENDIENTES.md`.

### Mejoras pendientes (sin implementar)
- `revert` no muestra progreso y es más lento que `--apply` (14,5 s frente a 5,2 s con 28 archivos en una SD).
  - Mostrar el avance «N de M» con un indicador animado en `revert`, `--resume` y `clean-backups`.
  - Indicar el paso en curso en las fases largas de verificación.
  - Investigar por qué `revert` tarda más.
- `tests/test_memoria.py` tarda entre 45 y 57 s en Windows; se pidieron unos 30 s.
- Tras una desconexión real, el resumen del paro mostró «Aplicadas 0 / Sin aplicar 42», aunque el error ocurrió en el 8.º FLAC de 21. Investigar si el resumen de reserva subcuenta lo confirmado en el diario.
- El error real al desconectar fue `[Errno 22] Invalid argument`, que no estaba entre los simulados. Evaluar si debe reconocerse como posible desconexión.

### No probado
- Tarjeta SD desde el teléfono, bibliotecas grandes en el teléfono, `convert-lyrics` en Termux y uso de CPU y batería.
- NAS y ARM, y charset-normalizer en Python puro fuera de Linux x86.
- Disco lleno real (solo simulado) y el editor ID3 con MP3 reales con cabeceras.
- `tools/medir_rendimiento.py` en Windows y en una SD.

### Etapa 7: documentación y PR
- `.gitignore` excluye `ChoconostleLRCTool_back/` y las bibliotecas de prueba generadas.
- Versión 0.3.0.

### Etapa 6: memoria y tiempo

#### Agregado
- `tools/medir_rendimiento.py`:
  - mide el pico de memoria, el tiempo, los recuentos y el tamaño del respaldo de cada comando con bibliotecas de tamaño creciente, hechas con `tools/generar_casos.py`;
  - `--destino` elige dónde crear las carpetas de medición;
  - `--ruta-real` mide sobre una copia limitada de una carpeta real sin modificar el original.
- `docs/RENDIMIENTO.md`: resultados antes y después con 230, 2 300, 6 900 y 13 800 archivos.
- `tests/test_memoria.py`: regresión de memoria con `tracemalloc` (×1 frente a ×20).

#### Corregido
- Los eventos del diario se cargaban enteros en memoria (unos 2 KB por entrada) en `revert`, `--resume`, el reporte de `--apply` y `clean-backups`. Ahora se guarda solo su posición en `diario.jsonl` y se leen al pedirlos (unos 185 B por entrada).
- Los resultados de `revert` guardaban la letra original hasta terminar. Ahora solo guardan id, tipo, ruta y etiqueta.
- Con 13 800 archivos, el pico de `revert` baja de 81,5 MB a 70,1 MB. El crecimiento baja de 1 284 a 420 bytes por archivo.

#### Limitaciones medidas
- `revert` sigue creciendo unos 420 bytes por archivo y `scan` unos 1,3 KB por archivo. `scan` queda fuera de las correcciones de esta fase.

### Etapa 5: pruebas de robustez

#### Agregado
- `tests/COBERTURA.md`: tabla de qué prueba cubre cada situación de riesgo para `normalize-lyrics`, `convert-lyrics`, `revert` y `clean-backups`.
- `tests/test_robustez.py`: lo que faltaba de la tabla, todo en los modos «posix» y «windows»:
  - `convert-lyrics`: corte en cada paso del diario y a mitad de escritura, WinError 3 y 5, espacio antes y a mitad, archivos modificados, `--resume` con respaldo incompleto o ajeno;
  - `revert`: interrupción, desconexión (EIO, 1167, 3), acceso denegado, espacio (antes, ENOSPC, WinError 112), conflictos, respaldo incompleto;
  - `clean-backups`: desconexión, acceso denegado e interrupción;
  - WinError 112 a mitad de ejecución en los dos comandos.
- Fixture `paths_mode`: las pruebas de la etapa ③ que se ejecutaban en un solo modo ahora se ejecutan en los dos.

#### Corregido
- `revert` ante una desconexión o falta de espacio: antes marcaba cada archivo como error y seguía con todos los demás. Ahora:
  - comprueba el espacio antes de empezar (código 2);
  - se detiene en el primer error fatal (código 3) con el comando para repetirlo, que continúa donde quedó.
- `clean-backups`: el borrado ya no usa `shutil.rmtree`, que se comporta distinto en Linux y Windows y no capturaba errores. Ahora:
  - es reanudable (`<nombre>.borrando`);
  - se detiene ante una desconexión (código 3);
  - sigue con las demás carpetas ante un acceso denegado (código 1).

- Nombres de respaldo: una ejecución creada en el mismo segundo que un borrado interrumpido reutilizaba el nombre liberado, y luego su borrado chocaba con el `.borrando` anterior. Ahora no se reutiliza ese nombre y el borrado usa `.borrando-2`, `-3`… Lo detectó una prueba que fallaba de forma intermitente; ahora tiene una prueba determinista.

### Etapa 4: convert-lyrics

#### Agregado
- Comando `convert-lyrics`, con el mismo sistema de ejecución que `normalize-lyrics`: simulación, `--apply`, plan en disco, diario, respaldo, `--resume`, `revert`, verificación antes y después de escribir, `--verify` y `--allow-full-rewrite`.
  - `--to` (por defecto `utf8`, sin BOM) y `--eol lf|crlf|keep` (por defecto `lf`), solo para `.lrc`/`.txt`.
  - `--source-encoding` (solo para archivos de 8 bits) y `--prefer-encoding` (desempate entre candidatos de familias distintas, como cp1250 y cp1252).
  - `--replace-char DE=A` y `--replace-map ARCHIVO`: nunca tocan las marcas de tiempo; se registra cuántas sustituciones hizo cada regla. También se aplican a las letras incrustadas.
  - `--id3-encoding latin1|utf16|utf8`: recodifica solo los frames de letra ID3. `utf8` solo en ID3v2.4, y la versión del tag no cambia. `revert` restaura la codificación original byte a byte.
  - `--on-unencodable skip|error`: nunca se sustituye por `?`.
- El reporte indica, por archivo, la codificación de origen y si es fiable, y cuántos archivos de audio necesitarían reescritura completa, por formato.
- Pruebas con la biblioteca de casos y archivos creados con `generar_casos.py`. La desconexión y `--resume` se prueban en los modos «posix» y «windows».

#### Cambiado
- La ejecución (`run.py`), el reporte y la CLI son comunes a los dos comandos (`_execute`, `processor_for`). `--resume` comprueba que la ejecución sea del mismo comando.
- Con `--to` UTF-16 o UTF-32, el reporte y cada archivo afectado avisan de que casi ningún reproductor lee letras en esas codificaciones.
- Documentado: las sustituciones también se aplican a las cabeceras (decisión aprobada), y la lista de funciones adicionales no pedidas (`--to` con cualquier códec, `recover`, `tools/medir_verificacion.py`).

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
- Desconexión al escribir el diario, el registro, el estado o la copia de respaldo: antes, el error al anotar un fallo escapaba sin capturar (código 1). Ahora:
  - toda escritura del diario pasa por `_diary()` y cualquier error de la carpeta de respaldo detiene la ejecución con código 3 y el comando `--resume`;
  - si no se pudo escribir el `intent`, no se toca el archivo;
  - si no se pudo escribir el `done`, `--resume` resuelve la entrada a partir del último `intent` confirmado.
- `reachable()` usa `os.stat`: en Windows `os.path.isdir` es una función en C (`nt._path_isdir`) que no se comporta igual ante algunos errores.
- El diario termina una línea cortada antes de añadir otra, y al leerlo se ignoran las líneas dañadas.
- Pruebas de desconexión más estrictas:
  - en modo «posix» y «windows» (este último reproduce en Linux que `os.path.isdir/exists` no pasan por `os.stat`);
  - con la desconexión en una escritura de la biblioteca, de la copia de respaldo, del diario (`intent` y `done`) y del estado;
  - con EIO, WinError 1167 y WinError 3.
- `revert`: si no encuentra el respaldo, nombra `estado.json` (no `manifiesto.json`) y sugiere comprobar que la ruta esté en una sola línea. Con `--latest` acepta la carpeta de la biblioteca (o `ChoconostleLRCTool_back`) y usa el respaldo más reciente.

#### Pendientes cerrados de la etapa 3
- `--verify auto` (por defecto): `quick` para ediciones en su sitio o al final (el audio no se escribe) y `full` para reescrituras completas. `--verify full|quick` fuerza uno u otro.
- `--apply` con más de 50 entradas: la consola muestra el resumen, las entradas que fallaron o quedaron sin aplicar y la ruta de `registro.txt`, que siempre tiene la lista completa. `--limit 0` muestra todo.

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