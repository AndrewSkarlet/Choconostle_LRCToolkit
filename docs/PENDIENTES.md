# Pendientes

Lo que no se hizo o no se probó hasta la versión 1.0.0rc3.dev0 (en desarrollo; la rc3 saldrá con el organizador de carpetas). Las decisiones ya tomadas y lo que está hecho se describen en `README.md` y `CHANGELOG.md`.

## Probado con la rc2

- **Tarjeta SD desde el teléfono, con biblioteca real:** LG G8 con Termux, 6690 letras en 4468 archivos. Simulación en 8 min 45 s, `--apply` en 31 min 23 s, 0 errores, 8 % de batería sin cargador. Una segunda simulación dio 0 a modificar, y Poweramp y otra app leen bien las letras.
- **Suite automática de la rc2:** 525/525 en Windows, Moto Edge 60 Fusion, LG G8 y Samsung A31 (Termux).

## Resuelto

- **Cambio externo solo en el audio en Android:** dos escrituras seguidas podían quedar con la misma `st_mtime_ns` y un byte de audio cambiado entre planificar y aplicar no se detectaba (`test_file_changed_between_plan_and_apply` fallaba de forma intermitente en tres teléfonos). Desde la rc2 el plan guarda la huella del audio; la suite pasó 525/525 en los tres teléfonos. Queda el límite descrito abajo (sin `--verify full`, solo el primer y el último MB).
- **Letras con «desconocidos» de la biblioteca real (287):** las etiquetas de sección (`[Intro: ...]`, `[Chorus]`), `[instrumental:true]` y los datos extendidos de SpotiFLAC (`[x-romaji:...]`) ya se clasifican (rc3.dev0). Falta repetir la simulación con la biblioteca real.
- **Idea de la rc1, hecha:** detectar letras que son publicidad o créditos de la web de origen («Letras sospechosas», rc3.dev0). Falta comprobar con la biblioteca real cuántos falsos positivos da.

## No probado

- **Tarjetas y dispositivos:**
  - NAS y ARM fuera de Android;
  - charset-normalizer en Python puro fuera de Linux x86;
  - uso de CPU (la batería, solo en la prueba del LG G8).
- **Comandos en Android:** `convert-lyrics` en Termux.
- **Disco lleno real:** solo está simulado.
- **Editor ID3:** solo se probó con MP3 generados, no con MP3 reales con cabeceras.
- **Mediciones de rendimiento** (`tools/medir_rendimiento.py`): solo en Linux sobre disco local, no en Windows ni en una SD.
- **`fix-gallery`:** se probó en un teléfono Android real (Termux) con una app de música, que siguió viendo las canciones. No se ha comprobado con otras apps de música, que pueden reaccionar distinto a los `.nomedia` (MediaStore).

## Conocido y sin resolver

- **`[Errno 22] Invalid argument`:** aparece al quitar una SD real y se reporta como posible desconexión («La unidad dejó de responder ([Errno 22]...) ¿se desconectó la tarjeta SD?», código 3). No se ha probado su comportamiento con nombres de archivo no válidos en FAT, que también pueden provocarlo.
- **`tests/test_memoria.py`:**
  - en Windows tarda entre 45 y 57 s, y se pidieron unos 30 s;
  - en una ejecución de la suite completa en Linux falló («el pico creció 5140 bytes por entrada»), aunque sola pasa 3 de 3. La causa no se ha determinado.
- **Huella del audio sin `--verify full`:** el hash que se guarda en el plan solo cubre el primer y el último MB del audio. Un cambio externo en el medio de un archivo de más de 2 MB, con el mismo tamaño y la misma fecha de modificación, no se detecta antes de escribir (con `--verify full`, sí).
- **Memoria:** `revert` crece unos 420 bytes por archivo y `scan` unos 1,3 KB por archivo (ver `docs/RENDIMIENTO.md`).

- **Novedades de la rc3.dev0 sin probar en dispositivos:** la pregunta «¿Guardar la lista completa?» en Termux (la ruta `~/storage/shared/Download` necesita `termux-setup-storage`), las barras nuevas en consolas de Windows y los avisos de letras sospechosas con la biblioteca real.

## Fuera de la rc3.dev0

- **Organizador de carpetas (acomodador de biblioteca):** renombrar y ordenar carpetas y archivos; saldrá con la rc3. Aún no hay código (el `rename.py` vacío se borró; ver `docs/LIMPIEZA.md`).
- **README completo en inglés y mensajes del programa traducidos** (solo hay un README corto, `README.en.md`).
- **Rendimiento en tarjetas lentas:** cada escritura sincroniza el respaldo, el diario y el archivo (fsync), y en tarjetas SD lentas ese coste domina el tiempo total. En una SD de 4 GB (FAT32, USB 2.0), una escritura con sincronización cuesta unos 19 ms por archivo, frente a 1 ms en el disco interno; con 42 archivos, `revert` tardó 21-22 s y `--apply` 25 s. Reducirlo exige agrupar sincronizaciones sin perder la capacidad de reanudar.
