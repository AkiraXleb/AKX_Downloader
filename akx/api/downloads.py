"""
Orquestación de descargas: yt-dlp (+ playlists), Telegram, post-procesado
(HEVC→H.264, renombrado inteligente, sincronización de tags) y limpieza
por lotes de una carpeta.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import yt_dlp

from akx.cookies import cookies_present
from akx.naming import (
    clean_title,
    sanitize_filename_part,
    build_name_from_metadata,
    reorder_to_artist_first,
    _RE_YT_ID,
)
from akx.paths import COOKIES_FILE, MEDIA_EXTS, VIDEO_EXTS
from akx.settings import SUPPORTED_BROWSERS
from akx.telegram import parse_telegram_url, TelegramDownloader, _load_telethon
from akx.utils import fmt_bytes


class DownloadMixin:
    @staticmethod
    def _initial_state() -> dict:
        return {
            "is_downloading": False,
            "title": "",
            "thumbnail_url": "",
            "frac": 0.0,
            "downloaded": 0,
            "total": 0,
            "speed": 0,
            "eta": 0,
            "status": "idle",         # idle|starting|downloading|processing|complete|error|cancelled
            "status_text": "",
            "error_hint": "",
            "error_code": "",
            "format": "",
            # Playlist info
            "is_playlist": False,
            "playlist_title": "",
            "playlist_index": 0,
            "playlist_count": 0,
            "playlist_completed": 0,  # videos terminados con éxito
            # Cola de reordenamientos pendientes de mostrar al frontend.
            # El JS los consume con get_state y luego llama a clear_recent_reorders().
            "recent_reorders": [],    # lista de {"from": "...", "to": "..."}
        }


    # ---------- Estado (polling) ----------
    def get_state(self) -> dict:
        return self.current_state

    def clear_recent_reorders(self) -> bool:
        """Limpia la cola de reorders después de que el frontend los mostró."""
        try:
            self.current_state["recent_reorders"] = []
        except Exception:
            pass
        return True


    # ---------- Descarga ----------
    def _dir_for_format(self, fmt: str) -> Path:
        """Devuelve la carpeta destino correcta según el formato (mp3 vs mp4)."""
        if fmt == "mp3":
            d = self.settings.get("download_dir_audio")
        else:
            d = self.settings.get("download_dir_video")
        # Fallback al legacy o a Downloads
        if not d:
            d = self.settings.get("download_dir") or str(Path.home() / "Downloads")
        return Path(d)

    def start_download(self, url: str, fmt: str) -> dict:
        if self.is_downloading:
            return {"ok": False, "error": "Ya hay una descarga en curso"}
        url = (url or "").strip()
        if not url:
            return {"ok": False, "error": "Pega una URL primero"}
        out_dir = self._dir_for_format(fmt)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return {"ok": False, "error": f"Carpeta inválida: {e}"}
        if fmt == "mp3" and not self.ffmpeg_path:
            return {"ok": False,
                    "error": "MP3 requiere FFmpeg, no se detectó en PATH"}

        self.is_downloading = True
        self.cancel_event.clear()
        self.current_state = self._initial_state()
        self.current_state.update({
            "is_downloading": True,
            "title": "Preparando…",
            "status": "starting",
            "status_text": "Resolviendo información…",
            "format": fmt,
        })
        self._current_video_id = None
        self._current_outdir = out_dir
        self._video_metadata = {}
        threading.Thread(target=self._worker, args=(url, fmt, out_dir),
                         daemon=True).start()
        return {"ok": True}

    def cancel_download(self) -> bool:
        if not self.is_downloading:
            return False
        self.cancel_event.set()
        self.current_state["status_text"] = "Cancelando…"
        return True

    def _delete_partial_files(self, out_dir: Path, video_id: str | None) -> int:
        """Borra archivos asociados al ID actual (incluye .part, .ytdl, finales recién creados)."""
        if not video_id or not out_dir.exists():
            return 0
        deleted = 0
        # yt-dlp escribe nombres tipo: "Title [VIDEOID].ext" y "Title [VIDEOID].fXXX.ext.part"
        for f in out_dir.glob(f"*{video_id}*"):
            try:
                # Margen de seguridad: solo si fue tocado en las últimas 2h
                if time.time() - f.stat().st_mtime < 7200:
                    f.unlink()
                    deleted += 1
            except Exception:
                pass
        return deleted

    def _worker_telegram(self, tg_url: dict, orig_url: str, out_dir: Path):
        """Worker específico para descargas via Telethon (grupos privados)."""
        try:
            api_id = int((self.settings.get("telegram_api_id") or "").strip())
            api_hash = (self.settings.get("telegram_api_hash") or "").strip()
        except ValueError:
            self.current_state.update({
                "status": "error",
                "status_text": "API ID de Telegram inválido",
                "is_downloading": False,
            })
            self.is_downloading = False
            return

        try:
            _load_telethon()
        except Exception:
            self.current_state.update({
                "status": "error",
                "status_text": ("Telethon no está instalado. Ejecuta: "
                                 "pip install telethon"),
                "is_downloading": False,
            })
            self.is_downloading = False
            return

        tg = TelegramDownloader(api_id, api_hash)
        if not tg.is_authorized():
            self.current_state.update({
                "status": "error",
                "status_text": ("Sesión de Telegram no iniciada. Ve a Cuenta → "
                                 "Telegram y logueate."),
                "is_downloading": False,
            })
            self.is_downloading = False
            return

        # Resolver chat_ref
        if tg_url["kind"] == "private":
            # Telegram usa -100 + chat_id decimal para grupos/canales privados
            chat_ref = int(f"-100{tg_url['chat']}")
        else:
            chat_ref = tg_url["chat"]  # username

        self.current_state.update({
            "title":       "Telegram · resolviendo mensaje…",
            "status":      "downloading",
            "status_text": "Conectando a Telegram…",
            "format":      "video",  # provisional; puede ser cualquier archivo
        })

        # Callback de progreso
        def _prog(current, total):
            if total <= 0: return
            pct = min(100, int(100 * current / total))
            self.current_state.update({
                "percent":     pct,
                "downloaded":  current,
                "total":       total,
                "status_text": (f"Descargando de Telegram… "
                                 f"{fmt_bytes(current)} / {fmt_bytes(total)}"),
                "speed":       0,   # Telethon no expone velocidad directa
                "eta":         0,
            })

        try:
            path = tg.download_message(
                chat_ref, tg_url["msg"], out_dir,
                progress_cb=_prog, cancel_event=self.cancel_event
            )
            if not path:
                raise RuntimeError("El mensaje no tiene archivo descargable.")
        except asyncio.CancelledError:
            self.current_state.update({
                "status": "cancelled",
                "status_text": "Descarga cancelada",
                "is_downloading": False,
            })
            self.is_downloading = False
            return
        except Exception as e:
            self.current_state.update({
                "status": "error",
                "status_text": f"Error de Telegram: {e}",
                "is_downloading": False,
            })
            self.is_downloading = False
            return

        # Ejecutar el post-hook para HEVC→H.264 y renombrado, igual que yt-dlp
        try:
            self._post_hook(path)
        except Exception:
            pass

        p = Path(path)
        # Agregar al historial
        try:
            self._add_history({
                "id":       f"tg_{tg_url['chat']}_{tg_url['msg']}",
                "title":    p.stem,
                "artist":   "Telegram",
                "url":      orig_url,
                "format":   p.suffix.lstrip("."),
                "filepath": str(p),
                "filename": p.name,
                "size":     p.stat().st_size if p.exists() else 0,
                "when":     datetime.now().isoformat(timespec="seconds"),
                "source":   "telegram",
            })
        except Exception:
            pass

        self.current_state.update({
            "status": "done",
            "status_text": f"✓ Descargado: {p.name}",
            "percent": 100,
            "final_path": str(p),
            "is_downloading": False,
        })
        self.is_downloading = False

    def _worker(self, url: str, fmt: str, out_dir: Path):
        # PASO PREVIO: si es URL de Telegram y hay credenciales, usar Telethon
        tg_url = parse_telegram_url(url)
        if tg_url:
            api_id = (self.settings.get("telegram_api_id") or "").strip()
            api_hash = (self.settings.get("telegram_api_hash") or "").strip()
            if api_id and api_hash:
                return self._worker_telegram(tg_url, url, out_dir)
            # Sin credenciales: seguimos con yt-dlp (funcionará solo si es público)

        info: dict | None = None
        final_path: Path | None = None
        try:
            # 1) Probe rápido. Para playlists usamos extract_flat para evitar
            #    resolver cada video uno por uno (eso colgaba minutos en playlists grandes).
            try:
                self.current_state["status_text"] = "Resolviendo información…"
                probe_opts = {
                    "quiet": True, "no_warnings": True, "skip_download": True,
                    "extract_flat": "in_playlist",  # <- clave: lista videos sin probe individual
                }
                # Cookies: prioridad navegador > archivo cookies.txt
                browser = (self.settings.get("cookies_browser") or "").strip().lower()
                if browser in SUPPORTED_BROWSERS:
                    probe_opts["cookiesfrombrowser"] = (browser,)
                elif cookies_present():
                    probe_opts["cookiefile"] = str(COOKIES_FILE)
                with yt_dlp.YoutubeDL(probe_opts) as probe:
                    info = probe.extract_info(url, download=False)

                if info:
                    is_playlist = info.get("_type") == "playlist" or bool(info.get("entries"))
                    if is_playlist:
                        entries = list(info.get("entries") or [])
                        self.current_state.update({
                            "is_playlist": True,
                            "playlist_title": info.get("title") or "Playlist",
                            "playlist_count": len(entries),
                            "playlist_index": 0,
                            "playlist_completed": 0,
                            "title": f"{info.get('title') or 'Playlist'} · {len(entries)} videos",
                            "status_text": f"Playlist detectada · {len(entries)} videos",
                        })
                        # Thumbnail del primer video si está disponible
                        first_thumb = ""
                        if entries:
                            first = entries[0]
                            first_thumb = (first.get("thumbnail")
                                           or (first.get("thumbnails") or [{}])[-1].get("url", ""))
                            if not first_thumb and first.get("id"):
                                first_thumb = f"https://i.ytimg.com/vi/{first['id']}/mqdefault.jpg"
                        if first_thumb:
                            self.current_state["thumbnail_url"] = first_thumb
                    else:
                        # Video único
                        self._current_video_id = info.get("id")
                        self.current_state["title"] = info.get("title") or "—"
                        if info.get("thumbnail"):
                            self.current_state["thumbnail_url"] = info["thumbnail"]
                        elif info.get("id"):
                            self.current_state["thumbnail_url"] = f"https://i.ytimg.com/vi/{info['id']}/mqdefault.jpg"
            except Exception:
                pass  # no fatal

            if self.cancel_event.is_set():
                raise yt_dlp.utils.DownloadError("Cancelado por el usuario")

            # 2) Descarga real
            opts = self._build_opts(fmt, out_dir)
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            # 3) Localizar el archivo final (último; en playlist será el último video bajado)
            final_path = self._guess_final_file(out_dir, fmt)
            size = final_path.stat().st_size if final_path and final_path.exists() else None

            # Mensaje final adaptado a playlist vs video único
            if self.current_state.get("is_playlist"):
                done = self.current_state.get("playlist_completed", 0)
                total = self.current_state.get("playlist_count", 0)
                self.current_state.update({
                    "frac": 1.0, "status": "complete",
                    "status_text": f"✔ Playlist completa · {done} de {total} videos descargados",
                })
            else:
                self.current_state.update({
                    "frac": 1.0, "status": "complete",
                    "status_text": "✔ Descarga completada",
                })
                # Solo agregamos al historial el video único acá; los de playlist
                # se agregaron en _post_hook video por video.
                self._add_history({
                    "status": "complete",
                    "title":  (info or {}).get("title") or (final_path.stem if final_path else url),
                    "filepath": str(final_path) if final_path else None,
                    "dir": str(out_dir),
                    "format": fmt, "size_bytes": size,
                })

        except yt_dlp.utils.DownloadError as e:
            if self.cancel_event.is_set():
                deleted = self._delete_partial_files(out_dir, self._current_video_id)
                self.current_state.update({
                    "status": "cancelled",
                    "status_text": f"Cancelado · {deleted} archivo(s) parciales eliminados",
                })
                self._add_history({
                    "status": "cancelled",
                    "title": (info or {}).get("title") or url,
                    "filepath": None, "dir": str(out_dir),
                    "format": fmt, "size_bytes": None,
                })
            else:
                err_msg, hint, code = self._diagnose_error(str(e))
                self.current_state.update({
                    "status": "error",
                    "status_text": err_msg,
                    "error_hint": hint,
                    "error_code": code,
                })
                self._add_history({
                    "status": "error",
                    "title": (info or {}).get("title") or url,
                    "filepath": None, "dir": str(out_dir),
                    "format": fmt, "size_bytes": None,
                })
        except Exception as e:
            self.current_state.update({
                "status": "error",
                "status_text": f"Error inesperado: {e}",
                "error_hint": "Revisá la consola para más detalles.",
                "error_code": "unexpected",
            })
            traceback.print_exc()
        finally:
            self.is_downloading = False
            self.current_state["is_downloading"] = False

    def _diagnose_error(self, raw: str) -> tuple[str, str, str]:
        """
        Convierte el error de yt-dlp en (mensaje_corto, sugerencia, codigo).
        El código permite al frontend reaccionar (p.ej. "needs_auth" → mostrar botón "Iniciar sesión").
        """
        low = raw.lower()
        has_cookies = cookies_present()

        # YouTube exige autenticación
        if any(s in low for s in [
            "sign in to confirm", "sign in to confirm you're not a bot",
            "private video", "members-only", "this video is available to",
            "video is unavailable", "join this channel",
            "age-restricted", "age restricted", "confirm your age",
            "login required",
        ]):
            if has_cookies:
                hint = ("Tus cookies pueden estar caducadas o no corresponden "
                        "a una cuenta con acceso a este video. Andá a Cuenta y "
                        "volvé a pegar cookies frescas.")
                code = "auth_failed"
            else:
                hint = ("Este video requiere iniciar sesión. Andá a la sección "
                        "Cuenta del menú lateral y pegá tus cookies de YouTube.")
                code = "needs_auth"
            return "YouTube exige autenticación para este video.", hint, code

        # Bot detection
        if "bot" in low and ("detected" in low or "confirm" in low):
            code = "auth_failed" if has_cookies else "needs_auth"
            return ("YouTube te pide verificar que no sos un bot.",
                    "Iniciá sesión desde la página Cuenta para pasar la verificación.",
                    code)

        # 403
        if "403" in low or "forbidden" in low:
            return ("Acceso denegado (HTTP 403).",
                    "Suele pasar cuando el motor de descarga quedó viejo. "
                    "Actualizá yt-dlp desde Configuración → Motor de descarga.",
                    "forbidden")

        # FFmpeg
        if "ffmpeg" in low or "postprocessor" in low:
            return ("Falta FFmpeg o falló la conversión.",
                    "Instalá FFmpeg y agregalo al PATH del sistema. "
                    "En Windows podés usar: winget install Gyan.FFmpeg",
                    "no_ffmpeg")

        # No format
        if "requested format" in low or "no video formats" in low:
            return ("No se encontró un formato compatible.",
                    "Probá la otra opción (MP3 ↔ MP4) o cambiá la calidad en Configuración.",
                    "no_format")

        # Red
        if any(s in low for s in ["timeout", "timed out", "name resolution",
                                  "network", "connection", "unreachable"]):
            return ("Problema de conexión.",
                    "Verificá tu internet y volvé a intentar.",
                    "network")

        # Geobloqueado
        if "geoblock" in low or "not available in your country" in low:
            return ("Video no disponible en tu región.",
                    "Necesitarías una VPN o proxy para acceder.",
                    "geoblocked")

        # Genérico — primer línea sin tracebacks
        first_line = raw.strip().split("\n")[0]
        if len(first_line) > 200:
            first_line = first_line[:200] + "…"
        return (first_line, "Revisá la URL e intentá de nuevo.", "generic")

    def _build_opts(self, fmt: str, out_dir: Path) -> dict:
        outtmpl = str(out_dir / "%(title)s [%(id)s].%(ext)s")
        opts: dict = {
            "outtmpl": outtmpl,
            "noprogress": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._progress_hook],
            "post_hooks": [self._post_hook],
            "retries": 5,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": 4,
            "windowsfilenames": os.name == "nt",
        }
        if self.ffmpeg_path:
            opts["ffmpeg_location"] = self.ffmpeg_path
        # Cookies: prioridad navegador > archivo cookies.txt
        browser = (self.settings.get("cookies_browser") or "").strip().lower()
        if browser in SUPPORTED_BROWSERS:
            opts["cookiesfrombrowser"] = (browser,)
        elif cookies_present():
            opts["cookiefile"] = str(COOKIES_FILE)

        if fmt == "mp3":
            kbps = self.settings.get("audio_kbps", "320")
            opts.update({
                "format": "bestaudio/best",
                "writethumbnail": True,
                "postprocessors": [
                    {"key": "FFmpegExtractAudio",
                     "preferredcodec": "mp3", "preferredquality": kbps},
                    {"key": "FFmpegMetadata"},
                    {"key": "EmbedThumbnail", "already_have_thumbnail": False},
                ],
            })
        else:
            vq = self.settings.get("video_quality", "best")
            # Preferencia: H.264 (avc1) en MP4 > cualquier MP4 > lo mejor disponible.
            # Evita descargar HEVC/H.265 que el reproductor de Windows no reproduce nativamente.
            if vq == "best":
                fstr = (
                    "bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/"
                    "bv*[ext=mp4]+ba[ext=m4a]/"
                    "bv*+ba/best"
                )
            else:
                fstr = (
                    f"bv*[vcodec^=avc1][ext=mp4][height<={vq}]+ba[ext=m4a]/"
                    f"bv*[ext=mp4][height<={vq}]+ba[ext=m4a]/"
                    f"bv*[height<={vq}]+ba/best[height<={vq}]"
                )
            opts.update({
                "format": fstr,
                "merge_output_format": "mp4",
                "postprocessors": [{"key": "FFmpegMetadata"}],
            })
        return opts

    def _progress_hook(self, d: dict):
        if self.cancel_event.is_set():
            raise yt_dlp.utils.DownloadError("Cancelado por el usuario")
        st = d.get("status")
        info = d.get("info_dict") or {}

        # Detectar progreso de playlist (yt-dlp pone playlist_index en info_dict
        # cuando la URL es una playlist, incluso después del extract_flat)
        pl_idx = info.get("playlist_index")
        pl_count = (info.get("n_entries") or info.get("playlist_count")
                    or self.current_state.get("playlist_count") or 0)
        if pl_idx and self.current_state.get("is_playlist"):
            self.current_state["playlist_index"] = pl_idx
            if pl_count:
                self.current_state["playlist_count"] = pl_count

        # Thumbnail del video actual (cambia en cada video de la playlist)
        if info.get("id"):
            self._current_video_id = info["id"]
            new_thumb = (info.get("thumbnail")
                         or f"https://i.ytimg.com/vi/{info['id']}/mqdefault.jpg")
            if self.current_state.get("thumbnail_url") != new_thumb:
                self.current_state["thumbnail_url"] = new_thumb

            # Cachear metadatos para usarlos en el renombrado del post_hook.
            # yt-dlp completa estos campos en YouTube (especialmente Music).
            self._video_metadata[info["id"]] = {
                "id":       info.get("id"),
                "title":    info.get("title"),
                "artist":   info.get("artist"),
                "track":    info.get("track"),
                "creator":  info.get("creator"),
                "composer": info.get("composer"),
                "uploader": info.get("uploader"),
                "album":    info.get("album"),
                "release_year": info.get("release_year"),
            }
        if info.get("title"):
            self.current_state["title"] = info["title"]

        if st == "downloading":
            total      = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            self.current_state.update({
                "frac": (downloaded / total) if total else 0,
                "downloaded": downloaded,
                "total": total,
                "speed": d.get("speed") or 0,
                "eta": d.get("eta") or 0,
                "status": "downloading",
                "status_text": "",
            })
        elif st == "finished":
            self.current_state.update({
                "frac": 1.0, "status": "processing",
                "status_text": "Procesando…",
            })

    def _ensure_h264(self, filepath: str) -> str:
        """
        Si el video descargado está en HEVC/H.265, lo re-encoda a H.264 in-place
        para máxima compatibilidad (Windows Media Player, celulares viejos, etc.).
        No toca videos que ya vengan en H.264 u otros formatos compatibles.
        """
        try:
            if not self.settings.get("auto_convert_hevc", True):
                return filepath
            p = Path(filepath)
            if not p.exists() or p.suffix.lower() not in VIDEO_EXTS:
                return filepath

            # Localizar ffprobe (viene en el mismo dir que ffmpeg)
            if self.ffmpeg_path:
                ffprobe = str(Path(self.ffmpeg_path).parent / (
                    "ffprobe.exe" if os.name == "nt" else "ffprobe"))
                if not Path(ffprobe).exists():
                    ffprobe = "ffprobe"
                ffmpeg_exe = self.ffmpeg_path
            else:
                ffprobe = "ffprobe"
                ffmpeg_exe = "ffmpeg"

            no_window = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

            # 1) Leer códec de video con ffprobe
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name",
                 "-of", "default=nw=1:nk=1", str(p)],
                capture_output=True, text=True, timeout=30,
                creationflags=no_window,
            )
            codec = (probe.stdout or "").strip().lower()
            # Códecs que Windows Media Player NO reproduce nativamente
            needs_convert = codec in ("hevc", "h265", "x265", "av1", "vp9")
            if not needs_convert:
                return filepath

            # 2) Re-encode a H.264 + AAC (contenedor MP4)
            self.current_state["status_text"] = (
                f"Convirtiendo {codec.upper()} → H.264 para compatibilidad…")
            temp = p.with_name(p.stem + ".__h264__" + p.suffix)
            enc = subprocess.run(
                [ffmpeg_exe, "-y", "-i", str(p),
                 "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                 "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart",
                 str(temp)],
                capture_output=True, text=True, timeout=1800,
                creationflags=no_window,
            )

            if enc.returncode == 0 and temp.exists() and temp.stat().st_size > 0:
                try:
                    p.unlink()
                    temp.rename(p)
                except Exception:
                    # Si falla el rename, borrar el temp y quedarnos con el original
                    try: temp.unlink()
                    except Exception: pass
            else:
                # Si falla el encode, quedarse con el HEVC original
                try:
                    if temp.exists(): temp.unlink()
                except Exception:
                    pass
            return str(p)
        except Exception:
            return filepath

    def _post_hook(self, filename: str):
        try:
            # PRIMERO: si el video es HEVC/H.265, convertirlo a H.264 antes de
            # cualquier otra cosa (así el renombrado y demás opera sobre el final)
            filename = self._ensure_h264(filename)
            p = Path(filename)
            if not p.exists():
                return
            ext = p.suffix.lower()
            is_video_file = ext in VIDEO_EXTS

            # Si es un video y la opción "limpiar nombres de video" está apagada,
            # NO renombramos ni tocamos los tags. Los videos suelen ser contenido
            # descriptivo (tutoriales, gameplays, podcasts) cuyo título original
            # ya es útil tal cual está.
            skip_for_video = is_video_file and not self.settings.get(
                "clean_video_names", False
            )

            # 1) Renombrado inteligente: si tenemos metadatos de yt-dlp,
            #    intentamos construir "Artista - Título" desde los campos
            #    artist/track. Si no, caemos a clean_title() tradicional.
            if (self.settings.get("auto_clean_names", True)
                    and ext in MEDIA_EXTS
                    and not skip_for_video):
                # Extraer ID del nombre actual: "Title [VIDEOID].ext"
                video_id = None
                m = re.search(r"\[([A-Za-z0-9_-]{11})\]", p.stem)
                if m:
                    video_id = m.group(1)
                meta = self._video_metadata.get(video_id) if video_id else None

                # Estrategia 1: usar metadata si tenemos artist + track
                new_stem = None
                if meta and (meta.get("artist") and meta.get("track")):
                    new_stem = build_name_from_metadata(meta)
                # Estrategia 2: limpieza regex sobre el nombre actual
                if not new_stem:
                    new_stem = clean_title(p.stem)

                # Estrategia 3: si el resultado tiene formato "Título | Artista"
                # o "Título - Artista" y conocemos el artist via meta, reordenamos
                # a "Artista - Título" (formato más estándar)
                reorder_from = None
                reorder_to = None
                if meta and meta.get("artist"):
                    candidate, was_reordered = reorder_to_artist_first(new_stem, meta["artist"])
                    if was_reordered:
                        reorder_from = new_stem
                        reorder_to = candidate
                        new_stem = candidate

                new_name = sanitize_filename_part(new_stem) + p.suffix

                if new_name and new_name != p.name:
                    target = p.with_name(new_name)
                    if target != p:
                        stem, ext = Path(new_name).stem, p.suffix
                        n = 1
                        while target.exists():
                            target = p.with_name(f"{stem} ({n}){ext}")
                            n += 1
                    try:
                        p.rename(target)
                        p = target
                        # Si hubo reorder, anunciarlo al frontend para toast
                        if reorder_from and reorder_to:
                            self._enqueue_reorder(reorder_from, reorder_to)
                    except Exception:
                        pass

                # 1.b) Sincronizar tags ID3/MP4 con el nuevo nombre.
                #      yt-dlp embebe los tags ANTES del post_hook, así que el
                #      título/artista guardados en el archivo todavía pueden
                #      tener "Official Video", "Videoclip Oficial", etc.
                #      Los limpiamos para que coincidan con el nombre del archivo.
                self._sync_audio_tags(p, meta)
            elif skip_for_video:
                # Para videos sin limpieza completa, igual quitamos SOLO el ID
                # de YouTube al final del nombre (ej. "Video Tutorial [Abc123Xyz].mp4")
                # porque ese ID nunca es deseable en el nombre, no es parte del título.
                stem_no_id = _RE_YT_ID.sub("", p.stem).rstrip()
                if stem_no_id and stem_no_id != p.stem:
                    new_name = sanitize_filename_part(stem_no_id) + p.suffix
                    if new_name != p.name:
                        target = p.with_name(new_name)
                        if target != p:
                            stem, ext = Path(new_name).stem, p.suffix
                            n = 1
                            while target.exists():
                                target = p.with_name(f"{stem} ({n}){ext}")
                                n += 1
                        try:
                            p.rename(target)
                            p = target
                        except Exception:
                            pass

            # 2) Si es playlist, agregar este archivo al historial
            #    (cada video de la playlist queda como entrada separada)
            if self.current_state.get("is_playlist") and p.suffix.lower() in MEDIA_EXTS:
                try:
                    size = p.stat().st_size
                except Exception:
                    size = None
                self._add_history({
                    "status":     "complete",
                    "title":      p.stem,
                    "filepath":   str(p),
                    "dir":        str(p.parent),
                    "format":     self.current_state.get("format") or p.suffix.lstrip("."),
                    "size_bytes": size,
                })
                # Contador de videos completados para el mensaje final
                self.current_state["playlist_completed"] = (
                    self.current_state.get("playlist_completed", 0) + 1
                )
        except Exception:
            pass

    def _enqueue_reorder(self, from_name: str, to_name: str):
        """Agrega un reorder a la cola para que el frontend lo muestre como toast."""
        try:
            queue = self.current_state.setdefault("recent_reorders", [])
            queue.append({"from": from_name, "to": to_name})
            # Limitar a 50 (en playlists muy grandes podría crecer mucho)
            if len(queue) > 50:
                self.current_state["recent_reorders"] = queue[-50:]
        except Exception:
            pass

    def _sync_audio_tags(self, filepath: Path, meta: dict | None):
        """
        Limpia los tags ID3/MP4 internos del archivo de audio para que
        coincidan con el nombre limpio. yt-dlp embebe los tags antes del
        post_hook, así que pueden tener "(Official Video)" todavía.

        - Si tenemos metadata de yt-dlp con artist y track confiables, los usa.
        - Si no, deduce desde el nombre del archivo aplicando clean_title.
        """
        try:
            import mutagen
        except ImportError:
            return  # mutagen no instalado, salir silencioso

        if filepath.suffix.lower() not in (".mp3", ".m4a", ".mp4", ".aac", ".flac",
                                           ".ogg", ".opus"):
            return

        # Determinar artist y title nuevos
        new_artist = None
        new_title  = None

        if meta and meta.get("artist") and meta.get("track"):
            new_artist = sanitize_filename_part(meta["artist"])
            new_title  = sanitize_filename_part(meta["track"])
        else:
            # Deducir desde el nombre del archivo limpio
            stem = filepath.stem
            # Patrón típico "Artista - Título"
            if " - " in stem:
                artist_part, _, title_part = stem.partition(" - ")
                new_artist = artist_part.strip()
                new_title  = title_part.strip()
            else:
                new_title = stem.strip()

        if not new_title:
            return

        try:
            audio = mutagen.File(str(filepath), easy=True)
            if audio is None:
                return

            # Comparar con valores actuales para no escribir si ya están bien
            current_title  = (audio.get("title")  or [""])[0] if audio else ""
            current_artist = (audio.get("artist") or [""])[0] if audio else ""

            changed = False
            if new_title and current_title != new_title:
                # También limpiamos el title actual con clean_title por si trae
                # ruido como "(Official Video)" — preferimos new_title pero
                # si new_title está vacío, usar el current limpio
                cleaned_current = clean_title(current_title) if current_title else ""
                final_title = new_title or cleaned_current
                if final_title and final_title != current_title:
                    audio["title"] = [final_title]
                    changed = True
            if new_artist and current_artist != new_artist:
                # Mismo razonamiento para artist
                audio["artist"] = [new_artist]
                changed = True

            if changed:
                audio.save()
        except Exception:
            # No es crítico — si falla, dejamos los tags como estaban
            pass

    def _guess_final_file(self, out_dir: Path, fmt: str) -> Path | None:
        ext_priority = [".mp3"] if fmt == "mp3" else [".mp4", ".mkv", ".webm"]
        latest = None
        for ext in ext_priority:
            files = list(out_dir.glob(f"*{ext}"))
            if files:
                f = max(files, key=lambda p: p.stat().st_mtime)
                if latest is None or f.stat().st_mtime > latest.stat().st_mtime:
                    latest = f
        return latest


    # ---------- Limpieza por lotes ----------
    def clean_folder(self, directory: str) -> dict:
        """
        Limpia los nombres de archivos de la carpeta:
          1) Aplica clean_filename() para quitar ruido (Official Video, etc.)
          2) Reordena "Canción - Artista" → "Artista - Canción" usando el
             tag ID3 'artist' como fuente de verdad
          3) Sincroniza los tags ID3 con el nombre final
        """
        d = Path(directory)
        if not d.exists() or not d.is_dir():
            return {"ok": False, "error": "Carpeta inválida"}

        # Necesitamos mutagen para leer el artist real desde los tags ID3
        try:
            import mutagen
            has_mutagen = True
        except ImportError:
            has_mutagen = False

        ok = err = 0
        tags_fixed = 0
        renamed = []        # [{"from": ..., "to": ...}, ...]
        reorders = []       # [{"from": ..., "to": ...}, ...]

        try:
            files = [f for f in d.iterdir()
                     if f.is_file() and f.suffix.lower() in MEDIA_EXTS]
        except Exception as e:
            return {"ok": False, "error": str(e)}

        for old in files:
            current_path = old
            current_name_changed = False
            old_name_for_log = old.name

            # Decisión: ¿este archivo es video y la opción de limpiar videos está apagada?
            is_video_file = current_path.suffix.lower() in VIDEO_EXTS
            skip_for_video = is_video_file and not self.settings.get(
                "clean_video_names", False
            )

            if skip_for_video:
                # Para videos sin limpieza completa: solo quitar el ID [VIDEOID] al final
                stem_no_id = _RE_YT_ID.sub("", current_path.stem).rstrip()
                if stem_no_id and stem_no_id != current_path.stem:
                    new_name = sanitize_filename_part(stem_no_id) + current_path.suffix
                    if new_name != current_path.name:
                        target = current_path.with_name(new_name)
                        if target != current_path:
                            stem, ext = Path(new_name).stem, current_path.suffix
                            n = 1
                            while target.exists():
                                target = current_path.with_name(f"{stem} ({n}){ext}")
                                n += 1
                        try:
                            current_path.rename(target)
                            ok += 1
                            renamed.append({"from": old_name_for_log, "to": target.name})
                        except Exception:
                            err += 1
                continue  # saltar el resto del procesamiento para este video

            # 1) Limpieza de ruido en el nombre
            cleaned_stem = clean_title(current_path.stem)

            # 2) Reordenamiento: leer artist del ID3 y aplicar reorder
            artist_from_id3 = None
            if has_mutagen:
                try:
                    audio = mutagen.File(str(current_path), easy=True)
                    if audio is not None:
                        artist_vals = audio.get("artist") or []
                        if artist_vals:
                            artist_from_id3 = artist_vals[0]
                except Exception:
                    pass

            reorder_from = None
            reorder_to = None
            if artist_from_id3:
                candidate, was_reordered = reorder_to_artist_first(
                    cleaned_stem, artist_from_id3
                )
                if was_reordered:
                    reorder_from = cleaned_stem
                    reorder_to = candidate
                    cleaned_stem = candidate

            # 3) Aplicar el rename si hubo cambios
            new_name = sanitize_filename_part(cleaned_stem) + current_path.suffix
            if new_name and new_name != current_path.name:
                target = current_path.with_name(new_name)
                if target != current_path:
                    stem, ext = Path(new_name).stem, current_path.suffix
                    n = 1
                    while target.exists():
                        target = current_path.with_name(f"{stem} ({n}){ext}")
                        n += 1
                try:
                    current_path.rename(target)
                    current_path = target
                    current_name_changed = True
                    ok += 1
                    renamed.append({"from": old_name_for_log, "to": target.name})
                    if reorder_from and reorder_to:
                        reorders.append({"from": reorder_from, "to": reorder_to})
                except Exception:
                    err += 1
                    continue

            # 4) Sincronizar tags ID3 con el nombre final
            try:
                if current_name_changed:
                    self._sync_audio_tags(current_path, None)
                else:
                    if self._sync_audio_tags_if_dirty(current_path):
                        tags_fixed += 1
            except Exception:
                pass

        return {
            "ok": True,
            "count": ok,
            "errors": err,
            "renamed": renamed,
            "reorders": reorders,
            "tags_fixed": tags_fixed,
        }

    def _sync_audio_tags_if_dirty(self, filepath: Path) -> bool:
        """
        Revisa los tags de un archivo y los limpia SOLO si tienen ruido
        (palabras como "Official Video"). Devuelve True si se modificaron.
        """
        try:
            import mutagen
        except ImportError:
            return False

        try:
            audio = mutagen.File(str(filepath), easy=True)
            if audio is None:
                return False

            current_title  = (audio.get("title")  or [""])[0]
            current_artist = (audio.get("artist") or [""])[0]

            cleaned_title  = clean_title(current_title)  if current_title  else ""
            cleaned_artist = clean_title(current_artist) if current_artist else ""

            changed = False
            if cleaned_title and cleaned_title != current_title:
                audio["title"] = [cleaned_title]
                changed = True
            if cleaned_artist and cleaned_artist != current_artist:
                audio["artist"] = [cleaned_artist]
                changed = True

            if changed:
                audio.save()
                return True
            return False
        except Exception:
            return False
