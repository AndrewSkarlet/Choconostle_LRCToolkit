"""
config.py

Configuración general del proyecto Choconostle_LRCToolkit.
Este archivo almacena información global utilizada por toda la aplicación.

Autor: Andrew
"""

APP_NAME = "Choconostle_LRCToolkit"
APP_CODENAME = "Xoconostle"
APP_VERSION = "0.1.0"
APP_AUTHOR = "Andrew"
APP_LICENSE = "MIT"


APP_DESCRIPTION = (
    "Toolkit para analizar, reparar y organizar "
    "bibliotecas musicales con archivos LRC."
)


# Extensiones de audio que se escanean. El códec real se identifica
# leyendo el contenido del archivo, no por la extensión.
SUPPORTED_AUDIO = [
    ".flac",
    ".wav",
    ".aif",
    ".aiff",
    ".aifc",
    ".ape",
    ".wv",
    ".mp3",
    ".mp2",
    ".m4a",
    ".m4b",
    ".mp4",
    ".aac",
    ".opus",
    ".ogg",
    ".oga",
    ".mka",
    ".ac3",
    ".eac3",
    ".ec3",
]

# Extensiones de audio reconocidas pero que esta versión no analiza.
UNSUPPORTED_AUDIO = [
    ".wma",
    ".dsf",
    ".dff",
    ".mpc",
    ".tta",
    ".tak",
    ".dts",
    ".mlp",
    ".thd",
]

SUPPORTED_LYRICS = [
    ".lrc",
    ".txt"
]

SUPPORTED_IMAGES = [
    ".jpg",
    ".jpeg",
    ".png",
    ".webp"
]

# Nombres (sin extensión, sin distinguir mayúsculas) que cuentan como
# portada de carpeta: Cover.jpg, folder.png, etc.
COVER_NAMES = [
    "cover",
    "folder",
]

# Subcarpetas de disco ("CD1", "Disc 2", "Disco 1"...). Se agrupan con la
# carpeta padre como un solo álbum.
DISC_FOLDER_PATTERN = r"^(cd|disc|disk|disco)[\s._-]*\d+$"

# Cabeceras LRC (metadatos tipo [ar:Artista]). Poweramp en Android no
# carga letras que las contienen. Otras etiquetas entre corchetes, como
# "[Coro: Artista]", se consideran texto de la letra.
LRC_HEADER_TAGS = [
    "ar", "ti", "al", "au", "by", "length", "offset", "re", "ve",
    "tool", "la", "lang", "language", "id", "key", "hash", "sign",
    "total", "encoding", "kana", "#",
]

# Tamaño máximo que se lee de un archivo de letra externo.
MAX_LYRICS_FILE_SIZE = 2 * 1024 * 1024
