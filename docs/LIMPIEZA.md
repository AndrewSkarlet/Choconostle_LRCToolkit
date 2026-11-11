# Reporte de limpieza (rc3.dev0)

Lista de código, archivos y scripts que **parecen** sin uso. **No se borró nada**: la decisión es del autor.

## Cómo se buscó

- Definiciones de primer nivel (funciones, clases y constantes en mayúsculas) y métodos de clase de `src/choconostle/` que no se usan en ningún otro punto del código. Se buscó el nombre como palabra completa en todo `src/`, y después en `tests/`, `tools/` y los documentos (`git grep`).
- Imports sin usar en cada módulo: no se encontró ninguno.
- No había linters instalados (pyflakes, ruff, vulture), así que la búsqueda se hizo con un script de `ast` y `re`. Puede haber falsos negativos, por ejemplo con nombres usados por `getattr` o en cadenas.
- Se descartaron los falsos positivos: las funciones de los comandos de `cli.py` (`normalize_lyrics`, `convert_lyrics`, `fix_gallery`, `_main`), que se registran con decoradores de Typer.

## Candidatos a borrar

| Elemento | Motivo | Lo mencionan |
|---|---|---|
| `src/choconostle/rename.py` | Archivo vacío (0 líneas). Reservado para el organizador de carpetas de la rc3. | `docs/PENDIENTES.md` («Fuera de la rc3.dev0»). No lo importa nadie. Conviene esperar al organizador: entonces se llena o se reemplaza. |
| `backup.BackupSession` (`backup.py`, unas 150 líneas: `__init__`, `add`, `add_edit`, `save_manifest`, `write_log`) | Creaba las carpetas de respaldo con `manifiesto.json` de la 0.3.0. Desde la ejecución en dos pasadas (`run.py`, etapa ③) los respaldos nuevos los crea `run.Run`. Ya no se usa en el código ni en las pruebas. | Ningún documento. **Ojo:** `revert` de respaldos `manifiesto.json` v1/v2 (`backup.revert`, `_revert_embedded`, `MANIFEST_NAME`, `ITEM_*`) **sí** se usa y hay que conservarlo. Las pruebas de respaldos antiguos (`tests/test_robustez.py`) escriben el manifiesto a mano. |
| `backup._safe_name`, `backup._relative`, `backup._jsonable` | Solo los usa `BackupSession`: quedarían sin uso si se borra. `run.py` y `albums.py` tienen sus propias versiones (`run._safe_name`, `albums._relative`, `run._jsonable`). | Ninguno. |
| `run.ResumeError` | Excepción definida y nunca lanzada ni capturada. `resume_check` devuelve una lista de problemas en vez de lanzarla. | Ningún documento ni prueba. |
| `normalizer.ENCODING_UTF8`, `normalizer.ENCODING_UTF8_BOM` | Constantes sin uso. Los valores `utf8` y `utf8-bom` de `--encoding` los interpreta `textio.parse_target_encoding`. | Ninguno. Los textos de ayuda y el README escriben los valores literales. |
| `textio._EOL_BYTES_RE` | Expresión regular sin uso (`_EOL_RE`, la de texto, sí se usa). | Ninguno. |
| `textio.join_lines` | Solo la usa una prueba. | `tests/test_textio.py` (`test_split_lines_keeps_delimiters`). Si se borra, hay que ajustar esa prueba. |
| `report.skipped_by_reason` | El reporte lee los motivos de omisión del plan en disco (`totals["skip_reasons"]`). Esta función, que trabaja con la lista de cambios en memoria, solo la usan las pruebas. | `tests/test_rawtags.py` (dos aserciones). Si se borra, hay que reescribir esas aserciones con `totals["skip_reasons"]`. |

## Conservar aunque parezcan viejos o sin uso

| Elemento | Por qué conservarlo |
|---|---|
| `src/choconostle/legacy_embedded.py` | Edición con mutagen de la v0.2.0. `backup.py` la importa (`EmbeddedLyrics`, `EmbeddedError`) para **revertir respaldos de la 0.2.0**, que guardaban la letra entera en vez de parches byte a byte. Sin este módulo, esos respaldos no se podrían deshacer. Lo menciona `README.md` (Estructura). |
| Lectura de `manifiesto.json` en `backup.py` (`revert`, `_revert_embedded`, `recover_session`, `MANIFEST_NAME`, `ITEM_*`) | Revierte y recupera respaldos de la 0.2.0 y la 0.3.0; `clean-backups` los clasifica (`run.py`, «v1»/«v2»). Lo cubren `tests/test_robustez.py` y `tests/test_rawtags.py`. |
| `run.Run.manifest` (propiedad «compatibilidad») | Vista tipo manifiesto de una ejecución nueva. La usan `normalizer.apply` y las pruebas (`session.manifest[...]` en `tests/test_rawtags.py` y otras). |
| `config.APP_AUTHOR`, `config.APP_LICENSE` | Sin uso en el código, pero son metadatos del programa junto a `APP_NAME` y `APP_VERSION`. Cuestan dos líneas. |
| `matroska._FILE_NAME` (`0x466E`) | Identificador EBML documentado junto a los demás (`_ATTACHED_FILE`...). Sirve de referencia del formato aunque hoy no se lea el nombre del adjunto. Se puede borrar sin efecto, pero ayuda a leer el módulo. |
| `tools/generar_casos.py` y `tools/CASOS.md` | Generan la biblioteca de casos que usan `tests/conftest.py`, `tests/test_casos_generados.py`, `tests/test_huella.py`, `tests/test_memoria.py` y `tools/medir_rendimiento.py`. Imprescindibles. |
| `tools/medir_rendimiento.py` | Mediciones de memoria y tiempo. Lo citan `README.md`, `docs/RENDIMIENTO.md` y `docs/PENDIENTES.md` (pendiente de medir en Windows y en una SD). |
| `tools/medir_verificacion.py` | Origen de la tabla de `--verify full` frente a `quick` en `README.md`. |
| `tests/COBERTURA.md`, `docs/RENDIMIENTO.md` | Documentación de las pruebas y de las mediciones. |

## Archivos generados (no están en git)

`git status --ignored` muestra `__pycache__/` (en `src/`, `tests/` y `tools/`), `.pytest_cache/` y `src/choconostle_lrctoolkit.egg-info/`. Están en `.gitignore` y no se suben. Se pueden borrar en local sin efecto; el `egg-info` se regenera con `pip install -e .`.
