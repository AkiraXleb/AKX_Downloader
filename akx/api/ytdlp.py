"""Actualización de yt-dlp desde la UI: chequeo, instalación y reinicio."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import webview

from akx.paths import SCRIPT_DIR, YTDLP_UPDATE_DIR
from akx.ytdlp_engine import (
    ytdlp_current_version,
    ytdlp_override_active,
    ytdlp_override_version,
    ytdlp_pending_version,
    ytdlp_is_newer,
    ytdlp_fetch_latest,
    ytdlp_install_wheel,
    ytdlp_install_pip,
    ytdlp_remove_override,
)


class YtdlpMixin:
    # ---------- Actualización de yt-dlp ----------
    @staticmethod
    def _initial_ytdlp_state() -> dict:
        return {
            "busy":          False,
            "stage":         "idle",   # idle|checking|updating|done|error
            "message":       "",
            "percent":       0,
            "latest":        "",
            "installed":     "",   # versión instalada en esta sesión, si hubo
            "update_available": False,
            "restart_needed": False,
        }

    def _ytdlp_effective_version(self) -> str:
        """
        Versión que va a estar en uso después de reiniciar: la que corre
        ahora, o una más nueva que ya quedó instalada esperando el reinicio.
        Comparar contra esta y no contra la cargada en memoria evita ofrecer
        una y otra vez la actualización que el usuario ya instaló.
        """
        best = ytdlp_current_version()
        for cand in (self._ytdlp_state.get("installed", ""),
                     ytdlp_pending_version()):
            if cand and ytdlp_is_newer(cand, best):
                best = cand
        return best

    def _ytdlp_method(self) -> str:
        """
        Cómo se va a instalar la actualización:
          'pip'   → corriendo desde el .py, hay intérprete con pip
          'wheel' → corriendo desde el .exe, se baja el wheel a DATA_DIR
        """
        return "wheel" if getattr(sys, "frozen", False) else "pip"

    def ytdlp_get_info(self) -> dict:
        """Estado de yt-dlp para pintar la card de Configuración."""
        with self._ytdlp_lock:
            st = dict(self._ytdlp_state)
        current = ytdlp_current_version()
        effective = self._ytdlp_effective_version()
        return {
            "version":        current,
            # Versión ya instalada que se activa al reiniciar ('' si no hay)
            "pending":        effective if effective != current else "",
            "override":       ytdlp_override_active(),
            "override_dir":   str(YTDLP_UPDATE_DIR),
            "local_version":  ytdlp_override_version(),
            "method":         self._ytdlp_method(),
            "auto_check":     bool(self.settings.get("ytdlp_auto_check", True)),
            "state":          st,
        }

    def ytdlp_check_update(self) -> dict:
        """
        Consulta PyPI (bloquea unos segundos, se llama desde JS con await).
        Devuelve {"ok", "current", "latest", "update_available", "error"}.
        """
        current = ytdlp_current_version()
        res = ytdlp_fetch_latest()
        if not res["ok"]:
            with self._ytdlp_lock:
                self._ytdlp_state["latest"] = ""
            return {"ok": False, "current": current, "latest": "", "pending": "",
                    "update_available": False, "error": res["error"]}

        latest = res["version"]
        # Comparar contra la versión que va a quedar activa tras reiniciar,
        # no contra la que está cargada en memoria.
        effective = self._ytdlp_effective_version()
        available = ytdlp_is_newer(latest, effective)
        with self._ytdlp_lock:
            self._ytdlp_state["latest"] = latest
            self._ytdlp_state["update_available"] = available
        return {"ok": True, "current": current, "latest": latest,
                "pending": effective if effective != current else "",
                "update_available": available, "error": ""}

    def ytdlp_update(self) -> dict:
        """Arranca la actualización en un thread. El frontend pollea el estado."""
        with self._ytdlp_lock:
            if self._ytdlp_state["busy"]:
                return {"ok": False, "error": "Ya hay una actualización en curso"}
            # "installed" sobrevive al reset: si ya instalamos algo en esta
            # sesión sigue siendo la versión que va a quedar activa.
            prev_installed = self._ytdlp_state.get("installed", "")
            self._ytdlp_state = self._initial_ytdlp_state()
            self._ytdlp_state.update({
                "busy": True, "stage": "checking",
                "installed": prev_installed,
                "message": "Buscando la última versión…",
            })
        threading.Thread(target=self._ytdlp_worker, daemon=True).start()
        return {"ok": True}

    def _ytdlp_set(self, **kw):
        with self._ytdlp_lock:
            self._ytdlp_state.update(kw)

    def _ytdlp_worker(self):
        try:
            latest_info = ytdlp_fetch_latest()
            if not latest_info["ok"]:
                self._ytdlp_set(busy=False, stage="error", percent=0,
                                message=latest_info["error"])
                return

            latest = latest_info["version"]
            effective = self._ytdlp_effective_version()
            needed = ytdlp_is_newer(latest, effective)
            self._ytdlp_set(latest=latest, update_available=needed)

            if not needed:
                pending = (effective != ytdlp_current_version())
                self._ytdlp_set(
                    busy=False, stage="done", percent=100,
                    restart_needed=pending,
                    message=(f"Ya tenés la última versión ({effective}), "
                             "pendiente de reiniciar."
                             if pending else
                             f"Ya tenés la última versión ({effective})."))
                return

            self._ytdlp_set(stage="updating", percent=0,
                            message=f"Actualizando a {latest}…")

            def _prog(msg, pct=None):
                kw = {"message": msg}
                if pct is not None:
                    kw["percent"] = pct
                self._ytdlp_set(**kw)

            if self._ytdlp_method() == "pip":
                ok, msg = ytdlp_install_pip(_prog)
            else:
                ok, msg = ytdlp_install_wheel(
                    latest_info["wheel_url"], latest, _prog)

            if ok:
                self._ytdlp_set(busy=False, stage="done", percent=100,
                                restart_needed=True, update_available=False,
                                installed=latest,
                                message=f"✔ yt-dlp {latest} instalado. "
                                        "Reiniciá la app para usarlo.")
            else:
                self._ytdlp_set(busy=False, stage="error", percent=0, message=msg)
        except Exception as e:
            self._ytdlp_set(busy=False, stage="error", percent=0,
                            message=f"Error inesperado: {e}")

    def ytdlp_get_update_state(self) -> dict:
        with self._ytdlp_lock:
            return dict(self._ytdlp_state)

    def ytdlp_restore_bundled(self) -> dict:
        """Borra la copia actualizada y vuelve a la que trae la app."""
        with self._ytdlp_lock:
            if self._ytdlp_state["busy"]:
                return {"ok": False, "error": "Hay una actualización en curso"}
        ok, msg = ytdlp_remove_override()
        if ok:
            # Al borrar la copia local dejamos de tener nada "pendiente"
            self._ytdlp_set(stage="done", percent=100, restart_needed=True,
                            update_available=False, installed="",
                            message="Copia local eliminada. Reiniciá la app.")
        return {"ok": ok, "message": msg}

    def restart_app(self) -> dict:
        """
        Relanza la app (necesario para que tome la nueva versión de yt-dlp,
        porque el módulo ya está importado en memoria).
        """
        try:
            if getattr(sys, "frozen", False):
                args = [sys.executable]
            else:
                args = [sys.executable, str(Path(__file__).resolve())]
            subprocess.Popen(args, cwd=str(SCRIPT_DIR), close_fds=True)
        except Exception as e:
            return {"ok": False, "error": f"No se pudo relanzar: {e}"}

        def _close():
            time.sleep(0.6)
            try:
                if webview.windows:
                    webview.windows[0].destroy()
            except Exception:
                pass

        threading.Thread(target=_close, daemon=True).start()
        return {"ok": True}

