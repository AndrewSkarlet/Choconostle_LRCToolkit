# Pendientes

Lo que no se hizo o no se probó en la versión 1.0.0rc2. Las decisiones ya tomadas y lo que está hecho se describen en `README.md` y `CHANGELOG.md`.

## No probado

- **Tarjetas y dispositivos:**
  - tarjeta SD desde el teléfono y bibliotecas grandes en el teléfono;
  - NAS y ARM;
  - charset-normalizer en Python puro fuera de Linux x86;
  - uso de CPU y batería.
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

## Fuera del rc1

- **Acomodador de biblioteca:** renombrar y ordenar carpetas y archivos. `src/choconostle/rename.py` está vacío.
- **README completo en inglés y mensajes del programa traducidos** (solo hay un README corto, `README.en.md`).
- **Rendimiento en tarjetas lentas:** cada escritura sincroniza el respaldo, el diario y el archivo (fsync), y en tarjetas SD lentas ese coste domina el tiempo total. En una SD de 4 GB (FAT32, USB 2.0), una escritura con sincronización cuesta unos 19 ms por archivo, frente a 1 ms en el disco interno; con 42 archivos, `revert` tardó 21-22 s y `--apply` 25 s. Reducirlo exige agrupar sincronizaciones sin perder la capacidad de reanudar.
- **Idea anotada:** detectar letras que en realidad son publicidad o créditos de la web de origen, por ejemplo una URL que se repite en muchos archivos.
