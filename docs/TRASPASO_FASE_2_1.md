# Traspaso — Fase 2.1 (normalización segura, conversión de letras y escalabilidad)

Este documento sirve para que una sesión nueva continúe la Fase 2.1 sin ayuda del usuario. Léelo entero antes de tocar código y responde siempre en español.

- **Rama:** `claude/adoring-cerf-o8xdvp`, creada desde `master` después de fusionar el PR #2. Todo se sube a esta rama.
- **PR:** todavía no existe. Se abre en la etapa ⑦ como PR independiente, **sin fusionarlo**.
- **Estado:** etapas ① a ⑤ aprobadas por el usuario. La siguiente es la ⑥, que **no se ha empezado**.

## 1. Estado de las etapas

| Etapa | Contenido | Estado | Commits |
|---|---|---|---|
| ① | `normalize-lyrics` conserva los bytes: no convierte a UTF-8 ni a LF, no quita el BOM y no añade salto final. Detección de codificación con charset-normalizer. `--strip-unknown-headers` solo actúa sobre el bloque inicial. | Aprobada | `2705f1f`, `f26651f` (detección estable entre versiones) |
| ② | Letras incrustadas editadas byte a byte (paquete `rawtags`): ID3v2.3/2.4, FLAC, MP4/M4A y APEv2. Diario `pendiente/` y comando `recover`. | Aprobada | `2464ee4` |
| ③ | Ejecución en dos pasadas con plan en disco, `--resume`, comprobación de espacio, desconexión de la SD, rutas largas de Windows, `clean-backups`, `--verify auto` y resumen de `--apply` con más de 50 entradas. | Aprobada | `201da60`, `1940930`, `829dece`, `adced00` |
| ④ | Comando `convert-lyrics` (`--to`, `--eol`, `--source-encoding`, `--prefer-encoding`, `--replace-char`, `--id3-encoding`, `--on-unencodable`), aviso para UTF-16/UTF-32 y decisiones documentadas. | Aprobada | `7b5415f`, `e4f33a5` |
| ⑤ | Pruebas de robustez en los modos `posix` y `windows`. Correcciones de `revert` y `clean-backups`, y de la colisión de nombres `.borrando`. | Aprobada | `1c40a32` |
| ⑥ | Medición de memoria y tiempo. | **Pendiente** | — |
| ⑦ | Documentación final y PR sin fusionar. | **Pendiente** | — |

Al aprobar la ⑤, la suite tenía 453 pruebas y pasaba 3 de 3 veces en Linux.

Los detalles de cada etapa están en `CHANGELOG.md`, que incluye la lista de incompatibilidades con la v0.2.0, y en `README.md`.

## 2. Decisiones de diseño y por qué

### `normalize-lyrics --encoding keep` por defecto
- El requisito original es no tocar nada que no sea lo que se pide quitar.
- Por eso `keep` conserva la codificación, el BOM y los finales de línea (CRLF, CR o mezclados), y no añade un salto final.
- También acepta `utf8` (sin BOM), `utf8-bom` y cualquier códec de Python. Si algún carácter no cabe en el destino, el archivo se omite y se lista; nunca se sustituye por `?`.
- Cambiar el valor por defecto de `utf8` a `keep` es una incompatibilidad con la v0.2.0 y figura en el CHANGELOG.
- La conversión explícita es trabajo de `convert-lyrics`. Sus valores por defecto son `--to utf8` (sin BOM) y `--eol lf`.
- En los archivos de 8 bits, las cabeceras y las marcas se procesan byte a byte, porque son ASCII. Quitar cabeceras no depende de que la detección de codificación sea segura.

