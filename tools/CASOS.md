# Casos de prueba — Choconostle_LRCToolkit

Biblioteca generada por `generar_casos.py` (requiere ffmpeg). Los audios son 15 s de silencio; las letras son texto inventado.

Columna **Esperado**: lo que debería pasar con `normalize-lyrics --strip-headers`. Lo marcado **⚖️ decidir** es una decisión de diseño pendiente (ver al final).

Casi todas las letras tienen 4 líneas para no caer en "casi vacía" (salvo la carpeta 07).

## 01_codificaciones
Todas con cabeceras `[ti:] [ar:] [by:]` y su .flac al lado.

| Archivo | Prueba | Esperado |
|---|---|---|
| 01 utf8 sin BOM | Caso base | Quita cabeceras |
| 02 utf8 con BOM | `EF BB BF` | Quita cabeceras; BOM según `--encoding` |
| 03 utf16 LE con BOM | `FF FE` | Detecta UTF-16, convierte a UTF-8 |
| 04 utf16 BE con BOM | `FE FF` | Igual que 03 |
| 05 utf16 LE sin BOM | Sin BOM, bytes `00` intercalados | Detectarlo (no confundir con binario) |
| 06 windows-1252 español | `ñ á ü` en 1252 | Convierte a UTF-8 sin romper acentos |
| 07 mojibake | UTF-8 que ya fue mal leído (`CanciÃ³n`) | No "arreglar" a ciegas: avisar |
| 08 shift-jis japonés | | ⚖️ No confirmable → conservar codificación y avisar, o detectar |
| 09 gbk chino | | ⚖️ Igual que 08 |
| 10 euc-kr coreano | | ⚖️ Igual que 08 |
| 11 windows-1251 ruso | | ⚖️ Riesgo: confundirlo con 1252 y dañarlo |
| 12 utf8 multiescritura | Español, japonés, coreano, ruso, árabe (RTL), tailandés, emoji | Quita cabeceras; texto intacto |
| 13 ascii puro | Detectado como `ascii` | Tratarlo como UTF-8 |
| 14–16 japonés/coreano/ruso utf8 | | Quita cabeceras |
| 17 utf8 con bytes inválidos | UTF-8 con un fragmento en 1252 | No convertir todo el archivo; avisar |

## 02_saltos_de_linea
| Archivo | Prueba | Esperado |
|---|---|---|
| 01 LF / 02 CRLF | | Normaliza a LF |
| 03 CR solo | Mac antiguo | Separar bien las líneas (no verlo como una sola) |
| 04 mixto sin salto final | CRLF + LF + CR, sin `\n` al final | Normaliza; agrega salto final |
| 05 espacios y tabs | Cabeceras/marcas con sangría y espacios finales | ⚖️ ¿Reconocer `\t[ar:]` como cabecera? |
| 06 líneas en blanco intermedias | | Conservar blancos de la letra; quitar el que queda tras las cabeceras |
| 07 caracteres invisibles | Espacio de ancho cero antes de `[ti:]`, `U+00A0`, `U+2028`, BOM al final | ⚖️ Quitar `U+200B`/BOM sobrantes; `U+2028` puede partir líneas |

## 03_cabeceras
| Archivo | Prueba | Esperado |
|---|---|---|
| 01 estándar | Tu caso de SpotiFLAC | Quita las 3 |
| 02 todas las conocidas | ar al ti au lr length by re tool ve la `#` | Quita todas las de la lista |
| 03 offset +500 | | Resta 0.5 s a cada marca |
| 04 offset −300 | | Suma 0.3 s |
| 05 offset sin signo | `[offset:250]` = +250 | Igual que positivo |
| 06 offset que deja negativo | +2000 con marca en 00:01 | Primera marca a 00:00.00 |
| 07 offset inválido | `[offset:medio segundo]` | No tocar tiempos; avisar |
| 08 dos offsets | | ⚖️ Usar el último, sumar, o avisar y no tocar |
| 09 mayúsculas | `[TI:] [Ar:] [BY:]` | Reconocer sin distinguir mayúsculas |
| 10 espacios dentro | `[ ti : x ]`, `[ar: ]`, `[al:]` vacías | Quitar |
| 11 duplicadas | Dos `[ar:]` distintos | Quitar ambas (standardize: no duplicar) |
| 12 en medio y al final | `[ar:]` entre líneas, `[by:]` al final | Quitar también esas |
| 13 corchetes que no son cabeceras | `[Coro]`, `[Coro: Artista]`, `(Instrumental)` | **No tocar**: son letra |
| 14 secciones sin marca | `[Verso 1]`, `[Coro]` sueltas | No tocar (o ⚖️ opción para quitarlas) |
| 15 solo cabeceras | Sin letra | Resultado vacío → ⚖️ no tocar y avisar |
| 16 cabeceras + letra sin sincronizar | | Quita cabeceras, deja texto |
| 17 cabecera desconocida | `[xtrack:7]`, `[hash:abc]` | ⚖️ Por defecto no tocar (no está en la lista) |
| 18 valor con `]` y `:` | `[ti:Canción: parte 2 [Remix]]` | Quitar la línea completa sin dejar `]` suelto |

