"""Diálogos nativos de selección de carpeta expuestos a la API."""
from __future__ import annotations

from pathlib import Path

import webview


class DialogsMixin:
    # ---------- Diálogos ----------
    def browse_folder(self, kind: str | None = None) -> str | None:
        """
        Abre un selector de carpeta. El parámetro `kind` ('audio' o 'video')
        define qué carpeta usar como punto de partida del diálogo:
          - 'audio': arranca desde download_dir_audio
          - 'video': arranca desde download_dir_video
          - None:    arranca desde download_dir legacy o home
        """
        if not webview.windows:
            return None
        if kind == "audio":
            initial = self.settings.get("download_dir_audio")
        elif kind == "video":
            initial = self.settings.get("download_dir_video")
        else:
            initial = self.settings.get("download_dir")
        if not initial:
            initial = str(Path.home())
        result = webview.windows[0].create_file_dialog(
            webview.FOLDER_DIALOG,
            directory=initial,
        )
        if result:
            return result[0] if isinstance(result, (list, tuple)) else result
        return None

