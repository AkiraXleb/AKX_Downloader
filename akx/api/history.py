"""Historial de descargas y apertura de archivos en el explorador del SO."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from akx.history import save_history
from akx.paths import VIDEO_EXTS


class HistoryMixin:
    # ---------- Historial ----------
    def _add_history(self, item: dict):
        item["id"] = str(int(time.time() * 1000))
        item["timestamp"] = datetime.now().isoformat(timespec="seconds")
        if not item.get("filename"):
            item["filename"] = (Path(item["filepath"]).name
                                if item.get("filepath") else item.get("title", "—"))
        self.history.append(item)
        save_history(self.history)

    def get_history(self) -> list[dict]:
        items = list(reversed(self.history))
        for it in items:
            fp = it.get("filepath")
            if fp and Path(fp).exists():
                it["exists"] = True
                it["kind"] = "video" if Path(fp).suffix.lower() in VIDEO_EXTS else "audio"
            else:
                it["exists"] = False
                it["kind"] = None
        return items

    def delete_history_item(self, item_id: str) -> bool:
        before = len(self.history)
        self.history = [h for h in self.history if h.get("id") != item_id]
        save_history(self.history)
        return len(self.history) != before

    def clear_history(self) -> bool:
        self.history = []
        save_history(self.history)
        return True

    def open_in_explorer(self, path_str: str) -> bool:
        try:
            p = Path(path_str)
            if sys.platform.startswith("win"):
                if p.is_file():
                    subprocess.Popen(["explorer", "/select,", str(p)])
                else:
                    os.startfile(str(p))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                if p.is_file():
                    subprocess.Popen(["open", "-R", str(p)])
                else:
                    subprocess.Popen(["open", str(p)])
            else:
                target = p if p.is_dir() else p.parent
                subprocess.Popen(["xdg-open", str(target)])
            return True
        except Exception:
            return False

