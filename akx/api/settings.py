"""Entorno de la app (get_env), configuración general y utilidades chicas."""
from __future__ import annotations

from pathlib import Path

from akx.constants import APP_NAME, APP_VERSION
from akx.icon_data import CUSTOM_ICON_B64
from akx.paths import DATA_DIR
from akx.settings import DEFAULT_SETTINGS, save_settings


class SettingsMixin:
    # ---------- Entorno ----------
    def get_env(self) -> dict:
        manual = (self.settings.get("ffmpeg_path") or "").strip()
        is_manual = bool(manual and self.ffmpeg_path == manual)
        version = ""
        if self.ffmpeg_path:
            ok, ver = self._probe_ffmpeg(self.ffmpeg_path)
            if ok:
                version = ver
        return {
            "app_name":          APP_NAME,
            "app_version":       APP_VERSION,
            "icon_data":         (f"data:image/png;base64,{CUSTOM_ICON_B64}"
                                  if CUSTOM_ICON_B64 else ""),
            "ffmpeg_present":    self.ffmpeg_path is not None,
            "ffmpeg_path":       self.ffmpeg_path or "",
            "ffmpeg_is_manual":  is_manual,
            "ffmpeg_version":    version,
            "home_dir":          str(Path.home()),
            "data_dir":          str(DATA_DIR),
        }


    # ---------- Settings ----------
    def get_settings(self) -> dict:
        return self.settings

    def save_settings(self, new_settings: dict) -> bool:
        for k, v in (new_settings or {}).items():
            if k in DEFAULT_SETTINGS:
                self.settings[k] = v
        save_settings(self.settings)
        return True

    def open_external(self, url: str) -> bool:
        """Abre una URL en el navegador externo del sistema."""
        try:
            import webbrowser
            webbrowser.open(url)
            return True
        except Exception:
            return False
