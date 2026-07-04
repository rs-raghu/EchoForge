from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from echoforge.stages.musevault.image_service import cover_resize, find_font, wrap_text


def make_upload_thumbnail(project_dir: Path, review: dict[str, Any]) -> dict[str, Any]:
    renders_dir = project_dir / "renders"
    images_dir = project_dir / "images"
    renders_dir.mkdir(parents=True, exist_ok=True)

    out = renders_dir / "upload_thumbnail.jpg"
    bg_path = images_dir / "background_source.jpg"
    thumb_path = images_dir / "music_thumbnail.jpg"

    bg = Image.open(bg_path).convert("RGB") if bg_path.exists() else Image.new("RGB", (1280, 720), (32, 32, 36))
    canvas = cover_resize(bg, (1280, 720)).filter(ImageFilter.GaussianBlur(2)).convert("RGBA")
    canvas = Image.alpha_composite(canvas, Image.new("RGBA", canvas.size, (0, 0, 0, 88)))
    draw = ImageDraw.Draw(canvas)

    title_font = find_font(76)
    artist_font = find_font(42)
    small_font = find_font(36)

    if thumb_path.exists():
        thumb = cover_resize(Image.open(thumb_path), (390, 390))
        canvas.paste(thumb.convert("RGBA"), (80, 110))

    x, y = 520, 150
    for line in wrap_text(draw, review.get("display_title") or "Untitled", title_font, 660)[:3]:
        draw.text((x, y), line, font=title_font, fill=(255, 255, 255, 255))
        y += 84

    y += 12
    for line in wrap_text(draw, review.get("display_artist") or "Unknown Artist", artist_font, 660)[:2]:
        draw.text((x, y), line, font=artist_font, fill=(230, 230, 230, 255))
        y += 52

    draw.text((x, 580), "( lyrics )", font=small_font, fill=(255, 255, 255, 255))
    draw.rounded_rectangle((80, 535, 470, 600), radius=30, fill=(255, 255, 255, 230))
    draw.text((135, 550), "◀    ▶    ●    ▬▬▬", font=small_font, fill=(20, 20, 24, 255))
    canvas.convert("RGB").save(out, quality=95)
    return {"ok": True, "path": str(out)}
