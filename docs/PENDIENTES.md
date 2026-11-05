# Pendientes

Lo que no se hizo o no se probó en la versión 1.0.0rc1. Las decisiones ya tomadas y lo que está hecho se describen en `README.md` y `CHANGELOG.md`.

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
- **`revert`:** tras el cambio de la v1.0.0-rc1 usa la misma verificación que `--apply`, pero no se ha vuelto a medir en una SD (antes tardaba 14,5 s frente a 5,2 s de `--apply` con 28 archivos).
- **`fix-gallery`:** no se ha probado en Android real. No se ha comprobado cómo reacciona cada app de música a los `.nomedia` (MediaStore).
- **Pantalla de la consola:** no se ha comprobado en consolas de Windows que la línea de progreso ya no deja restos del nombre anterior; en Linux no se reproducía.
- **`[Errno 22] Invalid argument`:** no se probó con nombres de archivo no válidos en FAT.
- **`--resume` tras una desconexión real:** no se verificaron después el audio y las etiquetas.

## Conocido y sin resolver

- **`[Errno 22] Invalid argument`:** apareció al desconectar una SD real y no se trata como desconexión. Falla solo ese archivo, con código 1.
- **`tests/test_memoria.py`:**
  - en Windows tarda entre 45 y 57 s, y se pidieron unos 30 s;
  - en una ejecución de la suite completa en Linux falló («el pico creció 5140 bytes por entrada»), aunque sola pasa 3 de 3. La causa no se ha determinado.
- **Memoria:** `revert` crece unos 420 bytes por archivo y `scan` unos 1,3 KB por archivo (ver `docs/RENDIMIENTO.md`).

## Fuera del rc1

- **Acomodador de biblioteca:** renombrar y ordenar carpetas y archivos. `src/choconostle/rename.py` está vacío.
- **README en inglés.**
- **Rendimiento en tarjetas lentas:** cada escritura sincroniza el respaldo, el diario y el archivo (fsync), y en tarjetas SD lentas ese coste domina el tiempo total. Reducirlo exige agrupar sincronizaciones sin perder la capacidad de reanudar.
- **Idea anotada:** detectar letras que en realidad son publicidad o créditos de la web de origen, por ejemplo una URL que se repite en muchos archivos.
