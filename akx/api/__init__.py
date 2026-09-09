"""
Clase API expuesta al frontend vía pywebview.api.*. Cada método que el JS
llama vive en uno de los mixins de este paquete, agrupados por tema
(settings, cookies, telegram, ffmpeg, ytdlp, dialogs, downloads, history,
player) — esta clase solo los combina y define el __init__ compartido.

El JS nunca nota la diferencia: `pywebview.api.start_download(...)`,
`pywebview.api.ytdlp_update()`, etc. siguen resolviendo igual que cuando
todo vivía en una sola clase de 80 métodos.
"""
from __future__ import annotations

import threading
from pathlib import Path

from akx.file_server import FileServer
from akx.history import load_history
from akx.settings import load_settings
from akx.ytdlp_engine import _purge_ytdlp_trash

from .cookies import CookiesMixin
from .dialogs import DialogsMixin
from .downloads import DownloadMixin
from .ffmpeg import FfmpegMixin
from .history import HistoryMixin
from .player import PlayerMixin
from .settings import SettingsMixin
from .telegram import TelegramApiMixin
from .ytdlp import YtdlpMixin


class API(
    SettingsMixin,
    CookiesMixin,
    TelegramApiMixin,
    DialogsMixin,
    FfmpegMixin,
    YtdlpMixin,
    DownloadMixin,
    HistoryMixin,
    PlayerMixin,
):
    def __init__(self):
        self.settings = load_settings()
        self.history  = load_history()
        self.cancel_event = threading.Event()
        self.is_downloading = False
        self.current_state = self._initial_state()
        self._current_video_id: str | None = None
        self._current_outdir: Path | None = None
        # Cache de metadatos extraídos durante la descarga, indexado por video_id.
        # Lo usamos en _post_hook para renombrar usando artist/track si están.
        self._video_metadata: dict[str, dict] = {}
        self.file_server = FileServer()
        # Detectar FFmpeg: primero la ruta manual de settings, sino el PATH
        self.ffmpeg_path = self._detect_ffmpeg()
        # Estado del actualizador de yt-dlp (lo pollea el frontend)
        self._ytdlp_state = self._initial_ytdlp_state()
        self._ytdlp_lock = threading.Lock()
        # Limpiar restos de una actualización anterior que quedó bloqueada
        _purge_ytdlp_trash()
