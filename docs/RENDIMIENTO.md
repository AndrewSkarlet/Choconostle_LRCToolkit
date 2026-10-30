# Rendimiento: memoria y tiempo (Fase 2.1, etapa ⑥)

## Cómo se midió

- **Herramienta:** `tools/medir_rendimiento.py`. Usa `tools/generar_casos.py` como biblioteca, sin modificarlo.
- **Bibliotecas:** la salida de `generar_casos.py` (227 archivos) más dos variantes de tamaño (una letra de unos 100 KB y un MP3 con portada incrustada de 5 MB), copiadas N veces: ×1, ×10, ×30 y ×60, es decir, de 230 a 13 800 archivos. La biblioteca real del usuario tiene unos 7 000 archivos de audio.
- Cada comando se ejecuta **una vez**, en un proceso aparte. El pico de memoria es el RSS máximo del proceso (`ru_maxrss` en Linux y Termux, `PeakWorkingSetSize` en Windows) e incluye el intérprete y las bibliotecas cargadas (unos 40-55 MB).
- **Crecimiento:** (pico ×60 − pico ×1) / (archivos ×60 − archivos ×1).
- **Equipo:** Linux en la nube, Python 3.13, 4 núcleos, disco local (no una SD). Los tiempos en una SD serán mayores; la memoria debería ser la misma.
- **Interferencia:** durante las filas ×10 de «antes» corría a la vez una prueba de 26 s, así que sus tiempos pueden estar algo inflados. La memoria no se ve afectada.

## Antes de las correcciones

| Tamaño | Archivos | Comando | Tiempo (s) | ms/archivo | Pico RSS (MB) | Pico Python (MB) | Código | Escaneados | Entradas | Aplicadas | Omitidas | Errores | Plan (MB) | Respaldo (MB) |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ×1 | 230 | scan | 0.2 | 0.81 | 50.2 | — | 0 |  |  |  |  |  |  |  |
| ×1 | 230 | normalize --diff | 0.4 | 1.87 | 56.8 | — | 0 |  |  |  |  |  |  |  |
| ×1 | 230 | normalize --apply | 0.6 | 2.65 | 66.1 | — | 0 | 231 | 89 | 89 | 3 | 0 | 0.1 | 0.6 |
| ×1 | 230 | revert | 0.2 | 0.84 | 64.9 | — | 0 |  |  |  |  |  |  |  |
| ×1 | 230 | convert --diff | 0.1 | 0.58 | 55.1 | — | 0 |  |  |  |  |  |  |  |
| ×1 | 230 | convert --apply | 0.2 | 0.75 | 55.2 | — | 0 | 231 | 13 | 13 | 2 | 0 | 0.1 | 0.1 |
| ×1 | 230 | clean-backups | 0.0 | 0.10 | 40.6 | — | 0 |  |  |  |  |  |  |  |
| ×10 | 2300 | scan | 0.6 | 0.25 | 53.0 | — | 0 |  |  |  |  |  |  |  |
| ×10 | 2300 | normalize --diff | 2.8 | 1.23 | 56.9 | — | 0 |  |  |  |  |  |  |  |
| ×10 | 2300 | normalize --apply | 5.1 | 2.23 | 66.5 | — | 0 | 2310 | 890 | 890 | 30 | 0 | 1.2 | 6.2 |
| ×10 | 2300 | revert | 1.9 | 0.84 | 67.8 | — | 0 |  |  |  |  |  |  |  |
| ×10 | 2300 | convert --diff | 0.9 | 0.37 | 55.6 | — | 0 |  |  |  |  |  |  |  |
| ×10 | 2300 | convert --apply | 1.0 | 0.45 | 55.5 | — | 0 | 2310 | 130 | 130 | 20 | 0 | 0.6 | 0.7 |
| ×10 | 2300 | clean-backups | 0.1 | 0.06 | 40.6 | — | 0 |  |  |  |  |  |  |  |
| ×30 | 6900 | scan | 1.7 | 0.25 | 58.4 | — | 0 |  |  |  |  |  |  |  |
| ×30 | 6900 | normalize --diff | 9.0 | 1.31 | 56.9 | — | 0 |  |  |  |  |  |  |  |
| ×30 | 6900 | normalize --apply | 18.8 | 2.73 | 66.5 | — | 0 | 6930 | 2670 | 2670 | 90 | 0 | 3.7 | 18.6 |
| ×30 | 6900 | revert | 6.3 | 0.91 | 72.9 | — | 0 |  |  |  |  |  |  |  |
| ×30 | 6900 | convert --diff | 2.5 | 0.36 | 55.6 | — | 0 |  |  |  |  |  |  |  |
| ×30 | 6900 | convert --apply | 3.2 | 0.46 | 55.7 | — | 0 | 6930 | 390 | 390 | 60 | 0 | 1.9 | 2.2 |
| ×30 | 6900 | clean-backups | 0.3 | 0.05 | 40.6 | — | 0 |  |  |  |  |  |  |  |
| ×60 | 13800 | scan | 4.0 | 0.29 | 66.5 | — | 0 |  |  |  |  |  |  |  |
| ×60 | 13800 | normalize --diff | 16.7 | 1.21 | 57.0 | — | 0 |  |  |  |  |  |  |  |
| ×60 | 13800 | normalize --apply | 29.4 | 2.13 | 67.0 | — | 0 | 13860 | 5340 | 5340 | 180 | 0 | 7.3 | 37.1 |
| ×60 | 13800 | revert | 11.4 | 0.83 | 81.5 | — | 0 |  |  |  |  |  |  |  |
| ×60 | 13800 | convert --diff | 5.2 | 0.38 | 55.7 | — | 0 |  |  |  |  |  |  |  |
| ×60 | 13800 | convert --apply | 6.0 | 0.44 | 55.7 | — | 0 | 13860 | 780 | 780 | 120 | 0 | 3.7 | 4.4 |
| ×60 | 13800 | clean-backups | 0.6 | 0.04 | 40.6 | — | 0 |  |  |  |  |  |  |  |

