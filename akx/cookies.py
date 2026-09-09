"""
Cookies de sesión (formato Netscape) usadas por yt-dlp para autenticarse
ante YouTube y otras plataformas. Se guardan en DATA_DIR/cookies.txt.
El usuario las pega vía la página "Cuenta" — no hay archivos externos.
"""
from __future__ import annotations

import time
from pathlib import Path

from akx.paths import COOKIES_FILE, ensure_data_dir

def cookies_path() -> Path:
    return COOKIES_FILE


def cookies_present() -> bool:
    return COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0


def parse_cookies_text(text: str) -> tuple[bool, str, list[dict]]:
    """
    Valida cookies en formato Netscape.
    Devuelve (ok, mensaje, lista_de_cookies_parseadas).
    Cada cookie es dict con: domain, name, expires (epoch o 0).
    """
    if not text or not text.strip():
        return False, "El contenido está vacío.", []

    lines = text.splitlines()
    cookies: list[dict] = []
    bad_lines = 0

    for raw in lines:
        line = raw.strip()
        # Comentarios y vacíos OK
        if not line or line.startswith("#"):
            continue
        # Formato Netscape: 7 campos separados por TAB
        # domain \t flag \t path \t secure \t expires \t name \t value
        parts = raw.split("\t")
        if len(parts) < 7:
            bad_lines += 1
            continue
        try:
            domain = parts[0]
            expires = int(parts[4]) if parts[4].isdigit() else 0
            name = parts[5]
            cookies.append({"domain": domain, "name": name, "expires": expires})
        except Exception:
            bad_lines += 1

    if not cookies:
        return False, ("Formato no reconocido. Necesitas el formato Netscape "
                       "(líneas con 7 campos separados por TAB). "
                       "Usa una extensión como “Get cookies.txt LOCALLY” "
                       "para exportarlas correctamente."), []

    msg = f"Se reconocieron {len(cookies)} cookie(s)."
    if bad_lines:
        msg += f" Se ignoraron {bad_lines} línea(s) inválidas."
    return True, msg, cookies


def get_cookies_status() -> dict:
    """Devuelve el estado actual de las cookies guardadas para el frontend."""
    if not cookies_present():
        return {"present": False}
    try:
        text = COOKIES_FILE.read_text(encoding="utf-8", errors="ignore")
        ok, _msg, cookies = parse_cookies_text(text)
        if not ok:
            return {"present": True, "valid": False,
                    "count": 0, "youtube_count": 0,
                    "modified": COOKIES_FILE.stat().st_mtime}
        # Buscar cookies de YouTube específicamente
        yt = [c for c in cookies if "youtube" in c["domain"].lower()
              or "google" in c["domain"].lower()]
        # Calcular expiración mínima de cookies de YT (las relevantes)
        now = time.time()
        future = [c["expires"] for c in yt if c["expires"] > now]
        soonest = min(future) if future else 0
        return {
            "present":       True,
            "valid":         True,
            "count":         len(cookies),
            "youtube_count": len(yt),
            "modified":      COOKIES_FILE.stat().st_mtime,
            "expires_soonest": soonest,
        }
    except Exception:
        return {"present": True, "valid": False,
                "count": 0, "youtube_count": 0, "modified": 0}


def write_cookies(text: str) -> tuple[bool, str]:
    """Guarda cookies validándolas. Devuelve (ok, mensaje)."""
    ok, msg, _ = parse_cookies_text(text)
    if not ok:
        return False, msg
    ensure_data_dir()
    try:
        # Asegurar header Netscape estándar al inicio si no lo trae
        text_to_write = text
        if not text.lstrip().startswith("#"):
            text_to_write = ("# Netscape HTTP Cookie File\n"
                             "# Guardado por AKX Downloader\n\n") + text
        COOKIES_FILE.write_text(text_to_write, encoding="utf-8")
        # Restringir permisos (en Unix); en Windows no hace daño que falle
        try:
            COOKIES_FILE.chmod(0o600)
        except Exception:
            pass
        return True, msg
    except Exception as e:
        return False, f"No se pudo guardar el archivo: {e}"


def clear_cookies() -> bool:
    try:
        if COOKIES_FILE.exists():
            COOKIES_FILE.unlink()
        return True
    except Exception:
        return False
