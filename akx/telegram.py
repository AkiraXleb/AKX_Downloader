"""
Soporte de Telegram (Telethon/MTProto) para grupos y canales privados que
yt-dlp no puede tocar, incluyendo URLs de foros tipo t.me/c/CHAT/TOPIC/MSG.
Telethon se importa perezosamente: si no está instalado, la app arranca
igual y solo falla esta sección con un mensaje explicativo.
"""
from __future__ import annotations

import asyncio
import mimetypes
import os
import re
import threading
from pathlib import Path

from akx.paths import TG_SESSION_FILE

# URLs de Telegram:
#   t.me/NOMBRE/MSG              → grupo/canal público, mensaje MSG
#   t.me/c/CHATID/MSG            → grupo/canal privado
#   t.me/c/CHATID/TOPIC/MSG      → grupo con foros (threads): TOPIC es el tema
# En todos los casos el ID del mensaje real es el ÚLTIMO número de la URL.
TELEGRAM_URL_RE = re.compile(
    r"^https?://(?:www\.)?t\.me/"
    r"(?P<priv>c/)?"
    r"(?P<chat>[A-Za-z0-9_]+)"
    r"(?:/(?P<topic>\d+))?"
    r"/(?P<msg>\d+)/?(?:\?.*)?$"
)


def parse_telegram_url(url: str) -> dict | None:
    """
    Detecta si `url` es un link a un mensaje de Telegram.
    Devuelve dict con {kind: 'private'|'public', chat: str, topic: int|None, msg: int}
    o None si no es una URL de Telegram válida.
    """
    m = TELEGRAM_URL_RE.match((url or "").strip())
    if not m:
        return None
    topic = m.group("topic")
    return {
        "kind":  "private" if m.group("priv") else "public",
        "chat":  m.group("chat"),
        "topic": int(topic) if topic else None,
        "msg":   int(m.group("msg")),
    }

# =====================================================================
# TELEGRAM (grupos privados via Telethon / MTProto)
# =====================================================================
# Telethon se importa perezosamente: si no está instalado, la app arranca
# igual y solo falla la sección de Telegram con un mensaje explicativo.

TELETHON_IMPORT_ERR: Exception | None = None

def _load_telethon():
    """Importa Telethon on-demand. Devuelve el módulo o lanza ImportError."""
    global TELETHON_IMPORT_ERR
    try:
        import telethon  # noqa
        TELETHON_IMPORT_ERR = None
        return telethon
    except Exception as e:
        TELETHON_IMPORT_ERR = e
        raise


