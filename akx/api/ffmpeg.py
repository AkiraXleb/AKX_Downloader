"""Detección, sondeo y configuración manual de FFmpeg (métodos de la API)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import webview

from akx.settings import save_settings


class FfmpegMixin:
    def _detect_ffmpeg(self) -> str | None:
        """
        Devuelve la ruta al ejecutable de FFmpeg, priorizando:
        1) La ruta manual configurada por el usuario en settings
        2) ffmpeg en el PATH del sistema
        Devuelve None si no se encuentra en ninguno de los dos lados.
        """
        # 1) Ruta manual de settings
        manual = (self.settings.get("ffmpeg_path") or "").strip() if hasattr(self, "settings") else ""
        if manual:
            p = Path(manual)
            if p.exists() and p.is_file():
                return str(p)
            # Si guardaron una carpeta en vez del .exe, intentar componerlo
            if p.is_dir():
                for candidate in ("ffmpeg.exe", "ffmpeg"):
                    if (p / candidate).is_file():
                        return str(p / candidate)
        # 2) Fallback al PATH del sistema
        return shutil.which("ffmpeg")

    def _guess_ffmpeg_install_dir(self) -> str:
        """
        Intenta localizar la carpeta donde está ffmpeg.exe en el sistema,
        para que el diálogo de selección arranque cerca del archivo correcto.
        Busca en ubicaciones típicas de instaladores comunes (winget, choco, scoop)
        y devuelve la primera carpeta donde encuentra el binario.
        """
        if not sys.platform.startswith("win"):
            return ""

        home = Path.home()
        # Lista de carpetas candidatas (raíces) donde buscar recursivamente
        # de forma limitada (no queremos escanear todo el disco).
        candidates_roots = [
            home / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages",
            Path("C:/ProgramData/chocolatey/lib"),
            home / "scoop" / "apps" / "ffmpeg",
            Path("C:/ffmpeg"),
            Path("C:/Program Files/ffmpeg"),
        ]

        for root in candidates_roots:
            if not root.exists() or not root.is_dir():
                continue
            try:
                # Búsqueda limitada (max 4 niveles de profundidad)
                # Usamos rglob pero con timeout via cantidad para no colgar
                count = 0
                for ffmpeg_exe in root.rglob("ffmpeg.exe"):
                    count += 1
                    if count > 50:  # límite de seguridad
                        break
                    if ffmpeg_exe.is_file():
                        return str(ffmpeg_exe.parent)
            except Exception:
                continue

        return ""

    def _probe_ffmpeg(self, path: str) -> tuple[bool, str]:
        """
        Verifica que el binario de FFmpeg responda y devuelve (ok, versión).
        Útil para confirmar que la ruta elegida por el usuario es válida.
        """
        if not path:
            return False, ""
        p = Path(path)
        if not p.exists() or not p.is_file():
            return False, ""
        try:
            result = subprocess.run(
                [str(p), "-version"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                # Primera línea: "ffmpeg version N.N.N ..."
                first = (result.stdout or "").split("\n", 1)[0].strip()
                return True, first
        except Exception:
            pass
        return False, ""


    # ---------- FFmpeg manual ----------
    def browse_ffmpeg_file(self) -> dict:
        """
        Abre un diálogo para que el usuario seleccione el ejecutable de FFmpeg.
        Valida el archivo y, si es correcto, lo guarda en settings y lo activa.
        Devuelve {"ok": bool, "path": str, "version": str, "error": str}.
        """
        if not webview.windows:
            return {"ok": False, "error": "No hay ventana activa"}

        # Filtros del diálogo: PyWebView usa formato "Descripción (*.ext;*.ext)"
        # con patrones glob obligatorios dentro de los paréntesis.
        is_windows = sys.platform.startswith("win")
        if is_windows:
            file_types = (
                "Ejecutables (*.exe)",
                "Todos los archivos (*.*)",
            )
        else:
            file_types = ("Todos los archivos (*.*)",)

        # Carpeta inicial: la actual del setting si existe, sino buscar dónde
        # winget instaló FFmpeg para llevarnos directo a la carpeta correcta.
        current = (self.settings.get("ffmpeg_path") or "").strip()
        if current and Path(current).exists():
            initial_dir = str(Path(current).parent)
        else:
            initial_dir = self._guess_ffmpeg_install_dir()
            if not initial_dir:
                initial_dir = str(Path.home())

        try:
            result = webview.windows[0].create_file_dialog(
                webview.OPEN_DIALOG,
                directory=initial_dir,
                file_types=file_types,
                allow_multiple=False,
            )
        except Exception as e:
            return {"ok": False, "error": f"Error al abrir diálogo: {e}"}

        if not result:
            return {"ok": False, "error": "Cancelado"}
        chosen = result[0] if isinstance(result, (list, tuple)) else result

        return self.set_ffmpeg_path(chosen)

    def set_ffmpeg_path(self, path: str) -> dict:
        """
        Valida una ruta a FFmpeg, la guarda en settings y la activa.
        Si la ruta apunta a una carpeta, busca ffmpeg.exe / ffmpeg adentro.
        """
        path = (path or "").strip()
        if not path:
            return {"ok": False, "error": "Ruta vacía"}

        p = Path(path)
        # Si pasaron una carpeta, intentar resolver al binario
        if p.is_dir():
            for name in ("ffmpeg.exe", "ffmpeg"):
                if (p / name).is_file():
                    p = p / name
                    break
            else:
                return {"ok": False,
                        "error": "La carpeta seleccionada no contiene ffmpeg.exe ni ffmpeg"}

        if not p.exists() or not p.is_file():
            return {"ok": False, "error": "El archivo no existe"}

        # Validar que es realmente FFmpeg (no cualquier .exe random)
        ok, version = self._probe_ffmpeg(str(p))
        if not ok:
            return {"ok": False,
                    "error": "El archivo no responde como FFmpeg válido. "
                             "¿Seguro que es ffmpeg.exe?"}

        # Guardar en settings y activar
        self.settings["ffmpeg_path"] = str(p)
        save_settings(self.settings)
        self.ffmpeg_path = str(p)
        return {"ok": True, "path": str(p), "version": version}

    def clear_ffmpeg_path(self) -> dict:
        """
        Borra la ruta manual y vuelve a usar el PATH del sistema.
        """
        self.settings["ffmpeg_path"] = ""
        save_settings(self.settings)
        self.ffmpeg_path = self._detect_ffmpeg()
        ok, version = (False, "")
        if self.ffmpeg_path:
            ok, version = self._probe_ffmpeg(self.ffmpeg_path)
        return {
            "ok": True,
            "path": self.ffmpeg_path or "",
            "version": version if ok else "",
            "found_in_path": bool(self.ffmpeg_path),
        }

    def autodetect_ffmpeg(self) -> dict:
        """
        Busca proactivamente ffmpeg.exe en ubicaciones típicas (winget,
        chocolatey, scoop, etc.) y devuelve la primera ruta válida encontrada.
        El frontend puede ofrecerle al usuario aplicarla con un click.
        """
        if self.ffmpeg_path:
            return {"found": True, "path": self.ffmpeg_path,
                    "already_configured": True}

        guess_dir = self._guess_ffmpeg_install_dir()
        if not guess_dir:
            return {"found": False, "path": ""}

        candidate = Path(guess_dir) / "ffmpeg.exe"
        if not candidate.is_file():
            return {"found": False, "path": ""}

        ok, version = self._probe_ffmpeg(str(candidate))
        if not ok:
            return {"found": False, "path": ""}

        return {
            "found": True,
            "path": str(candidate),
            "version": version,
            "already_configured": False,
        }

