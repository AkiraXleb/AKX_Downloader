"""Cookies de sesión (manual y desde navegador) expuestas a la API."""
from __future__ import annotations

from akx.cookies import get_cookies_status, write_cookies, clear_cookies
from akx.settings import SUPPORTED_BROWSERS, save_settings


class CookiesMixin:
    # ---------- Cookies / sesión ----------
    def get_cookies_status(self) -> dict:
        return get_cookies_status()

    def save_cookies_text(self, text: str) -> dict:
        ok, msg = write_cookies(text or "")
        return {"ok": ok, "message": msg, "status": get_cookies_status()}

    def clear_cookies(self) -> dict:
        ok = clear_cookies()
        return {"ok": ok, "status": get_cookies_status()}

    # ---------- Cookies desde navegador ----------
    def get_cookies_browser(self) -> dict:
        """Devuelve el navegador configurado y la lista de soportados."""
        return {
            "current":   (self.settings.get("cookies_browser") or "").strip().lower(),
            "supported": list(SUPPORTED_BROWSERS),
        }

    def set_cookies_browser(self, browser: str) -> dict:
        """
        Configura de qué navegador leer las cookies automáticamente.
        Pasa "" (cadena vacía) para desactivar.
        """
        b = (browser or "").strip().lower()
        if b and b not in SUPPORTED_BROWSERS:
            return {"ok": False, "error": f"Navegador no soportado: {b}"}
        self.settings["cookies_browser"] = b
        save_settings(self.settings)
        return {"ok": True, "current": b}

