"""Formateo de tamaños en bytes a texto legible (KB/MB/GB…)."""
from __future__ import annotations


def fmt_bytes(n) -> str:
    if n is None or n == 0:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"

