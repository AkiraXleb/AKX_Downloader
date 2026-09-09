"""
Rutas y constantes de archivo usadas por toda la app: dónde vive el
ejecutable/script, dónde se guardan settings/historial/cookies/sesión de
Telegram, dónde queda la copia actualizada de yt-dlp, y qué extensiones
cuentan como "audio" o "video".
"""
from __future__ import annotations

import sys
from pathlib import Path


def script_dir() -> Path:
    """Carpeta del ejecutable (congelado) o del repo (corriendo como script)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Este archivo vive en akx/paths.py -> parent (akx/) -> parent (raíz del
    # repo, junto a akx_downloader.py).
    return Path(__file__).resolve().parent.parent


SCRIPT_DIR    = script_dir()

# Carpeta del paquete akx/ (para ubicar assets propios, como ui/index.html).
PACKAGE_DIR   = Path(__file__).resolve().parent
UI_INDEX      = PACKAGE_DIR / "ui" / "index.html"

DATA_DIR      = Path.home() / ".akx_downloader"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE  = DATA_DIR / "history.json"
COOKIES_FILE  = DATA_DIR / "cookies.txt"
TG_SESSION_FILE = DATA_DIR / "telegram"   # Telethon agrega ".session" solo

# Copia de yt-dlp actualizada desde la UI (ver akx/ytdlp_engine.py). Vive acá
# y no en ytdlp_engine.py porque el finder de sys.meta_path necesita esta
# ruta antes de que se resuelva ningún import de yt_dlp, y paths.py no
# importa yt_dlp ni webview — se puede cargar sin disparar ese import.
YTDLP_UPDATE_DIR = DATA_DIR / "ytdlp"
YTDLP_STAMP_FILE = YTDLP_UPDATE_DIR / "installed.json"

AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".avi"}
MEDIA_EXTS = AUDIO_EXTS | VIDEO_EXTS


def ensure_data_dir() -> None:
    """Crea DATA_DIR si no existe. Usado por settings/history/cookies."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