### Offsets inválidos o duplicados: se omiten
- Regla general: si un `[offset:]` no se puede aplicar con seguridad, no se toca ni la cabecera ni las marcas de ese archivo. El archivo se lista en «Desconocidos / requieren decisión».
- **Dos o más** `[offset:]`: se omiten con `--offset-policy skip`, que es el valor por defecto. `first`, `last` o `sum` lo resuelven; `sum` es la política recomendada.
- **Offset inválido** (por ejemplo, `[offset:medio segundo]`): se omite siempre, con cualquier política, porque no hay forma de adivinar su valor.
- Un único offset válido se aplica a las marcas de línea y a las de palabra antes de quitarlo. Es el único caso en que cambian líneas de letra.
- Un archivo que quedaría vacío (solo tenía cabeceras) no se escribe y se avisa.

### `--verify auto`
- `auto` es el valor por defecto:
  - usa `quick` para ediciones en su sitio o al final del archivo, porque el audio no se escribe;
  - usa `full` (hash del audio completo) para las reescrituras completas.
- `--verify full|quick` fuerza uno de los dos modos.
- En todos los casos se relee el archivo y se comparan, byte a byte, la región editada y las etiquetas ajenas a la letra. Si algo no coincide, se restaura el original con su fecha de modificación.

### Ogg/Opus omitidos salvo con `--allow-full-rewrite`
- En Ogg el comentario va en las primeras páginas. Cambiar su tamaño obliga a renumerar todas las páginas, así que no existe una edición en su sitio.
- Lo mismo pasa con cualquier formato en el que la letra no quepa en el relleno.
- Esos archivos se omiten por defecto y `--diff` indica «reescritura completa, requiere X libres».
- Con `--allow-full-rewrite`, el archivo se escribe en una copia temporal junto al original, se verifica y se reemplaza de forma atómica.

### Rutas y comandos copiables sin saltos
- Las rutas largas (Windows, más de 260 caracteres) se partían en la consola y no se podían copiar.
- `report.print_copyable` (Rich con `soft_wrap`) imprime rutas y comandos («Para deshacer», «Vuelve a ejecutar», la ruta de `registro.txt`) en una sola línea lógica.

### Las sustituciones también tocan las cabeceras
- `--replace-char` se aplica a todo el texto, cabeceras incluidas, pero no dentro de las marcas de tiempo.
- El usuario decidió dejarlo así y documentarlo en el README (etapa ④).

### Avisos para UTF-16 y UTF-32
- Si `--to` es UTF-16 o UTF-32, el aviso aparece en el encabezado del reporte y en cada archivo afectado, y recomienda UTF-8.
- El motivo es que muchos reproductores, Poweramp entre ellos, no leen letras en esas codificaciones.

### `revert` y `clean-backups` se detienen ante una desconexión o falta de espacio
- Un error de dispositivo (EIO, o WinError 15, 21, 55, 121, 483, 1117, 1128, 1167, 3 con la letra de unidad desaparecida) o la falta de espacio (ENOSPC, WinError 39 y 112) detienen la ejecución con **código 3**.
  - Se muestra «Vuelve a ejecutar» con el comando listo para copiar.
  - Al repetirlo, sigue donde quedó.
- `revert` comprueba el espacio antes de empezar. Si no alcanza, sale con **código 2** sin tocar nada.
- **WinError 5 (acceso denegado) no es una desconexión:** solo falla ese archivo o esa carpeta, la ejecución sigue y el código de salida es **1**.
- `clean-backups` renombra cada carpeta a `<nombre>.borrando` y la borra archivo por archivo con rutas completas. Un borrado interrumpido se termina en la ejecución siguiente.
  - Se dejó de usar `shutil.rmtree` porque se comporta distinto en Linux y en Windows.
- `Run.create` no reutiliza un nombre que tenga un `.borrando` pendiente, y el borrado usa `.borrando-2`, `-3`… si hace falta.
- `normalize-lyrics` y `convert-lyrics` hacen lo mismo con `--apply`: código 3 y `--resume`.

### Otras decisiones tomadas por el usuario
- `--to` y `--eol` no tocan las letras incrustadas, que solo cambian con `--replace-char`. Está documentado.
- Funciones no pedidas que se mantienen y están documentadas: `--to` con cualquier códec de Python, el comando `recover` y `tools/medir_verificacion.py`.
- `--prefer-encoding` solo desempata entre candidatos empatados; nunca cambia una detección segura.

