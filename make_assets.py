"""Run this on your computer (it uses Pillow):  python make_assets.py

It makes 3x nearest-neighbour (crisp, no blurring) copies of every png in
raw_art/ into assets/, plus two bright crystal gems coloured from gem.png:
blue = XP 1, pink = XP 2. main.py only ever loads the finished assets/.
"""

import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw_art")
OUT = os.path.join(HERE, "assets")
SCALE = 3


def upscale(img):
    return img.resize((img.width * SCALE, img.height * SCALE), Image.NEAREST)


def colour_gem(src, colour):
    """Re-colour the grey gem: each pixel keeps its brightness, tinted with `colour`."""
    src = src.convert("RGBA")
    out = Image.new("RGBA", src.size)
    r, g, b = colour
    for y in range(src.height):
        for x in range(src.width):
            px = src.getpixel((x, y))
            if px[3] == 0:
                out.putpixel((x, y), (0, 0, 0, 0))
                continue
            light = max(px[0], px[1], px[2]) / 255.0
            boost = 0.45 + 0.55 * light  # bright faces stay bright, dark edges stay dark
            out.putpixel((x, y), (min(255, int(r * boost)), min(255, int(g * boost)),
                                  min(255, int(b * boost)), px[3]))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    gem_src = Image.open(os.path.join(RAW, "gem.png"))
    for name in sorted(os.listdir(RAW)):
        if not name.lower().endswith(".png"):
            continue
        img = Image.open(os.path.join(RAW, name)).convert("RGBA")
        upscale(img).save(os.path.join(OUT, name))
        print("wrote assets/" + name)
    for name, colour in (("gem_blue.png", (90, 170, 255)),
                         ("gem_pink.png", (255, 120, 220))):
        upscale(colour_gem(gem_src, colour)).save(os.path.join(OUT, name))
        print("wrote assets/" + name)


if __name__ == "__main__":
    main()
