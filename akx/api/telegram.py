"""Login y estado de Telegram (Telethon) expuestos a la API."""
from __future__ import annotations

from akx.settings import save_settings
from akx.telegram import TelegramDownloader, telegram_status


class TelegramApiMixin:
    # ---------- Telegram (Telethon / MTProto) ----------
    def telegram_get_status(self) -> dict:
        """Estado del setup: telethon disponible, credenciales, autorizado, usuario."""
        return telegram_status(self.settings)

    def telegram_save_credentials(self, api_id: str, api_hash: str) -> dict:
        """Guarda API ID y API Hash de my.telegram.org."""
        api_id = (str(api_id) if api_id is not None else "").strip()
        api_hash = (str(api_hash) if api_hash is not None else "").strip()
        if not api_id or not api_hash:
            return {"ok": False, "error": "Ambos campos son obligatorios"}
        try:
            int(api_id)
        except ValueError:
            return {"ok": False, "error": "API ID debe ser un número"}
        self.settings["telegram_api_id"] = api_id
        self.settings["telegram_api_hash"] = api_hash
        try:
            save_settings(self.settings)
        except Exception as e:
            return {"ok": False, "error": f"Error guardando: {e}"}
        return {"ok": True}

    def telegram_send_code(self, phone: str) -> dict:
        """Envía código de login al teléfono. Guarda phone_code_hash temporal."""
        phone = (phone or "").strip()
        if not phone:
            return {"ok": False, "error": "Teléfono vacío"}
        api_id = (self.settings.get("telegram_api_id") or "").strip()
        api_hash = (self.settings.get("telegram_api_hash") or "").strip()
        if not api_id or not api_hash:
            return {"ok": False, "error": "Guarda las credenciales primero"}
        try:
            tg = TelegramDownloader(int(api_id), api_hash)
        except Exception as e:
            return {"ok": False, "error": f"Credenciales inválidas: {e}"}
        res = tg.send_code(phone)
        if res.get("ok"):
            # Guardar en memoria (no en disco) el hash para completar sign_in
            self._tg_pending = {
                "phone": phone,
                "hash":  res["phone_code_hash"],
            }
        return res

    def telegram_sign_in(self, code: str, password: str = "") -> dict:
        """Completa el login. Requiere haber llamado telegram_send_code antes."""
        pending = getattr(self, "_tg_pending", None)
        if not pending:
            return {"ok": False,
                    "error": "Primero envía el código con 'Enviar código'"}
        api_id = (self.settings.get("telegram_api_id") or "").strip()
        api_hash = (self.settings.get("telegram_api_hash") or "").strip()
        try:
            tg = TelegramDownloader(int(api_id), api_hash)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        res = tg.sign_in(pending["phone"], (code or "").strip(),
                          pending["hash"], (password or "").strip())
        if res.get("ok"):
            self._tg_pending = None
        return res

    def telegram_logout(self) -> dict:
        api_id = (self.settings.get("telegram_api_id") or "").strip()
        api_hash = (self.settings.get("telegram_api_hash") or "").strip()
        if not api_id or not api_hash:
            return {"ok": False, "error": "Sin credenciales"}
        try:
            tg = TelegramDownloader(int(api_id), api_hash)
            tg.logout()
            self._tg_pending = None
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