## 3. Pruebas en Windows y hallazgos

Equipo del usuario: Windows, Python 3.15.1 y charset-normalizer 3.5.2 (rueda compilada).

| Momento | Resultado | Hallazgo y solución |
|---|---|---|
| Etapa ① | 148 de 149 | **EUC-KR:** charset-normalizer 3.5.2 devuelve `cp949` (caos 0.0) y `euc_jis_2004` (caos 0.1); la 3.5.1 daba 0.15. El margen de empate de 0.1 incluía el límite, así que el archivo salía como «aproximado». **Solución:** un empate exige diferencia < 0.05 y las codificaciones compatibles (`euc_kr`/`cp949`, `shift_jis`/`cp932`, `gbk`/`gb18030`) se agrupan en familias. Hay pruebas con los valores de las dos versiones y una prueba con charset-normalizer en Python puro (sin `.so`/`.pyd`), necesaria para Termux. |
| Etapa ② | 19 M4A reales con portada | Audio y etiquetas ajenas intactos; `revert` idéntico byte a byte. |
| Etapa ③ (primera prueba) | 224 de 225 | La prueba simulaba la desconexión con `os.rename` de la biblioteca, y en Windows eso da **WinError 5** porque la carpeta está en uso. **Solución:** simulador `Unplug` portable. Se añadieron los códigos de dispositivo de Windows. **WinError 5 no es desconexión:** es un fallo de ese archivo. |
| Etapa ③ (rutas largas) | Ruta de 584 caracteres | Aplicar, respaldar y revertir funcionaban, pero las rutas se partían en la consola. **Solución:** `print_copyable`. |
| Etapa ③ (`1940930`) | 237 de 240 | Dos causas de fallo. Primera: en Windows, `os.path.isdir` y `os.path.exists` son funciones en C (`nt._path_isdir`) que **no pasan por `os.stat`**, así que la desconexión simulada no se veía. Segunda: escribir el diario o el respaldo podía dejar escapar el `OSError`. **Solución:** `run.reachable()` usa `os.stat`; `_diary()` protege la escritura; las pruebas se ejecutan en los modos `posix` y `windows` (fixture `paths_mode` y parámetro `paths` de `Unplug`). |
| Etapa ③ (`829dece`) | 274 de 274 | Ciclo con 67 FLAC reales (apply, verificación de audio y etiquetas, `revert --latest`): **comparación byte a byte con 0 diferencias**. Rutas largas de 580 caracteres y `revert` idempotente correctos. |
| Etapa ④ | Bien | Sin hallazgos nuevos. |
| Etapa ⑤ (`1c40a32`) | Ver la nota | `clean-backups --older-than 0` sobre una carpeta de prueba. |

**Nota sobre la etapa ⑤:** el mensaje de aprobación decía «453 de 453 pruebas pasan; `clean-backups` con `--older-than 0` sobre una carpeta de prueba borró los respaldos sin dejar `.borrando`», seguido de «(ajusta al resultado real)». Parece una plantilla. Hay que confirmar con el usuario el resultado exacto en Windows antes de citarlo en el PR.

## 4. Pendientes

### Etapa ⑥: medición de memoria y tiempo
Requisitos del usuario (sección 7 de la especificación):
- La biblioteca real tiene 234 GB en una SD externa y el equipo tiene 16 GB de RAM.
- Generar bibliotecas sintéticas de tamaño creciente, con miles de archivos y distintos tamaños de letras y etiquetas.
- Medir:
  - el pico de memoria;
  - el tiempo total y por archivo;
  - los archivos escaneados, planificados, modificados y omitidos;
  - el crecimiento de la memoria con el número de archivos.
