# Changelog

## Sin publicar - Fase 2.1

### Etapa 1: normalize-lyrics conserva los bytes

#### Agregado
- `--strip-unknown-headers`: quita también las líneas `[palabra:valor]` desconocidas del inicio (p. ej. `[xtrack:7]`).
- `--offset-policy skip|first|last|sum` para archivos con dos o más `[offset:]` (por defecto `skip`).
- `--skip-near-empty` para omitir las letras casi vacías.
- `--encoding` acepta cualquier códec de texto de Python (`cp1252`, `shift_jis`, `gbk`...). Usa la misma función de conversión que usará `convert-lyrics`. Si un carácter no cabe, el archivo se omite y se lista (nunca se sustituye por `?`).
- Detección de la codificación de origen con `charset-normalizer` (nueva dependencia, Python puro). Una detección ambigua no se da por buena.
- Aviso de posible mojibake (sin corregirlo).
- Sección «Desconocidos / requieren decisión» en el reporte: offsets que no se aplicaron y cabeceras desconocidas que se conservan.
- `--diff` y `registro.txt` muestran los caracteres invisibles como `⟨U+200B⟩`, indican la codificación de origen y marcan la vista como aproximada si no se pudo confirmar.
- Pruebas con la biblioteca de `tools/generar_casos.py`, generada en una carpeta temporal.

#### Cambiado
- `[lr:]` se añade a la lista de cabeceras conocidas (`[hash:]` ya estaba).
- Las cabeceras se reconocen también precedidas de U+200B, U+FEFF, U+200E, U+200F o U+2060; esos caracteres solo se quitan junto con la cabecera.
- Las líneas se separan solo por CRLF, CR y LF, también en el análisis de `scan`.
- La ayuda de `--strip-headers` y `--standardize-headers` muestra los corchetes (`[ti:]`, `[ar:]`...).
- `generar_casos.py`: el caso «13 ascii puro» es ASCII también en las cabeceras.

#### Incompatibilidades con la v0.2.0
- **`--encoding` pasa de `utf8` a `keep` por defecto.** `normalize-lyrics` ya no convierte a UTF-8 ni quita el BOM, salvo que se pida con `--encoding utf8`.
- Se conservan los saltos de línea originales (CRLF, CR o mezclados): ya no se convierten a LF, ni en archivos ni en letras incrustadas. Tampoco se añade un salto de línea final.
- Con dos o más `[offset:]` el archivo ya no se modifica por defecto (antes se aplicaba el último y se borraban todos).
- Un `[offset:]` inválido ya no se borra: el archivo no se toca y se lista.
- Un offset no se aplica si el archivo tiene marcas inválidas (`[00:61.00]`) o marcas `[mm:ss]` dentro del texto: el archivo no se toca y se lista.
- `[lr:]` ahora se quita.
- Las letras casi vacías ahora se procesan, con un aviso (antes no se modificaban).
- Un archivo con solo cabeceras ya no queda vacío: no se escribe y se avisa.
- U+FEFF al inicio de una letra incrustada solo se quita si va antes de una cabecera.
- U+2028, U+0085 y otros separadores Unicode ya no parten líneas. Esto puede cambiar el conteo de letras casi vacías.
- Los archivos de 8 bits que no se pueden decodificar con certeza ya no se marcan como error al quitar cabeceras: se procesan byte a byte.
- `--limit` no tiene límite por defecto con `--diff`.

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