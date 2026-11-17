# Reporte de limpieza (rc3.dev0)

Código, archivos y scripts que parecían sin uso. El autor decidió qué se borra; lo borrado está en «Borrado» y lo que se decidió conservar, en las dos secciones siguientes.

## Cómo se buscó

- Definiciones de primer nivel (funciones, clases y constantes en mayúsculas) y métodos de clase de `src/choconostle/` que no se usan en ningún otro punto del código. Se buscó el nombre como palabra completa en todo `src/`, y después en `tests/`, `tools/` y los documentos (`git grep`).
- Imports sin usar en cada módulo: no se encontró ninguno (tampoco después del borrado).
- No había linters instalados (pyflakes, ruff, vulture), así que la búsqueda se hizo con un script de `ast` y `re`. Puede haber falsos negativos, por ejemplo con nombres usados por `getattr` o en cadenas.
- Se descartaron los falsos positivos: las funciones de los comandos de `cli.py` (`normalize_lyrics`, `convert_lyrics`, `fix_gallery`, `_main`), que se registran con decoradores de Typer.

## Borrado (rc3.dev0)

| Elemento | Motivo |
|---|---|
| `src/choconostle/rename.py` | Archivo vacío. El organizador de carpetas de la rc3 tendrá su propio módulo. No se mencionaba en `README.md` ni en `README.en.md` (solo en `docs/PENDIENTES.md`, actualizado). |
| `backup.BackupSession` (unas 150 líneas: `__init__`, `add`, `add_edit`, `save_manifest`, `write_log`) | Creaba los respaldos con `manifiesto.json` durante el desarrollo de la 0.3.0; desde la ejecución en dos pasadas los crea `run.Run`. |
| `backup._safe_name`, `backup._relative`, `backup._jsonable` | Solo los usaba `BackupSession`. `run.py` y `albums.py` tienen sus propias versiones. |
| `backup.MANIFEST_VERSION`, `backup.ITEM_PENDING`, `backup._UNSAFE_NAME_RE`, `backup._diff` y los imports `re`, `diff_lines` y `patches_to_json` de `backup.py` | Solo los usaba `BackupSession` (o las funciones de arriba): quedaron sin uso al borrarla. `ITEM_APPLIED` e `ITEM_FAILED` siguen (los usan `revert_run` y `Run.manifest`). |
| `run.ResumeError` | Nunca se lanzaba ni se capturaba: `resume_check` devuelve una lista de problemas. |
| `normalizer.ENCODING_UTF8`, `normalizer.ENCODING_UTF8_BOM` | Sin uso: los valores de `--encoding` los interpreta `textio.parse_target_encoding`. |
| `textio._EOL_BYTES_RE` | Sin uso (la versión de texto, `_EOL_RE`, sí se usa). |

## Borrado: soporte de versiones no públicas (rc3.dev0)

Las versiones anteriores a la 0.3.0 nunca fueron públicas. `manifiesto.json` v1 lo escribía la 0.2.0 y la v2 solo existió durante el desarrollo de la 0.3.0; desde la 0.3.0 final (y en las públicas 1.0.0rc1 y 1.0.0rc2) los respaldos usan el formato 3 (`estado.json`, `plan.jsonl`, `diario.jsonl`), que se sigue leyendo entero, igual que `--resume` de planes de la rc1 sin huella del audio.

| Elemento | Motivo |
|---|---|
| `src/choconostle/legacy_embedded.py` (222 líneas) | Edición con mutagen de la 0.2.0; solo servía para revertir sus respaldos. |
| En `backup.py`: la rama de `revert` y de `recover_session` que leía `manifiesto.json`, `_revert_embedded`, `_library_root`, `MANIFEST_NAME`, la lectura de manifiestos en `load_manifest`, `is_backup_folder` y `backup_date`, y los imports `recover`, `RECOVERED_COMPLETE` y `RECOVERED_FAILED` | Solo servían a los manifiestos v1 y v2. `revert`, `recover` y `load_manifest` aceptan ahora solo carpetas con `estado.json`; con otra carpeta responden «No se encontró estado.json». |
| En `run.py`: la clasificación «v1/v2» de `clean-backups` | Una carpeta con `manifiesto.json` pasa a ser **no reconocida**: `clean-backups` la lista con su ruta y una nota para borrarla a mano, y nunca la borra (`run.UNRECOGNIZED`). |
| Mensaje «(ni manifiesto.json de versiones anteriores)» de `revert` | Ya no se buscan manifiestos. |
| Pruebas | `tests/test_run.py` y `tests/test_robustez.py` ya no esperan que se borren carpetas con manifiesto; `tests/test_no_reconocidas.py` (nueva) comprueba que se listan, que nunca se borran y que `revert`/`recover` las rechazan. |

Se conserva: `_revert_file`, `_revert_edit` y `_revert_ogg` (los usa `revert_run`), `ITEM_APPLIED`/`ITEM_FAILED`, `Run.manifest` (vista del formato 3 que usan `normalizer.apply` y las pruebas), `load_manifest` (la usan las pruebas), el diario `pendiente/` y `recover`.

## Parecía sin uso, pero se conserva

| Elemento | Por qué |
|---|---|
| `textio.join_lines` | Solo la usa `tests/test_textio.py` (`test_split_lines_keeps_delimiters`). Se conserva por decisión del autor. |
| `report.skipped_by_reason` | Solo la usa `tests/test_rawtags.py` (dos aserciones). Se conserva por decisión del autor. |

## Conservar aunque parezcan viejos o sin uso

| Elemento | Por qué conservarlo |
|---|---|
| `run.Run.manifest` | Vista resumida de una ejecución de formato 3 (no lee manifiestos antiguos). La usan `normalizer.apply` y las pruebas (`session.manifest[...]` en `tests/test_rawtags.py` y otras). |
| `config.APP_AUTHOR`, `config.APP_LICENSE` | Sin uso en el código, pero son metadatos del programa junto a `APP_NAME` y `APP_VERSION`. Cuestan dos líneas. |
| `matroska._FILE_NAME` (`0x466E`) | Identificador EBML documentado junto a los demás (`_ATTACHED_FILE`...). Sirve de referencia del formato aunque hoy no se lea el nombre del adjunto. Se puede borrar sin efecto, pero ayuda a leer el módulo. |
| `tools/generar_casos.py` y `tools/CASOS.md` | Generan la biblioteca de casos que usan `tests/conftest.py`, `tests/test_casos_generados.py`, `tests/test_huella.py`, `tests/test_memoria.py` y `tools/medir_rendimiento.py`. Imprescindibles. |
| `tools/medir_rendimiento.py` | Mediciones de memoria y tiempo. Lo citan `README.md`, `docs/RENDIMIENTO.md` y `docs/PENDIENTES.md` (pendiente de medir en Windows y en una SD). |
| `tools/medir_verificacion.py` | Origen de la tabla de `--verify full` frente a `quick` en `README.md`. |
| `tests/COBERTURA.md`, `docs/RENDIMIENTO.md` | Documentación de las pruebas y de las mediciones. |

## Archivos generados (no están en git)

`git status --ignored` muestra `__pycache__/` (en `src/`, `tests/` y `tools/`), `.pytest_cache/` y `src/choconostle_lrctoolkit.egg-info/`. Están en `.gitignore` y no se suben. Se pueden borrar en local sin efecto; el `egg-info` se regenera con `pip install -e .`.
