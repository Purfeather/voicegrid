from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
SIZES = (16, 20, 24, 32, 48, 64, 128, 256)
ACCENT = (243, 255, 0, 255)
DARK = (17, 19, 21, 255)

SMALL_GEOMETRY = {
    16: {
        "outer_radius": 4,
        "inset": 1,
        "inner_radius": 2,
        "stroke": 1,
        "bars": ((3.5, 7, 9), (5.5, 6, 10), (7.5, 4, 12), (9.5, 6, 10), (11.5, 7, 9)),
        "blocks": ((11, 3, 2), (13, 5, 1)),
    },
    20: {
        "outer_radius": 4,
        "inset": 1,
        "inner_radius": 3,
        "stroke": 2,
        "bars": ((3, 9, 11), (6, 7, 13), (9, 5, 15), (12, 7, 13), (15, 9, 11)),
        "blocks": ((14, 4, 2), (17, 7, 2)),
    },
    24: {
        "outer_radius": 5,
        "inset": 2,
        "inner_radius": 4,
        "stroke": 2,
        "bars": ((5, 11, 13), (8, 9, 15), (11, 6, 18), (14, 9, 15), (17, 11, 13)),
        "blocks": ((16, 5, 2), (19, 8, 2)),
    },
    32: {
        "outer_radius": 7,
        "inset": 2,
        "inner_radius": 5,
        "stroke": 2,
        "bars": ((7, 15, 17), (11, 12, 20), (15, 8, 24), (19, 11, 21), (23, 14, 18)),
        "blocks": ((22, 7, 3), (26, 11, 2)),
    },
}


def _rounded_line(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float, float, float],
    width: float,
    fill: tuple[int, int, int, int],
) -> None:
    x1, y1, x2, y2 = xy
    radius = width / 2
    draw.rectangle((x1 - radius, y1, x2 + radius, y2), fill=fill)
    draw.ellipse((x1 - radius, y1 - radius, x1 + radius, y1 + radius), fill=fill)
    draw.ellipse((x2 - radius, y2 - radius, x2 + radius, y2 + radius), fill=fill)


def _render_small(size: int) -> Image.Image:
    geometry = SMALL_GEOMETRY[size]
    supersample = 16
    canvas = size * supersample
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, canvas - 1, canvas - 1),
        radius=geometry["outer_radius"] * supersample,
        fill=ACCENT,
    )
    inset = geometry["inset"] * supersample
    draw.rounded_rectangle(
        (inset, inset, canvas - inset - 1, canvas - inset - 1),
        radius=geometry["inner_radius"] * supersample,
        fill=DARK,
    )
    for x, y1, y2 in geometry["bars"]:
        _rounded_line(
            draw,
            (x * supersample, y1 * supersample, x * supersample, y2 * supersample),
            geometry["stroke"] * supersample,
            ACCENT,
        )
    for x, y, side in geometry["blocks"]:
        draw.rectangle(
            (x * supersample, y * supersample, (x + side) * supersample - 1, (y + side) * supersample - 1),
            fill=ACCENT,
        )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def _render_master(size: int) -> Image.Image:
    supersample = 16 if size <= 48 else 4
    canvas = size * supersample
    scale = canvas / 64
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, canvas - 1, canvas - 1), radius=round(14 * scale), fill=ACCENT)
    inset = round(4 * scale)
    draw.rounded_rectangle(
        (inset, inset, canvas - inset - 1, canvas - inset - 1),
        radius=round(10 * scale),
        fill=DARK,
    )
    width = 4 * scale
    for x, y1, y2 in ((14, 30, 34), (22, 24, 40), (30, 17, 47), (38, 22, 42), (46, 28, 36)):
        _rounded_line(draw, (x * scale, y1 * scale, x * scale, y2 * scale), width, ACCENT)
    draw.rounded_rectangle(
        (44 * scale, 14 * scale, 50 * scale - 1, 20 * scale - 1),
        radius=max(1, round(scale)),
        fill=ACCENT,
    )
    draw.rounded_rectangle(
        (50 * scale, 22 * scale, 54 * scale - 1, 26 * scale - 1),
        radius=max(1, round(scale)),
        fill=ACCENT,
    )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def render_system(size: int) -> Image.Image:
    return _render_small(size) if size in SMALL_GEOMETRY else _render_master(size)


def render_accent(size: int) -> Image.Image:
    return render_system(size)


if __name__ == "__main__":
    frames = [render_system(size) for size in SIZES]
    frames[-1].save(
        ROOT / "voicegrid.ico",
        format="ICO",
        append_images=frames[:-1],
        sizes=[(size, size) for size in SIZES],
    )
    render_accent(256).save(ROOT / "voicegrid-icon-accent.png", format="PNG")