## 04_marcas_de_tiempo
| Archivo | Prueba | Esperado |
|---|---|---|
| 01–03 | `.xx`, `.xxx`, `.x` | Conservar formato original |
| 04 sin fracción | `[00:01]` | Reconocer como sincronizada |
| 05 dos puntos | `[00:01:00]` (variante rara) | ⚖️ Reconocer o avisar |
| 06 coma | `[00:01,00]` | ⚖️ Reconocer o avisar |
| 07 un dígito | `[0:01.00]` | Reconocer |
| 08 >99 min / con horas | `[102:03.45]`, `[01:02:03.45]` | Reconocer; offset correcto |
| 09 varias marcas por línea | `[00:04.50][00:12.00]Coro` | Aplicar offset a ambas |
| 10 desordenadas | | No reordenar (o ⚖️ opción `--sort`) |
| 11 marcas vacías | `[00:03.00]` sin texto = pausa | Conservar |
| 12 mezcla con líneas sin marca | | Contar como sincronizada; no borrar las otras |
| 13 marcas inválidas | `[00:61.00]`, `[aa:bb.cc]` | No tocar; avisar |
| 14 espacio tras la marca | `[00:01.00] Uno` | Conservar |
| 15 marca final sin texto | Marca de fin `[00:14.50]` | Conservar |

## 05_palabra_por_palabra
| Archivo | Prueba | Esperado |
|---|---|---|
| 01 enhanced A2 | `<00:01.40>es` con cabeceras | Quita cabeceras, conserva `<…>` |
| 02 milésimas | | Igual |
| 03 con offset | | Ajusta `[…]` y `<…>` |
| 04 sin marca de cierre | | Igual |
| 05 corchetes en línea (estilo QQ) | `[00:01.00]Esta[00:01.40]es` | ⚖️ No confundir con "varias marcas por línea" |
| 06 voces v1/v2 | | Conservar prefijos |
| 07 voces M: F: D: | Formato Walaoke | Conservar prefijos |
| 08 mezcla palabra/línea | | Conservar ambas |
| 09 japonés | Palabras sin espacios | Igual |
| 10 enhanced en .txt | | Igual que .lrc |

Opciones propuestas: `--word-timing keep` (por defecto), `strip` (quitar `<…>` para DAPs), y `--strip-voices` aparte.

## 06_traducciones
| Archivo | Prueba | Esperado |
|---|---|---|
| 01 marca duplicada | Original + traducción con la misma marca | Conservar ambas y su orden |
| 02 en la misma línea | `原文 / traducción` | No tocar |
| 03 romanización | Entre paréntesis | No tocar |

## 07_casi_vacias
| Archivo | Esperado |
|---|---|
| 01 solo "Instrumental" / 02 con cabeceras | Procesar y avisar (regla nueva) |
| 03 dos líneas / 04 tres líneas | Probar el umbral |
| 05 0 bytes / 06 solo espacios / 07 solo BOM | No tocar; avisar "vacía" |
| 08 marcas sin texto | Avisar |
| 09 "Letra no disponible" | ⚖️ Detectar textos de relleno comunes |

## 08_txt
| Archivo | Prueba | Esperado |
|---|---|---|
| 01 txt sincronizado con canción | | Letra: quitar cabeceras |
| 02 txt sin sincronizar con canción | | Letra: quitar cabeceras |
| 03 mismo nombre .lrc y .txt | | ⚖️ ¿Cuál cuenta? Procesar ambos y avisar |
| 04 txt huérfano sincronizado | | Detectar por contenido → tratar como letra |
| 05 txt huérfano simple | | No tocar; listar |
| README.txt | Notas con `[Disco 1]` | **No tocar** |
| tracklist.txt | `(3:45)` y `[01:02]` | **No tocar** (trampa de falso positivo) |
| notas con cabecera.txt | Una `[ar:]` y texto | ⚖️ Trampa: ¿una sola cabecera basta? |
| 06 `.LRC` / 07 `.Lrc` | Extensión en mayúsculas | Reconocer |
| 08 txt utf16 | | Detectar codificación |