def _tg_run(coro):
    """Ejecuta una corutina async en un event loop temporal (para Telethon)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try: loop.close()
        except Exception: pass


class TelegramDownloader:
    """
    Wrapper sync sobre TelegramClient (Telethon).
    Cada operación abre y cierra su propia conexión, para no mantener sockets
    vivos entre llamadas del frontend.
    """

    def __init__(self, api_id: int, api_hash: str,
                 session_path: str | Path = TG_SESSION_FILE):
        self.api_id = int(api_id)
        self.api_hash = str(api_hash)
        self.session_path = str(session_path)

    def _make_client(self):
        _load_telethon()
        from telethon import TelegramClient
        return TelegramClient(self.session_path, self.api_id, self.api_hash)

    def is_authorized(self) -> bool:
        try:
            client = self._make_client()
            async def _op():
                await client.connect()
                try:    return await client.is_user_authorized()
                finally: await client.disconnect()
            return bool(_tg_run(_op()))
        except Exception:
            return False

    def get_me(self) -> dict | None:
        try:
            client = self._make_client()
            async def _op():
                await client.connect()
                try:
                    if not await client.is_user_authorized():
                        return None
                    me = await client.get_me()
                    return {
                        "phone": me.phone,
                        "first_name": me.first_name or "",
                        "last_name":  me.last_name or "",
                        "username":   me.username or "",
                    }
                finally:
                    await client.disconnect()
            return _tg_run(_op())
        except Exception:
            return None

    def send_code(self, phone: str) -> dict:
        """Solicita el código de login. Devuelve el phone_code_hash."""
        try:
            client = self._make_client()
            async def _op():
                await client.connect()
                try:
                    result = await client.send_code_request(phone)
                    return {"ok": True, "phone_code_hash": result.phone_code_hash}
                finally:
                    await client.disconnect()
            return _tg_run(_op())
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sign_in(self, phone: str, code: str, phone_code_hash: str,
                password: str = "") -> dict:
        """Completa el login con código (y contraseña 2FA si corresponde)."""
        try:
            _load_telethon()
            from telethon.errors import (SessionPasswordNeededError,
                                          PhoneCodeInvalidError,
                                          PhoneCodeExpiredError)
            client = self._make_client()

            async def _op():
                await client.connect()
                try:
                    try:
                        await client.sign_in(phone=phone, code=code,
                                              phone_code_hash=phone_code_hash)
                    except SessionPasswordNeededError:
                        if not password:
                            return {"ok": False, "needs_password": True,
                                    "error": "Se requiere contraseña 2FA"}
                        await client.sign_in(password=password)
                    me = await client.get_me()
                    return {"ok": True, "user": {
                        "phone": me.phone,
                        "first_name": me.first_name or "",
                        "last_name":  me.last_name or "",
                    }}
                except PhoneCodeInvalidError:
                    return {"ok": False, "error": "Código incorrecto"}
                except PhoneCodeExpiredError:
                    return {"ok": False, "error": "Código expirado, pide uno nuevo"}
                finally:
                    await client.disconnect()

            return _tg_run(_op())
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def logout(self) -> bool:
        try:
            client = self._make_client()
            async def _op():
                await client.connect()
                try:    await client.log_out()
                finally: await client.disconnect()
            _tg_run(_op())
            # Borrar archivo de sesión también
            try:
                s = Path(self.session_path + ".session")
                if s.exists(): s.unlink()
            except Exception:
                pass
            return True
        except Exception:
            return False

    def download_message(self, chat_ref, msg_id: int, out_dir: Path,
                          progress_cb=None, cancel_event: threading.Event = None
                          ) -> str | None:
        """
        Descarga el media del mensaje `msg_id` del chat `chat_ref`.
        `chat_ref`: username (str) para públicos, o int negativo -100XXXX para privados.
        Devuelve la ruta ABSOLUTA al archivo descargado, o None si falla silenciosamente.
        """
        client = self._make_client()

        async def _op():
            await client.connect()
            try:
                if not await client.is_user_authorized():
                    raise RuntimeError(
                        "Sesión de Telegram no autorizada. Ve a Cuenta → Telegram.")

                entity = await client.get_entity(chat_ref)
                msg = await client.get_messages(entity, ids=msg_id)
                if not msg:
                    raise RuntimeError(
                        f"No se encontró el mensaje {msg_id} en ese chat. "
                        "Verifica que la URL sea correcta y que tengas acceso.")
                if not msg.media:
                    raise RuntimeError(
                        "El mensaje no tiene archivo descargable "
                        "(puede ser solo texto o un link preview).")

                # Chequear tipo de media descargable
                from telethon.tl.types import (
                    MessageMediaPhoto, MessageMediaDocument)
                if not isinstance(msg.media,
                                   (MessageMediaPhoto, MessageMediaDocument)):
                    raise RuntimeError(
                        f"El mensaje contiene {type(msg.media).__name__}, "
                        "que no es un archivo descargable directamente.")

                # PRE-COMPUTAR nombre de archivo desde metadata
                filename = None
                try:
                    if isinstance(msg.media, MessageMediaDocument):
                        doc = msg.media.document
                        # Buscar DocumentAttributeFilename entre los atributos
                        for attr in (doc.attributes or []):
                            fn = getattr(attr, "file_name", None)
                            if fn:
                                filename = fn
                                break
                        if not filename:
                            # Fallback: extensión desde mime_type
                            mime = getattr(doc, "mime_type", "") or ""
                            ext = mimetypes.guess_extension(mime) or ".bin"
                            filename = f"telegram_{msg.id}{ext}"
                    else:  # MessageMediaPhoto
                        filename = f"telegram_{msg.id}.jpg"
                except Exception:
                    filename = f"telegram_{msg.id}.bin"

                # Sanear para Windows
                if os.name == "nt":
                    for ch in '<>:"/\\|?*':
                        filename = filename.replace(ch, "_")

                # ABSOLUTA + carpeta creada
                out_dir.mkdir(parents=True, exist_ok=True)
                target = (out_dir / filename).resolve()

                def _prog(current, total):
                    if cancel_event is not None and cancel_event.is_set():
                        raise asyncio.CancelledError()
                    if progress_cb:
                        try:    progress_cb(current, total)
                        except Exception: pass

                # Pasar path COMPLETO como string (no dir)
                returned = await msg.download_media(
                    file=str(target), progress_callback=_prog)

                # Verificación final: qué archivo existe realmente
                if returned and Path(returned).exists():
                    return str(Path(returned).resolve())
                if target.exists():
                    return str(target)
                raise RuntimeError(
                    "Telethon reportó descarga pero no se creó ningún archivo. "
                    "Puede ser un problema de permisos o de espacio en disco.")
            finally:
                await client.disconnect()

        return _tg_run(_op())


def telegram_status(settings: dict) -> dict:
    """Devuelve el estado del setup de Telegram para el frontend."""
    api_id = (settings.get("telegram_api_id") or "").strip()
    api_hash = (settings.get("telegram_api_hash") or "").strip()
    telethon_available = True
    try:    _load_telethon()
    except Exception: telethon_available = False

    st = {
        "telethon_available": telethon_available,
        "has_credentials":    bool(api_id and api_hash),
        "authorized":         False,
        "user":               None,
    }
    if not telethon_available or not st["has_credentials"]:
        return st
    try:
        api_id_int = int(api_id)
    except ValueError:
        return st
    tg = TelegramDownloader(api_id_int, api_hash)
    if tg.is_authorized():
        st["authorized"] = True
        st["user"] = tg.get_me()
    return st
