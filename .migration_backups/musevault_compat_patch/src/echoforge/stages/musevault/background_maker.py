from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from echoforge.stages.musevault.image_service import (
    add_rounded_corners,
    add_soft_overlay,
    asset_defaults,
    cover_image,
    find_font,
    grayscale_blur,
    open_rgb,
    paste_rgba,
    resolve_background,
)

LYRICS_VIDEO_BACKGROUND_SIZE = (1920, 1080)


@dataclass
class LyricsVideoBackgroundResult:
    ok: bool
    project_no: int
    background_index: int
    background_path: str | None
    music_thumbnail_path: str
    output_path: str | None
    error: str | None
    created_assets: dict


def _norm(value: str) -> str:
    return ' '.join((value or '').split()).strip()


def create_lyrics_video_background(
    project_no: int,
    song_title: str,
    artist_text: str,
    music_thumbnail_path: str | Path,
    output_path: str | Path,
    background_path: str | Path | None = None,
) -> LyricsVideoBackgroundResult:
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        background, used_background_path, background_index = resolve_background(
            project_no, LYRICS_VIDEO_BACKGROUND_SIZE, explicit_path=background_path
        )
        background = grayscale_blur(background, blur_radius=1.1)
        background = add_soft_overlay(background, mode='light').convert('RGBA')
        draw = ImageDraw.Draw(background)

        title = _norm(song_title)
        artist = _norm(artist_text)

        cover_size = 70
        cover_x, cover_y = 42, 38
        cover = cover_image(open_rgb(music_thumbnail_path), (cover_size, cover_size)).filter(
            ImageFilter.UnsharpMask(radius=1)
        )
        cover = add_rounded_corners(cover, radius=4)
        paste_rgba(background, cover, (cover_x, cover_y))

        title_font = find_font('Odibee Sans', 30)
        artist_font = find_font('Odibee Sans', 25)
        text_x = cover_x + cover_size + 16
        draw.text((text_x, cover_y + 8), title, font=title_font, fill=(0, 0, 0))
        draw.text((text_x, cover_y + 40), artist, font=artist_font, fill=(18, 18, 18))

        defaults = asset_defaults()
        created_assets = {
            'background_path': str(used_background_path) if used_background_path else None,
            'logo_path': str(defaults['logo']) if defaults['logo'].exists() else None,
            'fonts': {
                'title': 'Odibee Sans',
                'artist': 'Odibee Sans',
            },
        }

        if defaults['logo'].exists():
            logo = Image.open(defaults['logo']).convert('RGBA')
            target_h = 138
            aspect = logo.width / max(logo.height, 1)
            target_w = int(target_h * aspect)
            logo = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)
            logo_x = 15
            logo_y = 1080 - 42 - target_h + 30
            paste_rgba(background, logo, (logo_x, logo_y))

        background.convert('RGB').save(out_path, quality=95)
        return LyricsVideoBackgroundResult(
            ok=True,
            project_no=project_no,
            background_index=background_index,
            background_path=str(used_background_path) if used_background_path else None,
            music_thumbnail_path=str(music_thumbnail_path),
            output_path=str(out_path),
            error=None,
            created_assets=created_assets,
        )
    except Exception as exc:  # noqa: BLE001
        return LyricsVideoBackgroundResult(
            ok=False,
            project_no=project_no,
            background_index=0,
            background_path=str(background_path) if background_path else None,
            music_thumbnail_path=str(music_thumbnail_path),
            output_path=None,
            error=str(exc),
            created_assets={},
        )

def make_lyrics_video_background(
    project_no: int,
    song_title: str,
    artist_text: str,
    music_thumbnail_path,
    output_path,
    background_path=None,
):
    return create_lyrics_video_background(
        project_no=project_no,
        song_title=song_title,
        artist_text=artist_text,
        music_thumbnail_path=music_thumbnail_path,
        output_path=output_path,
        background_path=background_path,
    )
