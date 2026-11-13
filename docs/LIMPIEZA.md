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
| `backup.BackupSession` (unas 150 líneas: `__init__`, `add`, `add_edit`, `save_manifest`, `write_log`) | Creaba los respaldos con `manifiesto.json` de la 0.3.0; desde la ejecución en dos pasadas los crea `run.Run`. La **lectura** de `manifiesto.json` (revert, recover, clean-backups) se conserva. |
| `backup._safe_name`, `backup._relative`, `backup._jsonable` | Solo los usaba `BackupSession`. `run.py` y `albums.py` tienen sus propias versiones. |
| `backup.MANIFEST_VERSION`, `backup.ITEM_PENDING`, `backup._UNSAFE_NAME_RE`, `backup._diff` y los imports `re`, `diff_lines` y `patches_to_json` de `backup.py` | Solo los usaba `BackupSession` (o las funciones de arriba): quedaron sin uso al borrarla. Los manifiestos antiguos se siguen leyendo igual (`manifest_version`, `ITEM_APPLIED` e `ITEM_FAILED` siguen). |
| `run.ResumeError` | Nunca se lanzaba ni se capturaba: `resume_check` devuelve una lista de problemas. |
| `normalizer.ENCODING_UTF8`, `normalizer.ENCODING_UTF8_BOM` | Sin uso: los valores de `--encoding` los interpreta `textio.parse_target_encoding`. |
| `textio._EOL_BYTES_RE` | Sin uso (la versión de texto, `_EOL_RE`, sí se usa). |

## Parecía sin uso, pero se conserva

| Elemento | Por qué |
|---|---|
| `textio.join_lines` | Solo la usa `tests/test_textio.py` (`test_split_lines_keeps_delimiters`). Se conserva por decisión del autor. |
| `report.skipped_by_reason` | Solo la usa `tests/test_rawtags.py` (dos aserciones). Se conserva por decisión del autor. |

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
