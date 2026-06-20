"""Generate the Tauri icon set from a simple drawn source (no external assets).

Produces icons/{32x32.png,128x128.png,128x128@2x.png,icon.ico}. Run from the
src-tauri/ directory:  python gen_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "icons"
OUT.mkdir(parents=True, exist_ok=True)

BG1 = (15, 18, 32)      # deep navy
BG2 = (24, 28, 48)
ACCENT = (233, 69, 96)  # primary red
LIGHT = (235, 238, 245)


def base(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Rounded-rect background
    r = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG1)
    # Subtle inner panel
    pad = int(size * 0.10)
    d.rounded_rectangle([pad, pad, size - pad, size - pad],
                        radius=int(r * 0.7), outline=BG2, width=max(1, size // 64))
    # Lightning bolt (headless "dynamic patcher" motif)
    s = size
    bolt = [
        (0.56 * s, 0.16 * s), (0.34 * s, 0.55 * s), (0.48 * s, 0.55 * s),
        (0.42 * s, 0.84 * s), (0.66 * s, 0.44 * s), (0.50 * s, 0.44 * s),
        (0.60 * s, 0.16 * s),
    ]
    d.polygon(bolt, fill=ACCENT)
    return img


def main() -> None:
    sizes = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
    }
    for name, sz in sizes.items():
        base(sz).save(OUT / name)
    # Multi-resolution .ico
    ico = base(256)
    ico.save(OUT / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    # Some Tauri/Windows bundlers also expect a Square/StoreLogo set; provide a 512 png.
    base(512).save(OUT / "icon.png")
    print(f"Icons written to {OUT}")


if __name__ == "__main__":
    main()