Opción propuesta: `--txt-to-lrc` (sin sobrescribir un .lrc existente).

## 09_emparejamiento
| Archivo | Prueba | Esperado |
|---|---|---|
| 01 `01. Mr. Nombre...` | Varios puntos | Emparejar por nombre completo sin extensión |
| 02–04 | Acentos, `[Explicit] & (feat.)`, japonés | Emparejar |
| 05 mayúsculas distintas | `.flac` y `.LRC` con nombre en otro caso | ⚖️ En Windows es el mismo archivo; en Linux/Android no |
| 06 nombre distinto | Canción sin letra + .lrc con otro nombre | Huérfano; no emparejar por adivinanza |
| 07 mp3 y flac mismo nombre | Un solo .lrc para dos audios | Procesar el .lrc una sola vez |
| 08 espacio antes de la extensión | `nombre .flac` | Emparejar |
| 09 letra en `Lyrics/` | Subcarpeta | ⚖️ Algunos reproductores la usan |
| 10 lrc huérfano total | | Procesar con `--strip-headers` |

## 10_incrustadas
| Archivo | Prueba | Esperado |
|---|---|---|
| 01 FLAC LYRICS | | Quita cabeceras |
| 02 FLAC UNSYNCEDLYRICS sincronizada | Tu caso real | Quita; ⚖️ ¿mover a LYRICS? |
| 03 LYRICS y UNSYNCEDLYRICS distintas | Una sincronizada, otra no | Procesar ambas por separado |
| 04 incrustada distinta al .lrc | Contenidos diferentes | Procesar cada una; ⚖️ avisar discrepancia |
| 05 BOM dentro del texto | `U+FEFF` al inicio de la etiqueta | Quitar el BOM; luego reconocer `[ti:]` |
| 06 CRLF dentro | | Normalizar a LF |
| 07 por palabra | | Igual que 05_palabra |
| 08 dos campos LYRICS | Clave repetida (válido en Vorbis) | Procesar ambos, no perder ninguno |
| 09 clave en minúsculas | `lyrics=` | Reconocer |
| 10 con offset | | Aplicar offset |
| 11 casi vacía | | Regla de casi vacías |
| 20 MP3 v2.4 USLT UTF-8 | | Quitar; conservar v2.4 |
| 21 MP3 v2.3 USLT UTF-16 | | Quitar; conservar v2.3 y UTF-16 |
| 22 MP3 v2.3 USLT Latin-1 | Acentos en Latin-1 | Conservar acentos |
| 23 dos USLT (eng, spa) | | Procesar ambos |
| 24 USLT con descripción | | Conservar descripción |
| 25 SYLT | Sin cabeceras | Sin cambios |
| 26 SYLT con cabecera | Entrada `[ti:…]` en ms 0 | Quitar solo esa entrada |
| 27 TXXX:LYRICS | | Quitar |
| 28 USLT + SYLT + .lrc | Tres fuentes | Procesar las tres |
| 29 USLT por palabra | | Conservar `<…>` |
| 30 TXXX:UNSYNCEDLYRICS v2.3 | | Quitar |
| 40/41 M4A AAC/ALAC `©lyr` | | Quitar |
| 42 Opus / 43 OGG Vorbis | | Quitar |
| 44 WavPack APEv2 `Lyrics` | | Quitar |
| 45 WAV + .lrc | WAV no admite letra incrustada | Solo el .lrc |

## Decisiones pendientes (⚖️)
1. Codificaciones no confirmables (Shift-JIS, GBK, EUC-KR, 1251): ¿detectar con una librería como `charset-normalizer`, o conservar y avisar?
2. Cabeceras con sangría, desconocidas o duplicadas como `[offset:]`.
3. Variantes raras de marca (`mm:ss:xx`, coma).
4. Marcas por palabra con corchetes (estilo QQ).
5. Letra sincronizada guardada en `UNSYNCEDLYRICS`: dejarla o moverla a `LYRICS` (opción aparte).
6. Discrepancia entre letra incrustada y .lrc: solo avisar, o elegir una fuente.
7. `.txt`: decidir por contenido; cuántas señales hacen falta para tratarlo como letra.
8. Emparejar sin distinguir mayúsculas en Linux/Android.
9. Letras en subcarpeta `Lyrics/`.
