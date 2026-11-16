"""Generate the launcher icon at every mipmap density."""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
ACCENT = (252, 213, 53, 255)
DARK = (11, 14, 17, 255)


def draw_icon(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=ACCENT)

    line = max(1, round(size * 0.035))
    margin = round(size * 0.17)
    inner = size - 2 * margin
    draw.rectangle((margin, margin, size - margin, size - margin), outline=DARK, width=line)
    for step in (1, 2, 3):
        offset = margin + round(inner * step / 4)
        draw.line((offset, margin, offset, size - margin), fill=DARK, width=line)
        draw.line((margin, offset, size - margin, offset), fill=DARK, width=line)
    return image


for density, px in SIZES.items():
    target = HERE / "res" / f"mipmap-{density}"
    target.mkdir(parents=True, exist_ok=True)
    draw_icon(px).save(target / "ic_launcher.png")

print("icons written")