| Comando | Pico RSS menor → mayor (MB) | Crecimiento (bytes por archivo) |
|---|---|---:|
| scan | 50.2 → 66.5 | 1259 |
| normalize --diff | 56.8 → 57.0 | 15 |
| normalize --apply | 66.1 → 67.0 | 73 |
| revert | 64.9 → 81.5 | 1284 |
| convert --diff | 55.1 → 55.7 | 48 |
| convert --apply | 55.2 → 55.7 | 36 |
| clean-backups | 40.6 → 40.6 | 0 |

## Después de las correcciones

| Tamaño | Archivos | Comando | Tiempo (s) | ms/archivo | Pico RSS (MB) | Pico Python (MB) | Código | Escaneados | Entradas | Aplicadas | Omitidas | Errores | Plan (MB) | Respaldo (MB) |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ×1 | 230 | scan | 0.1 | 0.57 | 50.1 | — | 0 |  |  |  |  |  |  |  |
| ×1 | 230 | normalize --diff | 0.4 | 1.71 | 56.7 | — | 0 |  |  |  |  |  |  |  |
| ×1 | 230 | normalize --apply | 0.6 | 2.69 | 66.4 | — | 0 | 231 | 89 | 89 | 3 | 0 | 0.1 | 0.6 |
| ×1 | 230 | revert | 0.2 | 0.88 | 64.6 | — | 0 |  |  |  |  |  |  |  |
| ×1 | 230 | convert --diff | 0.1 | 0.59 | 55.1 | — | 0 |  |  |  |  |  |  |  |
| ×1 | 230 | convert --apply | 0.2 | 0.99 | 55.1 | — | 0 | 231 | 13 | 13 | 2 | 0 | 0.1 | 0.1 |
| ×1 | 230 | clean-backups | 0.0 | 0.10 | 40.8 | — | 0 |  |  |  |  |  |  |  |
| ×10 | 2300 | scan | 0.7 | 0.28 | 53.0 | — | 0 |  |  |  |  |  |  |  |
| ×10 | 2300 | normalize --diff | 2.9 | 1.28 | 57.0 | — | 0 |  |  |  |  |  |  |  |
| ×10 | 2300 | normalize --apply | 5.2 | 2.24 | 66.2 | — | 0 | 2310 | 890 | 890 | 30 | 0 | 1.2 | 6.2 |
| ×10 | 2300 | revert | 2.1 | 0.91 | 65.9 | — | 0 |  |  |  |  |  |  |  |
| ×10 | 2300 | convert --diff | 0.9 | 0.39 | 55.6 | — | 0 |  |  |  |  |  |  |  |
| ×10 | 2300 | convert --apply | 1.1 | 0.46 | 55.7 | — | 0 | 2310 | 130 | 130 | 20 | 0 | 0.6 | 0.7 |
| ×10 | 2300 | clean-backups | 0.1 | 0.05 | 40.8 | — | 0 |  |  |  |  |  |  |  |
| ×30 | 6900 | scan | 1.7 | 0.25 | 58.5 | — | 0 |  |  |  |  |  |  |  |
| ×30 | 6900 | normalize --diff | 8.8 | 1.27 | 56.8 | — | 0 |  |  |  |  |  |  |  |
| ×30 | 6900 | normalize --apply | 14.8 | 2.15 | 67.0 | — | 0 | 6930 | 2670 | 2670 | 90 | 0 | 3.7 | 18.6 |
| ×30 | 6900 | revert | 6.4 | 0.92 | 67.3 | — | 0 |  |  |  |  |  |  |  |
| ×30 | 6900 | convert --diff | 2.7 | 0.39 | 55.8 | — | 0 |  |  |  |  |  |  |  |
| ×30 | 6900 | convert --apply | 2.8 | 0.41 | 55.6 | — | 0 | 6930 | 390 | 390 | 60 | 0 | 1.9 | 2.2 |
| ×30 | 6900 | clean-backups | 0.3 | 0.05 | 40.8 | — | 0 |  |  |  |  |  |  |  |
| ×60 | 13800 | scan | 3.2 | 0.23 | 66.6 | — | 0 |  |  |  |  |  |  |  |
| ×60 | 13800 | normalize --diff | 17.3 | 1.25 | 57.0 | — | 0 |  |  |  |  |  |  |  |
| ×60 | 13800 | normalize --apply | 29.6 | 2.14 | 67.1 | — | 0 | 13860 | 5340 | 5340 | 180 | 0 | 7.3 | 37.1 |
| ×60 | 13800 | revert | 11.7 | 0.85 | 70.1 | — | 0 |  |  |  |  |  |  |  |
| ×60 | 13800 | convert --diff | 4.6 | 0.33 | 55.8 | — | 0 |  |  |  |  |  |  |  |
| ×60 | 13800 | convert --apply | 5.8 | 0.42 | 55.8 | — | 0 | 13860 | 780 | 780 | 120 | 0 | 3.7 | 4.4 |
| ×60 | 13800 | clean-backups | 0.6 | 0.05 | 40.8 | — | 0 |  |  |  |  |  |  |  |

