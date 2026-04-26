"""
thumbnail_gen.py

Generates a 1280×720 YouTube thumbnail using Pillow.

Layout
──────
┌─────────────────────────────────────────────────────┐
│  [blurred / darkened background]                    │
│                                                     │
│  ┌──────────┐   SONG TITLE                          │
│  │  album   │   Artist Name                         │
│  │   art    │   (lyrics)                            │
│  │ (square) │                                       │
│  └──────────┘                                       │
└─────────────────────────────────────────────────────┘

Fonts are loaded from absolute .ttf/.otf paths stored in DB (user_settings).
Falls back to PIL's built-in bitmap font if no custom font is configured.

CLI USAGE:
    python thumbnail_gen.py --title "Song" --artist "Artist" \\
                            --bg path/to/bg.jpg --output ./output_dir
"""

import argparse
import os
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import db_manager
from logger import get_logger

log = get_logger(__name__)

# ─── Layout ───────────────────────────────────────────────────────────────────
THUMB_W  = 1280
THUMB_H  = 720
PADDING  = 60
ART_SIZE = 520
ART_X    = PADDING
ART_Y    = (THUMB_H - ART_SIZE) // 2
TEXT_X   = ART_X + ART_SIZE + PADDING
TEXT_MAX_W = THUMB_W - TEXT_X - PADDING

BG_OVERLAY     = (0, 0, 0, 160)
ART_BORDER_CLR = (255, 255, 255, 200)
TITLE_COLOR    = (255, 255, 255)
ARTIST_COLOR   = (200, 200, 200)
LYRICS_TAG_CLR = (160, 160, 160)

TITLE_SIZE_MAX  = 80
ARTIST_SIZE_MAX = 52
TAG_SIZE        = 40
BG_BLUR         = 4


# ─── Font helpers ─────────────────────────────────────────────────────────────

def _load_font(path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    if path and os.path.isfile(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception as exc:
            log.warning("⚠️  Could not load font '%s': %s — using default.", path, exc)
    return ImageFont.load_default()


def _fit_text(
    draw: ImageDraw.Draw,
    text: str,
    font_path: Optional[str],
    max_size: int,
    max_width: int,
) -> ImageFont.FreeTypeFont:
    """Return the largest font that keeps *text* within *max_width* pixels."""
    for size in range(max_size, 20, -4):
        font = _load_font(font_path, size)
        if draw.textlength(text, font=font) <= max_width:
            return font
    return _load_font(font_path, 20)


# ─── Main generator ───────────────────────────────────────────────────────────

def generate_thumbnail(
    title:      str,
    artist:     str,
    bg_path:    Optional[str],
    output_dir: str,
) -> str:
    """
    Generate a 1280×720 thumbnail and save it as output_dir/thumbnail.jpg.

    Returns the absolute path to the saved file.
    """
    db_manager.init_db()
    fonts            = db_manager.get_font_paths()
    title_font_path  = fonts.get("title")
    artist_font_path = fonts.get("artist")
    lyrics_font_path = fonts.get("lyrics") or artist_font_path

    log.info("🖼️  Generating thumbnail for '%s'...", title)

    # ── Background layer ──────────────────────────────────────────────────────
    if bg_path and os.path.isfile(bg_path):
        bg = Image.open(bg_path).convert("RGBA")
        bg = bg.resize((THUMB_W, THUMB_H), Image.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(BG_BLUR))
    else:
        log.warning("⚠️  No valid bg_path — using dark fallback.")
        bg = Image.new("RGBA", (THUMB_W, THUMB_H), (20, 20, 30, 255))

    overlay = Image.new("RGBA", (THUMB_W, THUMB_H), BG_OVERLAY)
    canvas  = Image.alpha_composite(bg, overlay)

    # ── Album art (left square) ───────────────────────────────────────────────
    if bg_path and os.path.isfile(bg_path):
        art_src    = Image.open(bg_path).convert("RGBA")
        src_w, src_h = art_src.size
        min_dim    = min(src_w, src_h)
        cx, cy     = src_w // 2, src_h // 2
        art_src    = art_src.crop((
            cx - min_dim // 2, cy - min_dim // 2,
            cx + min_dim // 2, cy + min_dim // 2,
        ))
        art = art_src.resize((ART_SIZE, ART_SIZE), Image.LANCZOS)
    else:
        art = Image.new("RGBA", (ART_SIZE, ART_SIZE), (40, 40, 50, 255))

    draw_canvas = ImageDraw.Draw(canvas)
    border      = 4
    draw_canvas.rectangle(
        [ART_X - border, ART_Y - border,
         ART_X + ART_SIZE + border, ART_Y + ART_SIZE + border],
        fill=ART_BORDER_CLR,
    )
    canvas.paste(art, (ART_X, ART_Y), art)

    # ── Text block ────────────────────────────────────────────────────────────
    draw = ImageDraw.Draw(canvas)

    title_font  = _fit_text(draw, title,    title_font_path,  TITLE_SIZE_MAX,  TEXT_MAX_W)
    artist_font = _fit_text(draw, artist,   artist_font_path, ARTIST_SIZE_MAX, TEXT_MAX_W)
    tag_font    = _load_font(lyrics_font_path, TAG_SIZE)

    title_h  = draw.textbbox((0, 0), title,    font=title_font)[3]
    artist_h = draw.textbbox((0, 0), artist,   font=artist_font)[3]
    tag_h    = draw.textbbox((0, 0), "(lyrics)", font=tag_font)[3]

    gap      = 24
    total_h  = title_h + gap + artist_h + gap + tag_h
    y        = (THUMB_H - total_h) // 2

    draw.text((TEXT_X, y), title,      font=title_font,  fill=TITLE_COLOR)
    y += title_h + gap
    draw.text((TEXT_X, y), artist,     font=artist_font, fill=ARTIST_COLOR)
    y += artist_h + gap
    draw.text((TEXT_X, y), "(lyrics)", font=tag_font,    fill=LYRICS_TAG_CLR)

    # ── Save ──────────────────────────────────────────────────────────────────
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "thumbnail.jpg")
    canvas.convert("RGB").save(out_path, "JPEG", quality=95)
    log.info("✅ Thumbnail saved: %s", out_path)
    return out_path


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoForge Thumbnail Generator")
    parser.add_argument("--title",  required=True)
    parser.add_argument("--artist", required=True)
    parser.add_argument("--bg",     default=None,  help="Path to background image")
    parser.add_argument("--output", default=".",   help="Output directory")
    args = parser.parse_args()

    path = generate_thumbnail(
        title=args.title, artist=args.artist,
        bg_path=args.bg,  output_dir=args.output,
    )
    print(f"Thumbnail saved: {path}")