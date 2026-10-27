"""生成 BulkSeq Studio 的应用图标（多尺寸 .ico）。"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "build" / "app.ico"


def make(size: int = 512) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角渐变底
    bg = Image.new("RGB", (size, size), (13, 42, 84))
    bd = ImageDraw.Draw(bg)
    for y in range(size):
        t = y / size
        r = int(13 + (12 - 13) * t)
        g = int(42 + (120 - 42) * t)
        b = int(84 + (188 - 84) * t)
        bd.line([(0, y), (size, y)], fill=(r, g, b))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255)
    img.paste(bg, (0, 0), mask)

    # 双螺旋
    cx = size / 2
    top, bottom = size * 0.18, size * 0.82
    amp = size * 0.17
    steps = 240
    for strand in (0, math.pi):
        pts = []
        for i in range(steps + 1):
            t = i / steps
            y = top + (bottom - top) * t
            x = cx + amp * math.sin(t * math.pi * 3 + strand)
            pts.append((x, y))
        d.line(pts, fill=(255, 255, 255, 235), width=max(3, int(size * 0.038)), joint="curve")

    # 横档
    for k in range(9):
        t = 0.06 + k * 0.11
        y = top + (bottom - top) * t
        x1 = cx + amp * math.sin(t * math.pi * 3)
        x2 = cx + amp * math.sin(t * math.pi * 3 + math.pi)
        d.line([(x1, y), (x2, y)], fill=(125, 211, 252, 210), width=max(2, int(size * 0.022)))

    return img


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    base = make(512)
    base.save(OUT, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    base.resize((256, 256), Image.LANCZOS).save(OUT.with_name("app_256.png"))
    print("icon ->", OUT)


if __name__ == "__main__":
    main()