- No declarar que el consumo es constante sin resultados que lo demuestren.
- Identificar las estructuras que acumulan datos en memoria y corregir los cuellos de botella.
- Las mediciones se hacen en carpetas temporales generadas. **Nunca** sobre la biblioteca real.
- Si `tools/generar_casos.py` no sirve para generar miles de archivos, **hay que preguntar al usuario** antes de crear otra herramienta. Lo mismo vale para cualquier otro archivo que falte en el repositorio.

Cuello de botella ya conocido: la tabla de resultados por entrada (un diccionario de identificadores) que se arma al reanudar, al revertir y al mostrar el reporte sigue creciendo con la biblioteca. Está anotado en la sección «Pendiente» del CHANGELOG.

El escaneo (`scanner.iter_folders`) y la planificación (`plan.jsonl` en disco) ya son incrementales, pero no se han medido.

### Etapa ⑦: documentación final y PR
- Repasar `README.md` y `CHANGELOG.md`: comandos, valores por defecto, limitaciones, incompatibilidades con la v0.2.0 y los resultados de la ⑥.
- Abrir un PR independiente desde `claude/adoring-cerf-o8xdvp` hacia `master`, **sin fusionarlo**. Antes, buscar una plantilla de PR en el repositorio.

### Ideas anotadas (sin implementar)
- Detectar «letras de relleno», por ejemplo letras que solo contienen URLs repetidas, publicidad o créditos de la web de origen. Por ahora solo es una idea; no forma parte de ninguna etapa aprobada.

## 5. Cómo ejecutar las pruebas

Requisitos: Python 3.9 o posterior y `ffmpeg` en el PATH.

```bash
pip install -e ".[dev]"
pytest                    # suite completa
pytest tests/test_robustez.py -q
```

- `tests/conftest.py` genera la biblioteca de casos una vez por sesión, en una carpeta temporal, con `tools/generar_casos.py` (fixture `casos`). Cada prueba que modifica archivos trabaja sobre una copia (fixture `biblioteca`). Sin `ffmpeg`, esas pruebas se omiten.
- La fixture `paths_mode` y el simulador `Unplug` (`tests/test_run.py`) ejecutan cada prueba de desconexión en los modos `posix` y `windows`.
- **Las pruebas solo usan `tools/generar_casos.py` y sus instrucciones.** Del generador solo se corrigió el caso «13 ASCII puro» (todo ASCII, cabeceras incluidas), con permiso del usuario. No se reescribe por cuenta propia.

Para generar la biblioteca a mano (en una carpeta temporal, nunca dentro de la biblioteca real):

```bash
python tools/generar_casos.py /tmp/Choconostle_Casos_LRC
```

- `tools/CASOS.md` describe cada caso y lo que se espera de él.
- `tools/medir_verificacion.py` mide el coste de `--verify quick` frente a `full`.
- **Cobertura de robustez:** `tests/COBERTURA.md` tiene la tabla de escenarios (interrupción, desconexión, espacio, archivos modificados, `--resume`) para los cuatro comandos que escriben, con el nombre de cada prueba.

## 6. Reglas de trabajo con el usuario

1. Trabajar por etapas. Al terminar cada una, **parar, mostrar los resultados y esperar la aprobación** antes de empezar la siguiente. Si el usuario pide ver un plan o una tabla antes de implementar, mostrarlos y esperar.
2. **Un commit por etapa**, más los commits de ajustes que pida el usuario dentro de la misma etapa. Subir a `claude/adoring-cerf-o8xdvp`.
3. **No tocar nunca la biblioteca musical real.** Todas las pruebas se hacen sobre copias o bibliotecas generadas en carpetas temporales.
4. No presentar funciones como implementadas ni pruebas como aprobadas si no se ejecutaron y verificaron. Informar de los fallos con su salida.
5. Si falta algo en el repositorio (una herramienta o unos casos), avisar al usuario y pedírselo en lugar de reescribirlo.
6. Dependencias nuevas: solo Python puro, que funcione en Windows, Linux y Termux.
7. Explicar todo en español.
8. No abrir el PR hasta la etapa ⑦ y no fusionarlo nunca de forma automática.
