"""
Configuración persistente de la app: valores por defecto, carga/guardado
en ~/.akx_downloader/settings.json y migración desde versiones viejas
que solo tenían un download_dir único.
"""
from __future__ import annotations

import json
from pathlib import Path

from akx.paths import SETTINGS_FILE, ensure_data_dir

DEFAULT_SETTINGS = {
    # Carpeta legacy (compatibilidad con versiones anteriores). Si los usuarios
    # tienen este campo guardado y no tienen los nuevos, se usa este como fallback.
    "download_dir":       str(Path.home() / "Downloads"),
    # Carpetas separadas por tipo de contenido
    "download_dir_audio": str(Path.home() / "Downloads"),
    "download_dir_video": str(Path.home() / "Downloads"),
    "auto_clean_names":   True,
    # Si False (por defecto), el renombrado NO se aplica a archivos MP4/video.
    # Útil porque los videos suelen ser tutoriales, gameplays, podcasts, etc.
    # cuyos títulos originales son descriptivos y no conviene "limpiar".
    "clean_video_names":  False,
    "default_format":     "mp3",
    "audio_kbps":         "320",
    "video_quality":      "best",
    # Ruta manual al ejecutable de FFmpeg. Si está vacía, se busca en el PATH.
    # Útil para instalaciones de winget que no agregan al PATH correctamente.
    "ffmpeg_path":        "",
    # Navegador desde el cual leer cookies automáticamente (yt-dlp --cookies-from-browser).
    # "" = no usar cookies-from-browser (fallback a cookies.txt si existe).
    # Valores válidos: chrome, firefox, edge, brave, opera, safari, chromium, vivaldi.
    "cookies_browser":    "",
    # Si True (default), después de descargar un video HEVC/H.265 se re-encoda
    # a H.264 automáticamente para máxima compatibilidad (Windows Media Player,
    # etc.). Solo se activa si el video baja como HEVC; videos ya en H.264 no
    # se tocan.
    "auto_convert_hevc":  True,
    # Credenciales de la API de Telegram (para grupos/canales privados via Telethon).
    # Se obtienen gratis en https://my.telegram.org → API Development Tools.
    # La sesión login se guarda por separado en telegram.session (Telethon).
    "telegram_api_id":    "",
    "telegram_api_hash":  "",
    # Si True (default), al arrancar la app consulta en segundo plano si hay
    # una versión nueva de yt-dlp en PyPI y avisa con un toast. Nunca instala
    # nada sola: la instalación siempre la dispara el usuario con el botón.
    "ytdlp_auto_check":   True,
}

# Navegadores soportados por yt-dlp para --cookies-from-browser.
SUPPORTED_BROWSERS = ["chrome", "firefox", "edge", "brave", "opera",
                       "safari", "chromium", "vivaldi"]


def _migrate_settings(s: dict) -> dict:
    """
    Para usuarios que vienen de versiones anteriores con un solo download_dir:
    si no tienen los campos nuevos, los inicializan con el viejo.
    """
    if s.get("download_dir") and not s.get("download_dir_audio"):
        s["download_dir_audio"] = s["download_dir"]
    if s.get("download_dir") and not s.get("download_dir_video"):
        s["download_dir_video"] = s["download_dir"]
    return s



def load_settings() -> dict:
    ensure_data_dir()
    if not SETTINGS_FILE.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        out = dict(DEFAULT_SETTINGS)
        out.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        # Migrar: si vienen de versión vieja con un solo download_dir,
        # rellenar los nuevos campos con ese valor.
        out = _migrate_settings(out)
        return out
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict):
    ensure_data_dir()
    try:
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
    except Exception:
        pass
