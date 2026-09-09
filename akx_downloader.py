"""
AKX Downloader — descargador de YouTube con interfaz HTML/CSS/JS
================================================================
Backend: Python + yt-dlp.
Frontend: HTML/CSS/JS embebido y renderizado en una ventana nativa via PyWebView.

Características:
  • Interfaz CSS moderna (glow, transiciones, theming con custom properties)
  • Reproductor integrado (HTML5 <audio>/<video>) con servidor local de archivos
  • Cancelación que ELIMINA los archivos parciales en disco
  • MP3 320 kbps / MP4 mejor calidad (con FFmpeg)
  • Limpieza automática de nombres (quita IDs y "Official Video" etc.)
  • Historial persistente con thumbnails reales y reproducción directa
  • Actualización de yt-dlp desde la propia UI

Dependencias:
    pip install pywebview yt-dlp
    pip install "yt-dlp[default]" --upgrade
    # Linux extra: pip install 'pywebview[gtk]'   (o pywebview[qt])

Opcionales en PATH:
    - ffmpeg  (necesario para MP3 y para mezclar video+audio en MP4)

Persistencia (settings + historial):
    ~/.akx_downloader/

Este archivo es solo el punto de entrada — el código real vive en akx/.
"""
from __future__ import annotations

import sys
import traceback

from akx.ytdlp_engine import install_update_finder, load_engine

# Tiene que ir ANTES de cualquier "import yt_dlp" en el resto de la app —
# ver el docstring de akx/ytdlp_engine.py para el porqué.
install_update_finder()

try:
    load_engine()
except ImportError as e:
    print(f"[!] Falta dependencia: {e}")
    print("    pip install pywebview yt-dlp")
    print('    pip install "yt-dlp[default]" --upgrade')
    print("    (Linux) pip install 'pywebview[gtk]'  o  'pywebview[qt]'")
    sys.exit(1)

from akx.app import main

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
