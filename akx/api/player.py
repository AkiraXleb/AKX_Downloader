"""
Reproductor: listado de archivos, URLs de reproducción vía FileServer,
extracción de portadas embebidas, y renombrado/borrado de medios.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

from akx.history import save_history
from akx.naming import _RE_BAD_FN_CHARS, sanitize_filename_part
from akx.paths import AUDIO_EXTS, MEDIA_EXTS, VIDEO_EXTS


class PlayerMixin:
    # ---------- Reproductor ----------
    def list_media_files(self, directory: str | None = None) -> list[dict]:
        directory = directory or self.settings.get("download_dir")
        if not directory:
            return []
        d = Path(directory)
        if not d.exists() or not d.is_dir():
            return []
        out = []
        try:
            for f in sorted(d.iterdir(), key=lambda p: p.name.lower()):
                if not f.is_file():
                    continue
                ext = f.suffix.lower()
                if ext in AUDIO_EXTS:
                    kind = "audio"
                elif ext in VIDEO_EXTS:
                    kind = "video"
                else:
                    continue
                stat = f.stat()
                out.append({
                    "name": f.name,
                    "path": str(f),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "kind": kind,
                    "ext": ext.lstrip("."),
                })
        except Exception:
            pass
        return out

    def get_playback_url(self, filepath: str) -> str | None:
        p = Path(filepath)
        if not p.exists() or not p.is_file():
            return None
        return self.file_server.register(filepath)

    def get_embedded_thumbnail(self, filepath: str) -> str | None:
        """
        Extrae la portada embebida de un archivo de audio (MP3/M4A/etc) y la
        devuelve como data URL base64. Si no hay portada embebida, intenta usar
        el ID de YouTube en el nombre como fallback (i.ytimg.com).
        Devuelve None si no se puede.
        """
        p = Path(filepath)
        if not p.exists() or not p.is_file():
            return None

        # 1) Intentar extraer portada embebida con mutagen (si está disponible)
        try:
            import mutagen
            from mutagen.id3 import ID3
            from mutagen.mp4 import MP4
            from mutagen.flac import FLAC

            ext = p.suffix.lower()
            data = None
            mime = "image/jpeg"

            if ext == ".mp3":
                try:
                    tags = ID3(str(p))
                    for key in tags.keys():
                        if key.startswith("APIC"):
                            apic = tags[key]
                            data = apic.data
                            mime = apic.mime or "image/jpeg"
                            break
                except Exception:
                    pass
            elif ext in (".m4a", ".mp4", ".aac"):
                try:
                    audio = MP4(str(p))
                    covers = audio.tags.get("covr") if audio.tags else None
                    if covers:
                        cover = covers[0]
                        data = bytes(cover)
                        # MP4Cover.imageformat: 13=JPEG, 14=PNG
                        try:
                            from mutagen.mp4 import MP4Cover
                            if cover.imageformat == MP4Cover.FORMAT_PNG:
                                mime = "image/png"
                        except Exception:
                            pass
                except Exception:
                    pass
            elif ext == ".flac":
                try:
                    audio = FLAC(str(p))
                    if audio.pictures:
                        pic = audio.pictures[0]
                        data = pic.data
                        mime = pic.mime or "image/jpeg"
                except Exception:
                    pass

            if data:
                b64 = base64.b64encode(data).decode("ascii")
                return f"data:{mime};base64,{b64}"
        except ImportError:
            pass  # mutagen no instalado, caemos al fallback
        except Exception:
            pass

        # 2) Fallback: ID de YouTube en el nombre del archivo
        m = re.search(r"\[([A-Za-z0-9_-]{11})\]", p.stem)
        if m:
            return f"https://i.ytimg.com/vi/{m.group(1)}/mqdefault.jpg"

        return None

    def rename_media_file(self, filepath: str, new_name: str) -> dict:
        """
        Renombra un archivo de la carpeta de medios.
        new_name puede venir con o sin extensión; si no la trae, se conserva la original.
        """
        p = Path(filepath)
        if not p.exists() or not p.is_file():
            return {"ok": False, "error": "El archivo ya no existe."}

        new_name = (new_name or "").strip()
        if not new_name:
            return {"ok": False, "error": "El nombre no puede estar vacío."}

        # Validar caracteres prohibidos
        if _RE_BAD_FN_CHARS.search(new_name):
            return {"ok": False,
                    "error": 'El nombre contiene caracteres no permitidos: < > : " / \\ | ? *'}

        # Si el nuevo nombre no trae extensión, conservar la actual
        new_p = Path(new_name)
        if not new_p.suffix:
            new_name = new_name + p.suffix
            new_p = Path(new_name)
        else:
            # Validar que la extensión sea de medio (no permitir cambiar a .exe etc)
            if new_p.suffix.lower() not in MEDIA_EXTS:
                return {"ok": False,
                        "error": f"Extensión '{new_p.suffix}' no permitida."}

        # Sanitizar
        clean_stem = sanitize_filename_part(new_p.stem)
        if not clean_stem:
            return {"ok": False, "error": "Nombre inválido tras sanitización."}
        new_name = clean_stem + new_p.suffix

        target = p.with_name(new_name)
        if target == p:
            return {"ok": True, "path": str(p), "name": p.name, "unchanged": True}
        if target.exists():
            return {"ok": False,
                    "error": f"Ya existe un archivo llamado '{new_name}' en esta carpeta."}

        try:
            p.rename(target)
        except Exception as e:
            return {"ok": False, "error": f"No se pudo renombrar: {e}"}

        # Actualizar historial: si tenemos una entrada con esta ruta, ajustarla
        try:
            updated = False
            for h in self.history:
                if h.get("filepath") == str(p):
                    h["filepath"] = str(target)
                    h["filename"] = target.name
                    h["title"] = target.stem
                    updated = True
            if updated:
                save_history(self.history)
        except Exception:
            pass

        return {"ok": True, "path": str(target), "name": target.name}

    def delete_media_file(self, filepath: str) -> dict:
        """Borra un archivo del disco (envía al modelo de papelera del SO si está disponible)."""
        p = Path(filepath)
        if not p.exists() or not p.is_file():
            return {"ok": False, "error": "El archivo ya no existe."}

        # Intentar mandar a la papelera (más seguro). Si falla, usar unlink directo.
        sent_to_trash = False
        try:
            import send2trash  # type: ignore
            send2trash.send2trash(str(p))
            sent_to_trash = True
        except ImportError:
            try:
                p.unlink()
            except Exception as e:
                return {"ok": False, "error": f"No se pudo borrar: {e}"}
        except Exception:
            try:
                p.unlink()
            except Exception as e:
                return {"ok": False, "error": f"No se pudo borrar: {e}"}

        # Limpiar historial
        try:
            new_hist = [h for h in self.history if h.get("filepath") != str(p)]
            if len(new_hist) != len(self.history):
                self.history = new_hist
                save_history(self.history)
        except Exception:
            pass

        return {"ok": True, "trashed": sent_to_trash, "path": str(p)}

