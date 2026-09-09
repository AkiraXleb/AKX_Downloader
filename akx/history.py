"""Historial persistente de descargas (~/.akx_downloader/history.json)."""
from __future__ import annotations

import json

from akx.paths import HISTORY_FILE, ensure_data_dir


def load_history() -> list[dict]:
    ensure_data_dir()
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_history(items: list[dict]):
    ensure_data_dir()
    try:
        HISTORY_FILE.write_text(json.dumps(items[-500:], indent=2, ensure_ascii=False),
                                encoding="utf-8")
    except Exception:
        pass
