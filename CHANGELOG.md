# Changelog

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