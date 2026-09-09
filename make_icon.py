"""
Convierte una imagen PNG (o JPG) en un archivo .ico multi-resolución
listo para PyInstaller/Windows.

Uso:
    python make_icon.py imagen.png            → crea icon.ico
    python make_icon.py imagen.png logo.ico   → nombre custom

Requisitos:
    pip install pillow
"""

import sys
from pathlib import Path
from PIL import Image

def main():
    if len(sys.argv) < 2:
        print("Uso: python make_icon.py <imagen.png> [salida.ico]")
        sys.exit(1)

    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("icon.ico")

    if not src.exists():
        print(f"✗ No existe: {src}")
        sys.exit(1)

    img = Image.open(src)

    # Convertir a RGBA para preservar transparencia
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    # Recortar a cuadrado si no lo es (centro)
    w, h = img.size
    if w != h:
        side = min(w, h)
        left = (w - side) // 2
        top  = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        print(f"  (recortado a cuadrado: {side}x{side})")

    # Todas las resoluciones que usa Windows
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

    # Aviso si la fuente es más chica que 256
    if img.size[0] < 256:
        print(f"  ⚠ Fuente es {img.size[0]}px, ideal 256+ para no perder nitidez")

    img.save(out, format="ICO", sizes=sizes)
    print(f"✓ Guardado {out} ({out.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