| Comando | Pico RSS menor → mayor (MB) | Crecimiento (bytes por archivo) |
|---|---|---:|
| scan | 50.1 → 66.6 | 1280 |
| normalize --diff | 56.7 → 57.0 | 21 |
| normalize --apply | 66.4 → 67.1 | 54 |
| revert | 64.6 → 70.1 | 420 |
| convert --diff | 55.1 → 55.8 | 52 |
| convert --apply | 55.1 → 55.8 | 52 |
| clean-backups | 40.8 → 40.8 | 0 |

## Qué crecía y qué se corrigió

Se localizó con `tracemalloc`, fase por fase, comparando ×1 con ×20.

| Estructura | Antes | Después | Corrección |
|---|---|---|---|
| Eventos del diario (`Run.outcome()`), usados por `revert`, `--resume`, el reporte y `clean-backups` | ~2 KB por entrada (evento `intent` ~1,5 KB, `done` ~0,5 KB) | ~185 B por entrada | Solo se guarda la posición de cada evento en `diario.jsonl` y se lee del disco cuando se pide (`DiaryEvents`). |
| Resultados de `revert` | ~1,2 KB por resultado (incluía la letra original) | ~485 B | Cada resultado guarda solo id, tipo, ruta y etiqueta, que es lo que usan el registro y la consola. |
| Reporte de `--apply` | Crecía con los eventos `done` | Plano | Cuenta los resultados en una sola lectura del diario. |

