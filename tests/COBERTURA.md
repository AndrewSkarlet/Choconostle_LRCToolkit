# Cobertura de robustez (etapa ⑤)

Pruebas de interrupción, desconexión, falta de espacio, archivos modificados y `--resume`, para los cuatro comandos que escriben o borran. Todas usan la biblioteca de `tools/generar_casos.py` (fixture `casos` de `conftest.py`) o archivos creados con sus funciones.

Todas las de esta tabla se ejecutan en los **dos modos de rutas**:
- **posix:** `os.path.isdir` y `exists` pasan por `os.stat`, como en Linux.
- **windows:** no pasan por `os.stat`, como `nt._path_isdir` en Windows.

El modo se elige con la fixture `paths_mode` o con el parámetro `paths` del simulador `Unplug`. Así la prueba da lo mismo en Linux y en Windows.

Leyenda: **✔** cubierto en los dos modos (con el número de casos) · **+** añadido en la etapa ⑤ · **↑** existía en un solo modo y ahora se ejecuta en los dos · **n/a** no aplica.

| Escenario | normalize-lyrics | convert-lyrics | revert | clean-backups |
|---|---|---|---|---|
| Corte en cada paso del diario (inicio, copia, intent, escrito, done) | ✔↑ 50 `test_crash_at_each_step_then_resume` | ✔+ 40 `test_convert_crash_at_each_step` | ✔+ 6 `test_revert_interrupted_then_rerun` | ✔+ `test_clean_backups_access_denied_and_crash` |
| Corte a mitad de una escritura de bytes | ✔↑ 6 `test_crash_mid_byte_write_then_resume`, 8 `test_crash_mid_write_then_recover` | ✔+ 6 `test_convert_crash_mid_byte_write` | ✔+ (incluido arriba: MP3 y FLAC) | n/a (no escribe) |
| Desconexión EIO | ✔ 4 `test_device_disconnected_then_resume`, 30 `test_disconnection_while_writing_backup_or_diary` | ✔ 8 `test_disconnection_then_resume` | ✔+ 6 `test_revert_disconnection_then_rerun` | ✔+ 6 `test_clean_backups_disconnection_then_rerun` |
| Desconexión WinError 1167 | ✔ (mismas pruebas) y 16 `test_windows_device_errors_stop_the_run` (8 códigos) | ✔ (misma prueba) | ✔+ (misma prueba) | ✔+ (misma prueba) |
| Desconexión WinError 3 (letra de unidad) | ✔ 2 `test_drive_letter_disappears` | ✔+ 2 `test_convert_drive_letter_disappears` | ✔+ (en `test_revert_disconnection_then_rerun`) | ✔+ (en `test_clean_backups_disconnection_then_rerun`) |
| WinError 5 (acceso denegado: fallo de ese archivo, no desconexión) | ✔↑ 2 `test_access_denied_is_not_a_disconnection` | ✔+ 2 `test_convert_access_denied_is_not_a_disconnection` | ✔+ 2 `test_revert_access_denied_only_fails_that_file` | ✔+ (en `test_clean_backups_access_denied_and_crash`) |
| Sin espacio antes de empezar | ✔↑ 2 `test_not_enough_space_before_applying` | ✔+ 2 `test_convert_no_space_before_applying` | ✔+ (en `test_revert_space`) | n/a (libera espacio) |
| Sin espacio a mitad: ENOSPC | ✔↑ 2+2 `test_disk_full_*`, ✔+ `test_space_runs_out_mid_run` | ✔+ `test_space_runs_out_mid_run` | ✔+ 4 `test_revert_space` | n/a |
| Sin espacio a mitad: WinError 112 | ✔+ 8 `test_space_runs_out_mid_run` (ambos comandos, en un .lrc y en un FLAC) | ✔+ (misma prueba) | ✔+ (en `test_revert_space`) | n/a |
| Archivo modificado entre planificación y aplicación | ✔↑ 2 `test_files_modified_between_plan_and_apply` | ✔+ 2 `test_convert_files_modified_between_plan_and_apply` | ✔↑+ conflicto: 2 `test_revert_conflict_when_tags_changed`, 2 `test_revert_conflict_after_convert` | n/a |
| `--resume` / revert con respaldo incompleto | ✔↑ 2 `test_resume_refuses_missing_backup_copy`, 2 `test_resume_refuses_file_changed_after_interrupted_write`, 2 `test_resume_refuses_applied_file_changed_later` | ✔+ 2 `test_convert_resume_refuses_incomplete_or_foreign_backup` | ✔+ 2 `test_revert_with_incomplete_backup` | ✔↑ 2 `test_clean_backups_never_touches_incomplete_runs` |
| `--resume` con respaldo de otra biblioteca, ya completado o de otro comando | ✔↑ 2 `test_resume_refuses_completed_or_unfinished_plan` | ✔+ (misma prueba de convert) y 8 `test_disconnection_then_resume` (otro comando) | n/a (revert usa la carpeta del respaldo) | n/a |

## Cambios en la herramienta que salieron de estas pruebas

Con el código anterior fallaban 18 de las pruebas nuevas:

- **`revert`**
  - Antes, ante una desconexión o falta de espacio, marcaba cada archivo como ERROR y seguía con todos los demás.
  - Ahora comprueba el espacio antes de empezar («Espacio libre insuficiente para revertir», código 2) y se detiene en el primer error fatal (código 3) con «Vuelve a ejecutar» y el comando para copiar.
  - Lo restaurado hasta ahí cuenta como «ya estaba como el original» al repetirlo.
  - Un acceso denegado o una copia de respaldo que falta solo afectan a ese archivo (código 1).
- **`clean-backups`**
  - Antes usaba `shutil.rmtree`, que en Linux borra con descriptores relativos y en Windows con rutas completas, y no capturaba errores.
  - Ahora renombra cada carpeta a `<nombre>.borrando` y la borra archivo por archivo con rutas completas.
  - Un borrado interrumpido se termina en la siguiente ejecución.
  - Una desconexión detiene la ejecución (código 3); un acceso denegado solo afecta a esa carpeta (código 1).
- **Colisión de nombres** (encontrada porque una prueba fallaba de forma intermitente):
  - Un borrado interrumpido deja `<nombre>.borrando` y libera `<nombre>`. Una ejecución creada en el mismo segundo reutilizaba ese nombre y su borrado chocaba con el anterior («Directory not empty»).
  - Ahora `Run.create` no reutiliza un nombre con un `.borrando` pendiente, y el borrado usa `.borrando-2`, `-3`… si hace falta.
  - Prueba determinista: `test_backup_names_never_collide_with_interrupted_deletions`.
