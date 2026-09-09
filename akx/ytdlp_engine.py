"""
yt-dlp actualizable en caliente.

Cuando el usuario actualiza yt-dlp desde Configuración, la copia nueva se
guarda en ~/.akx_downloader/ytdlp/ — la que viene empaquetada en el .exe no
se toca nunca (vive adentro del bundle y es de solo lectura).

Para que la copia actualizada gane, NO alcanza con sys.path: adentro del
.exe, PyInstaller resuelve los imports con un finder propio en sys.meta_path
que ignora sys.path, así que el yt_dlp empaquetado taparía al actualizado.
Por eso este módulo instala un finder al principio de sys.meta_path que se
queda con TODO lo que empiece con "yt_dlp" y lo resuelve desde nuestra
carpeta. Los submódulos también pasan por acá, si no terminaríamos
mezclando mitad paquete nuevo y mitad viejo.

IMPORTANTE — orden de imports: `install_update_finder()` tiene que llamarse
ANTES de que cualquier módulo de la app haga `import yt_dlp` — por eso es lo
primero que hace akx_downloader.py, antes de importar akx.app.

yt-dlp se rompe seguido porque YouTube cambia cosas; tener el motor viejo es
la causa #1 de errores 403 / "no se encontró formato". Por eso la app puede
actualizarlo sola, con dos estrategias según cómo esté corriendo:

  • Corriendo desde el .py (hay pip):  pip install -U yt-dlp
  • Corriendo desde el .exe (no hay pip, y yt_dlp está adentro del bundle):
    se baja el wheel de PyPI y se descomprime en ~/.akx_downloader/ytdlp/.

En los dos casos el cambio recién toma efecto al reiniciar la app, porque
el módulo yt_dlp ya está importado en memoria.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from akx.constants import APP_NAME, APP_VERSION
from akx.paths import YTDLP_UPDATE_DIR, YTDLP_STAMP_FILE
from akx.utils import fmt_bytes

PYPI_YTDLP_JSON = "https://pypi.org/pypi/yt-dlp/json"
_UA = f"{APP_NAME}/{APP_VERSION}"


class _YtdlpUpdateFinder:
    """Resuelve el paquete yt_dlp desde YTDLP_UPDATE_DIR, antes que nada más."""

    _roots = [str(YTDLP_UPDATE_DIR)]

    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        import importlib.machinery as _machinery
        if fullname == "yt_dlp":
            return _machinery.PathFinder.find_spec(fullname, cls._roots, target)
        if fullname.startswith("yt_dlp."):
            # `path` acá ya es el __path__ del paquete cargado de nuestra
            # carpeta, así que el submódulo sale del mismo lugar.
            return _machinery.PathFinder.find_spec(fullname, path, target)
        return None   # cualquier otro módulo no es asunto nuestro


def install_update_finder() -> None:
    """
    Registra el finder si hay una copia local válida de yt-dlp.

    Solo se activa si la carpeta tiene __init__.py de verdad: una carpeta a
    medio extraer se importaría como "namespace package" vacío y la app
    arrancaría con un yt_dlp fantasma que revienta recién al descargar.
    """
    if not (YTDLP_UPDATE_DIR / "yt_dlp" / "__init__.py").is_file():
        return
    try:
        if _YtdlpUpdateFinder not in sys.meta_path:
            sys.meta_path.insert(0, _YtdlpUpdateFinder)
    except Exception:
        pass   # si algo sale mal, se usa el yt-dlp empaquetado y listo


def load_engine():
    """
    Importa webview + yt_dlp. Si la copia actualizada de yt-dlp está rota,
    la descarta y reintenta con la que trae la app, en lugar de dejar la
    aplicación sin arrancar. Devuelve (webview, yt_dlp).
    """
    def _attempt():
        import webview as _wv
        import yt_dlp as _yt
        if not hasattr(_yt, "YoutubeDL"):
            raise ImportError("el paquete yt_dlp está incompleto")
        return _wv, _yt

    try:
        return _attempt()
    except ImportError:
        if _YtdlpUpdateFinder not in sys.meta_path:
            raise

    sys.meta_path.remove(_YtdlpUpdateFinder)
    for _name in [k for k in sys.modules
                  if k == "yt_dlp" or k.startswith("yt_dlp.")]:
        sys.modules.pop(_name, None)
    loaded = _attempt()
    print("[!] La copia actualizada de yt-dlp está rota; "
          "se usa la versión que trae la app.")
    return loaded


def ytdlp_current_version() -> str:
    """Versión de yt-dlp efectivamente cargada en este proceso."""
    try:
        from yt_dlp.version import __version__ as v
        return str(v)
    except Exception:
        return "?"


def ytdlp_override_active() -> bool:
    """True si el yt_dlp cargado salió de la carpeta de actualizaciones."""
    try:
        import yt_dlp
        mod_dir = Path(yt_dlp.__file__).resolve().parent.parent
        return mod_dir == YTDLP_UPDATE_DIR.resolve()
    except Exception:
        return False


def ytdlp_override_version() -> str:
    """Versión guardada en la carpeta de actualizaciones ('' si no hay)."""
    try:
        if YTDLP_STAMP_FILE.exists():
            data = json.loads(YTDLP_STAMP_FILE.read_text(encoding="utf-8"))
            return str(data.get("version") or "")
    except Exception:
        pass
    return ""


def ytdlp_pending_version() -> str:
    """
    Versión ya instalada en la carpeta local que todavía NO está en uso: se
    va a activar en el próximo arranque. Devuelve '' si no hay nada pendiente.
    """
    if ytdlp_override_active():
        return ""     # ya está en uso, no hay nada pendiente
    if not (YTDLP_UPDATE_DIR / "yt_dlp" / "__init__.py").is_file():
        return ""
    v = ytdlp_override_version()
    return v if v and ytdlp_is_newer(v, ytdlp_current_version()) else ""


def _version_tuple(v: str) -> tuple:
    """
    Convierte '2026.8.19' o '2026.07.04.232712' en tupla de enteros comparable.
    Las versiones de yt-dlp son fechas, pero a veces con ceros a la izquierda
    y a veces sin ellos ('2026.8.19' vs '2026.08.19'), así que comparar como
    string no sirve.
    """
    parts = []
    for chunk in str(v or "").split("."):
        m = re.match(r"^(\d+)", chunk.strip())
        parts.append(int(m.group(1)) if m else 0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def ytdlp_is_newer(latest: str, current: str) -> bool:
    """True si `latest` es posterior a `current`."""
    if not latest or not current or current == "?":
        return bool(latest)
    try:
        return _version_tuple(latest) > _version_tuple(current)
    except Exception:
        return latest != current


def ytdlp_fetch_latest() -> dict:
    """
    Consulta PyPI por la última versión estable de yt-dlp.
    Devuelve {"ok": bool, "version": str, "wheel_url": str, "error": str}.
    """
    import urllib.request
    try:
        req = urllib.request.Request(PYPI_YTDLP_JSON, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "version": "", "wheel_url": "",
                "error": f"No se pudo consultar PyPI: {e}"}

    version = str((data.get("info") or {}).get("version") or "")
    wheel_url = ""
    for f in (data.get("urls") or []):
        if (f.get("packagetype") == "bdist_wheel"
                and str(f.get("filename", "")).endswith("py3-none-any.whl")):
            wheel_url = f.get("url") or ""
            break
    if not version:
        return {"ok": False, "version": "", "wheel_url": "",
                "error": "Respuesta de PyPI inesperada"}
    return {"ok": True, "version": version, "wheel_url": wheel_url, "error": ""}


def _purge_ytdlp_trash():
    """Borra restos de actualizaciones anteriores que quedaron bloqueados."""
    try:
        if not YTDLP_UPDATE_DIR.exists():
            return
        for p in YTDLP_UPDATE_DIR.glob(".trash-*"):
            shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


def _retire_dir(path: Path):
    """
    Saca del medio una carpeta vieja. Intenta borrarla; si Windows la tiene
    tomada, la renombra a .trash-* para limpiarla en el próximo arranque.
    """
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
        return
    except Exception:
        pass
    try:
        path.rename(path.parent / f".trash-{int(time.time())}-{path.name}")
    except Exception:
        pass


def _clear_ytdlp_dir():
    """
    Vacía la carpeta de actualizaciones: el paquete `yt_dlp` más todo lo que
    trae el wheel al lado (`yt_dlp-VERSION.dist-info`, `yt_dlp-VERSION.data`).
    Si no se limpian los `-*`, se van acumulando con cada actualización.
    """
    if not YTDLP_UPDATE_DIR.exists():
        return
    _purge_ytdlp_trash()
    targets = [YTDLP_UPDATE_DIR / "yt_dlp"] + sorted(YTDLP_UPDATE_DIR.glob("yt_dlp-*"))
    for old in targets:
        if old.is_dir():
            _retire_dir(old)
        elif old.exists():
            try:    old.unlink()
            except Exception: pass


def ytdlp_install_wheel(wheel_url: str, version: str, progress_cb=None) -> tuple[bool, str]:
    """
    Baja el wheel de yt-dlp y lo descomprime en YTDLP_UPDATE_DIR.
    Devuelve (ok, mensaje).
    """
    import tempfile
    import urllib.request
    import zipfile

    def _say(msg, pct=None):
        if progress_cb:
            try:    progress_cb(msg, pct)
            except Exception: pass

    if not wheel_url:
        return False, "PyPI no devolvió un wheel descargable para yt-dlp."

    tmpdir = Path(tempfile.mkdtemp(prefix="akx_ytdlp_"))
    try:
        # 1) Descargar el .whl mostrando progreso
        whl = tmpdir / "yt_dlp.whl"
        _say("Descargando yt-dlp…", 0)
        req = urllib.request.Request(wheel_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=60) as resp, whl.open("wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if total:
                    _say(f"Descargando yt-dlp… {fmt_bytes(got)} / {fmt_bytes(total)}",
                         int(90 * got / total))

        # 2) Descomprimir a un staging (un wheel es un zip común)
        _say("Descomprimiendo…", 92)
        staging = tmpdir / "staging"
        with zipfile.ZipFile(whl) as z:
            z.extractall(staging)

        if not (staging / "yt_dlp" / "version.py").is_file():
            return False, "El paquete descargado no contiene yt_dlp (wheel inválido)."

        # 3) Reemplazar la copia anterior de forma atómica-ish
        _say("Instalando…", 95)
        YTDLP_UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        _clear_ytdlp_dir()
        for item in staging.iterdir():
            shutil.move(str(item), str(YTDLP_UPDATE_DIR / item.name))

        # 4) Sello con la versión instalada
        try:
            YTDLP_STAMP_FILE.write_text(
                json.dumps({"version": version,
                            "installed_at": datetime.now().isoformat(timespec="seconds")},
                           indent=2),
                encoding="utf-8")
        except Exception:
            pass

        _say("Listo", 100)
        return True, f"yt-dlp {version} instalado en {YTDLP_UPDATE_DIR}"
    except Exception as e:
        return False, f"Falló la instalación: {e}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def ytdlp_install_pip(progress_cb=None) -> tuple[bool, str]:
    """
    Actualiza yt-dlp con pip (solo cuando corremos desde el .py: dentro del
    .exe no hay pip y sys.executable sería la propia app).
    Devuelve (ok, mensaje).
    """
    def _say(msg, pct=None):
        if progress_cb:
            try:    progress_cb(msg, pct)
            except Exception: pass

    _say("Ejecutando pip install -U yt-dlp…", 10)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U",
             "--disable-pip-version-check", "yt-dlp"],
            capture_output=True, text=True, timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return False, "pip tardó demasiado (más de 10 minutos) y se canceló."
    except Exception as e:
        return False, f"No se pudo ejecutar pip: {e}"

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = err[-1] if err else f"código {proc.returncode}"
        return False, f"pip falló: {detail}"

    # pip ya dejó la versión buena en site-packages: si había una copia vieja
    # en la carpeta de actualizaciones, sacarla del medio para que no la tape.
    _say("Limpiando copia local…", 90)
    try:
        _clear_ytdlp_dir()
        YTDLP_STAMP_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    _say("Listo", 100)
    return True, "yt-dlp actualizado con pip."


def ytdlp_remove_override() -> tuple[bool, str]:
    """Borra la copia actualizada y vuelve a la que trae la app."""
    try:
        if not YTDLP_UPDATE_DIR.exists():
            return True, "No había ninguna copia local."
        _clear_ytdlp_dir()
        YTDLP_STAMP_FILE.unlink(missing_ok=True)
        return True, "Copia local eliminada."
    except Exception as e:
        return False, str(e)