**Resultado con ×60 (13 800 archivos, 5 340 entradas aplicadas):**
- `revert` pasa de 81,5 MB a 70,1 MB de pico. El crecimiento baja de 1 284 a 420 bytes por archivo.
- Los tiempos no cambian: `revert` tarda 11,4 s antes y 11,7 s después, dentro del ruido de una sola medición.

## Conclusiones

- **`normalize-lyrics` y `convert-lyrics` (`--diff` y `--apply`):** el pico prácticamente no crece con la biblioteca, entre 21 y 54 bytes por archivo. Eso es menos de 1 MB para 14 000 archivos, dentro de la precisión del RSS. Lo que más pesa es el archivo más grande que se procesa (la portada de 5 MB), no el número de archivos.
- **`revert`:** todavía crece unos 420 bytes por archivo, por la lista de resultados y las posiciones del diario. Para unos 7 000 archivos de audio con sus letras son unos 3-6 MB. Para que fuera plano habría que escribir el registro a medida que avanza y cambiar lo que devuelve `revert`, que usan la consola y 36 pruebas. No se hizo porque el beneficio es pequeño.
- **`scan`:** crece unos 1,3 KB por archivo (66,6 MB con ×60) porque guarda todas las pistas para agrupar los álbumes. Según lo acordado, solo se mide y no se corrige.
- **`clean-backups`:** plano.
- **Tiempo:** es lineal con el número de archivos.

  | Comando | ms por archivo |
  |---|---:|
  | `normalize-lyrics --apply` | ~2,1-2,7 |
  | `normalize-lyrics --diff` | ~1,3 |
  | `revert` | ~0,9 |
  | `convert-lyrics` | ~0,4 |

  Con 13 800 archivos, `--apply` tarda unos 30 s en disco local.
- **Disco:** el respaldo de `normalize-lyrics --apply` ocupa unos 7 KB por entrada aplicada en esta biblioteca (37 MB con 5 340 entradas, en su mayoría copias de `.lrc` y pre-imágenes de etiquetas). El plan ocupa unos 1,4 KB por entrada, porque incluye los diffs.

## Regresión

`tests/test_memoria.py` compara el pico de Python (`tracemalloc`) de un ciclo completo con ×1 y con ×20 copias de dos carpetas de letras: planificar, aplicar, mostrar el reporte y revertir.

- Medido: 648 bytes por entrada con las correcciones y 2 388 sin ellas.
- El umbral es de 1 024 bytes.
- Tarda unos 11 s, más la generación de la biblioteca de casos, que se comparte con el resto de la suite.

## Cómo repetirlo

```bash
python tools/medir_rendimiento.py --destino /ruta/en/la/sd --tamanos 1,10,30,60
python tools/medir_rendimiento.py --ruta-real "/ruta/a/la/biblioteca" --destino /otra/ruta --max-archivos 2000 --max-mb 2000
```

`--ruta-real` copia como máximo `--max-archivos` archivos y `--max-mb` MB de la carpeta indicada y mide sobre la copia: `normalize-lyrics --diff`, `--apply` y `revert`.
- La carpeta original solo se lee.
- `--destino` no puede estar dentro de ella ni contenerla; se comprueba antes de crear nada.
- Al terminar se verifica que el tamaño y la fecha de cada archivo copiado del original no cambiaron.

Probado sobre una biblioteca generada con 150 archivos y 2 MB: el original quedó idéntico (mismo hash de rutas, tamaños y fechas antes y después).
