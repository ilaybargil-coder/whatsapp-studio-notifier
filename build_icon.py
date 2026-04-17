"""
Build a modern, Chrome-style transparent icon from logo_icon.png.

Strategy:
  1. Load the source PNG (current one has a white square background).
  2. Flood-fill the outer white/near-white pixels from each corner → alpha 0.
     This removes ONLY the outer background, leaving any internal whites
     (bell highlights, gear teeth) intact.
  3. Feather the alpha edges (1-px anti-alias) so the icon looks smooth.
  4. Save as logo_icon.png (transparent PNG for Tk iconphoto).
  5. Generate logo_icon.ico at every Windows-required size
     (16/24/32/48/64/128/256) so the taskbar, desktop, and Explorer
     all pick the best variant.

Run once after changing the source logo:
    python3 build_icon.py
"""
from __future__ import annotations
import os, sys
from collections import deque
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(HERE, "logo_icon.png")    # or swap to "logo.png" + crop
OUT_PNG = os.path.join(HERE, "logo_icon.png")
OUT_ICO = os.path.join(HERE, "logo_icon.ico")

# Pixel is considered "background" if all RGB channels are above this.
# Lowered slightly to catch the cream/off-white edges.
BG_THRESHOLD = 235


def flood_transparent(img: Image.Image, threshold: int = BG_THRESHOLD) -> Image.Image:
    """Flood-fill the outer background (white/near-white) to transparent,
    starting from the 4 corners. Preserves interior bright pixels."""
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()

    visited = bytearray(w * h)   # 0 = not visited, 1 = visited
    stack: deque[tuple[int, int]] = deque()

    def is_bg(r, g, b, a):
        return a > 0 and r >= threshold and g >= threshold and b >= threshold

    # Seed from all 4 corners
    for sx, sy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        r, g, b, a = px[sx, sy]
        if is_bg(r, g, b, a):
            stack.append((sx, sy))

    while stack:
        x, y = stack.pop()
        idx = y * w + x
        if visited[idx]:
            continue
        visited[idx] = 1
        r, g, b, a = px[x, y]
        if not is_bg(r, g, b, a):
            continue
        px[x, y] = (r, g, b, 0)  # transparent
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not visited[ny * w + nx]:
                stack.append((nx, ny))

    return img


def feather_alpha(img: Image.Image, radius: float = 0.8) -> Image.Image:
    """Tiny gaussian blur on the alpha channel to soften jagged edges."""
    r, g, b, a = img.split()
    a = a.filter(ImageFilter.GaussianBlur(radius=radius))
    return Image.merge("RGBA", (r, g, b, a))


def build(source_path: str = SRC) -> None:
    if not os.path.exists(source_path):
        sys.exit(f"[build_icon] source not found: {source_path}")

    src = Image.open(source_path).convert("RGBA")
    print(f"[build_icon] loaded {source_path} @ {src.size}")

    # Upscale to 512 first so the flood has smooth edges, then downsample.
    if max(src.size) < 512:
        src = src.resize((512, 512), Image.LANCZOS)

    cut = flood_transparent(src)
    cut = feather_alpha(cut, radius=0.8)

    # Square it (logo_icon is already square but be safe)
    w, h = cut.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(cut, ((side - w) // 2, (side - h) // 2), cut)

    # Save the master PNG (512×512 transparent, used by Tk iconphoto)
    master = canvas.resize((256, 256), Image.LANCZOS)
    master.save(OUT_PNG, "PNG", optimize=True)
    print(f"[build_icon] wrote {OUT_PNG}  {master.size}")

    # Generate ICO with all common Windows sizes (256 first for Win10+)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48),
             (32, 32), (24, 24), (16, 16)]
    frames = [canvas.resize(s, Image.LANCZOS) for s in sizes]
    # Pillow writes all supplied sizes when passed via `sizes=`
    frames[0].save(OUT_ICO, format="ICO", sizes=sizes)
    print(f"[build_icon] wrote {OUT_ICO}  sizes={sizes}")

    print("[build_icon] done ✓  — run pyinstaller now to embed the new icon.")


if __name__ == "__main__":
    build()
