from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from echoforge.stages.musevault.image_service import cover_resize, find_font, wrap_text


def make_lyrics_video_background(project_dir: Path, review: dict[str, Any]) -> dict[str, Any]:
    images_dir = project_dir / "images"
    out = images_dir / "video_background.jpg"
    bg_path = images_dir / "background_source.jpg"
    thumb_path = images_dir / "music_thumbnail.jpg"

    bg = Image.open(bg_path).convert("RGB") if bg_path.exists() else Image.new("RGB", (1920, 1080), (32, 32, 36))
    canvas = cover_resize(bg, (1920, 1080)).filter(ImageFilter.GaussianBlur(1)).convert("RGBA")
    canvas = Image.alpha_composite(canvas, Image.new("RGBA", canvas.size, (255, 255, 255, 25)))
    draw = ImageDraw.Draw(canvas)

    if thumb_path.exists():
        thumb = cover_resize(Image.open(thumb_path), (220, 220))
        canvas.paste(thumb.convert("RGBA"), (70, 60))

    title_font = find_font(54)
    artist_font = find_font(34)
    x, y = 325, 88
    for line in wrap_text(draw, review.get("display_title") or "Untitled", title_font, 720)[:2]:
        draw.text((x, y), line, font=title_font, fill=(20, 20, 20, 255))
        y += 62

    for line in wrap_text(draw, review.get("display_artist") or "Unknown Artist", artist_font, 720)[:2]:
        draw.text((x, y + 6), line, font=artist_font, fill=(45, 45, 45, 255))
        y += 42

    draw.text((75, 970), "EchoForge", font=find_font(38), fill=(25, 25, 25, 220))
    canvas.convert("RGB").save(out, quality=95)
    return {"ok": True, "path": str(out)}
