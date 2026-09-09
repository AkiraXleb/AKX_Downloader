"""
Servidor HTTP local (127.0.0.1) que sirve archivos multimedia para el
reproductor HTML5 embebido, autenticado por token y con soporte de Range
requests para que <video>/<audio> puedan hacer seek.
"""
from __future__ import annotations

import mimetypes
import re
import secrets
import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# =====================================================================
class FileServer:
    """
    Sirve archivos locales por HTTP en 127.0.0.1, autenticados por token.
    Soporta Range requests para que <video> pueda hacer seek.
    """
    def __init__(self):
        self.tokens: dict[str, str] = {}      # token -> ruta
        self.path_to_token: dict[str, str] = {}  # ruta -> token (para reuso)
        self._lock = threading.Lock()
        self.port = self._free_port()
        self._start_server()

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def register(self, file_path: str) -> str:
        path = str(Path(file_path).resolve())
        with self._lock:
            if path in self.path_to_token:
                tok = self.path_to_token[path]
            else:
                tok = secrets.token_urlsafe(16)
                self.tokens[tok] = path
                self.path_to_token[path] = tok
        return f"http://127.0.0.1:{self.port}/f/{tok}"

    def lookup(self, token: str) -> str | None:
        with self._lock:
            return self.tokens.get(token)

    def _start_server(self):
        server = self
        mimetypes.add_type("audio/x-m4a", ".m4a")
        mimetypes.add_type("audio/mp4", ".m4a")
        mimetypes.add_type("video/webm", ".webm")
        mimetypes.add_type("video/x-matroska", ".mkv")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args, **_kwargs):
                return  # silencio total

            def do_GET(self):
                if not self.path.startswith("/f/"):
                    self.send_error(404); return
                token = self.path[3:].split("?", 1)[0]
                fpath = server.lookup(token)
                if not fpath or not Path(fpath).exists():
                    self.send_error(404); return
                self._serve(Path(fpath))

            def do_HEAD(self):
                if not self.path.startswith("/f/"):
                    self.send_error(404); return
                token = self.path[3:].split("?", 1)[0]
                fpath = server.lookup(token)
                if not fpath or not Path(fpath).exists():
                    self.send_error(404); return
                size = Path(fpath).stat().st_size
                ctype = mimetypes.guess_type(str(fpath))[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

            def _serve(self, path: Path):
                size = path.stat().st_size
                ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
                rng = self.headers.get("Range")
                if rng:
                    m = re.match(r"bytes=(\d+)-(\d*)", rng)
                    if m:
                        start = int(m.group(1))
                        end = int(m.group(2)) if m.group(2) else size - 1
                        end = min(end, size - 1)
                        if start > end:
                            self.send_error(416); return
                        length = end - start + 1
                        self.send_response(206)
                        self.send_header("Content-Type", ctype)
                        self.send_header("Content-Length", str(length))
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                        self.send_header("Accept-Ranges", "bytes")
                        self.end_headers()
                        try:
                            with path.open("rb") as f:
                                f.seek(start)
                                remaining = length
                                while remaining > 0:
                                    chunk = f.read(min(64 * 1024, remaining))
                                    if not chunk:
                                        break
                                    self.wfile.write(chunk)
                                    remaining -= len(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            return
                        return

                # Sin Range: fichero completo
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                try:
                    with path.open("rb") as f:
                        shutil.copyfileobj(f, self.wfile, length=64 * 1024)
                except (BrokenPipeError, ConnectionResetError):
                    return

        httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()


# =====================================================================
