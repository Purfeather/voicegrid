from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
SIZES = (16, 20, 24, 32, 48, 64, 128, 256)


def render(size: int) -> Image.Image:
    scale = size / 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    white = (255, 255, 255, 255)
    width = max(1, round(4 * scale))
    draw.rounded_rectangle(
        tuple(round(value * scale) for value in (5, 5, 59, 59)),
        radius=max(2, round(13 * scale)), outline=white, width=width,
    )
    for x, y1, y2 in ((15, 29, 35), (23, 24, 40), (31, 17, 47), (39, 23, 41), (47, 28, 36)):
        draw.line(
            (round(x * scale), round(y1 * scale), round(x * scale), round(y2 * scale)),
            fill=white, width=width,
        )
    draw.rounded_rectangle(tuple(round(value * scale) for value in (45, 15, 51, 21)), radius=max(1, round(scale)), fill=white)
    draw.rounded_rectangle(tuple(round(value * scale) for value in (49, 23, 54, 28)), radius=max(1, round(scale)), fill=white)
    return image


if __name__ == "__main__":
    frames = [render(size) for size in SIZES]
    frames[-1].save(ROOT / "voicegrid.ico", format="ICO", append_images=frames[:-1], sizes=[(size, size) for size in SIZES])
    render(256).save(ROOT / "voicegrid-icon-white.png", format="PNG")
