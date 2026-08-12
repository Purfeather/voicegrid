from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
SIZES = (16, 20, 24, 32, 48, 64, 128, 256)
SYSTEM_BACKGROUND = (17, 19, 21, 255)
SYSTEM_BORDER = (42, 46, 51, 255)
SYSTEM_ACCENT = (243, 255, 0, 255)


def _draw_mark(size: int, color: tuple[int, int, int, int], width_scale: float = 1.0) -> Image.Image:
    scale = size / 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    width = max(1, round(4 * scale * width_scale))
    draw.rounded_rectangle(
        tuple(round(value * scale) for value in (5, 5, 59, 59)),
        radius=max(2, round(13 * scale)), outline=color, width=width,
    )
    for x, y1, y2 in ((15, 29, 35), (23, 24, 40), (31, 17, 47), (39, 23, 41), (47, 28, 36)):
        draw.line(
            (round(x * scale), round(y1 * scale), round(x * scale), round(y2 * scale)),
            fill=color, width=width,
        )
    draw.rounded_rectangle(tuple(round(value * scale) for value in (45, 15, 51, 21)), radius=max(1, round(scale)), fill=color)
    draw.rounded_rectangle(tuple(round(value * scale) for value in (49, 23, 54, 28)), radius=max(1, round(scale)), fill=color)
    return image


def render_white(size: int) -> Image.Image:
    return _draw_mark(size, (255, 255, 255, 255))


def render_system(size: int) -> Image.Image:
    scale = size / 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    border_width = max(1, round(scale))
    draw.rounded_rectangle(
        tuple(round(value * scale) for value in (2, 2, 62, 62)),
        radius=max(2, round(14 * scale)),
        fill=SYSTEM_BACKGROUND,
        outline=SYSTEM_BORDER,
        width=border_width,
    )
    image.alpha_composite(_draw_mark(size, SYSTEM_ACCENT))
    return image


if __name__ == "__main__":
    frames = [render_system(size) for size in SIZES]
    frames[-1].save(ROOT / "voicegrid.ico", format="ICO", append_images=frames[:-1], sizes=[(size, size) for size in SIZES])
    render_white(256).save(ROOT / "voicegrid-icon-white.png", format="PNG")
