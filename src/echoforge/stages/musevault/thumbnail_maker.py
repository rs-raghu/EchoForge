from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from echoforge.stages.musevault.image_service import (
    add_rounded_corners,
    add_soft_overlay,
    asset_defaults,
    cover_image,
    draw_centered_text,
    draw_letter_spaced_text,
    find_font,
    fit_font,
    grayscale_blur,
    open_rgb,
    paste_rgba,
    resolve_background,
    text_size,
)

UPLOAD_THUMBNAIL_SIZE = (1280, 720)


@dataclass
class UploadThumbnailResult:
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


def create_upload_thumbnail(
    project_no: int,
    song_title: str,
    artist_text: str,
    music_thumbnail_path: str | Path,
    output_path: str | Path,
    background_path: str | Path | None = None,
) -> UploadThumbnailResult:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        background, used_background_path, background_index = resolve_background(
            project_no, UPLOAD_THUMBNAIL_SIZE, explicit_path=background_path
        )
        background = grayscale_blur(background, blur_radius=2.2)
        background = add_soft_overlay(background, mode='light').convert('RGBA')
        draw = ImageDraw.Draw(background)

        title = _norm(song_title)
        artist = _norm(artist_text)

        cover_size = 210
        cover_x, cover_y = 170, 240
        cover = cover_image(open_rgb(music_thumbnail_path), (cover_size, cover_size)).filter(
            ImageFilter.UnsharpMask(radius=1)
        )
        cover = add_rounded_corners(cover, radius=10)
        paste_rgba(background, cover, (cover_x, cover_y))

        title_font = fit_font(title, max_width=760, start_size=96, min_size=44, kind='Cherry Bomb One')
        artist_font = find_font('regular', 27)
        lyrics_font = find_font('bold', 25)

        text_center_x = 790
        title_bbox = draw_centered_text(draw, title, text_center_x, 250, title_font, fill=(0, 0, 0))
        artist_y = title_bbox[3] + 24
        draw_letter_spaced_text(
            draw,
            artist.upper(),
            text_center_x,
            artist_y,
            artist_font,
            tracking=8,
            fill=(28, 28, 28),
        )

        lyrics_text = '( LYRICS )'
        lyrics_w, _ = text_size(draw, lyrics_text, lyrics_font)
        draw.text((text_center_x - lyrics_w // 2, artist_y + 56), lyrics_text, font=lyrics_font, fill=(0, 0, 0))

        defaults = asset_defaults()
        created_assets = {
            'background_path': str(used_background_path) if used_background_path else None,
            'player_path': str(defaults['player']) if defaults['player'].exists() else None,
            'fonts': {
                'title': 'Cherry Bomb One',
                'artist': 'regular',
                'lyrics': 'bold',
            },
        }

        if defaults['player'].exists():
            player_img = Image.open(defaults['player']).convert('RGBA')
            scale_factor = 0.18
            new_width = int(player_img.width * scale_factor)
            new_height = int(player_img.height * scale_factor)
            player_img = player_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            center_x = cover_x + cover_size // 2
            player_x = center_x - (player_img.width // 2)
            player_y = cover_y + cover_size + 28
            paste_rgba(background, player_img, (player_x, player_y))

        background.convert('RGB').save(output_path, quality=95)
        return UploadThumbnailResult(
            ok=True,
            project_no=project_no,
            background_index=background_index,
            background_path=str(used_background_path) if used_background_path else None,
            music_thumbnail_path=str(music_thumbnail_path),
            output_path=str(output_path),
            error=None,
            created_assets=created_assets,
        )
    except Exception as exc:  # noqa: BLE001
        return UploadThumbnailResult(
            ok=False,
            project_no=project_no,
            background_index=0,
            background_path=str(background_path) if background_path else None,
            music_thumbnail_path=str(music_thumbnail_path),
            output_path=None,
            error=str(exc),
            created_assets={},
        )

def make_upload_thumbnail(
    project_no: int,
    song_title: str,
    artist_text: str,
    music_thumbnail_path,
    output_path,
    background_path=None,
):
    return create_upload_thumbnail(
        project_no=project_no,
        song_title=song_title,
        artist_text=artist_text,
        music_thumbnail_path=music_thumbnail_path,
        output_path=output_path,
        background_path=background_path,
    )
# Compatibility wrapper used by asset_collector.py
def make_upload_thumbnail(project_dir: Path, review: dict) -> dict:
    images_dir = project_dir / "images"
    renders_dir = project_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    project_no = int(project_dir.name.split("_", 1)[0]) if project_dir.name.split("_", 1)[0].isdigit() else 1
    music_thumbnail_path = images_dir / "music_thumbnail.jpg"
    background_path = images_dir / "background_source.jpg"
    out = renders_dir / "upload_thumbnail.jpg"

    result = create_upload_thumbnail(
        project_no=project_no,
        song_title=review.get("display_title") or review.get("search_title") or "Untitled",
        artist_text=review.get("display_artist") or review.get("search_artist") or "Unknown Artist",
        music_thumbnail_path=music_thumbnail_path,
        output_path=out,
        background_path=background_path if background_path.exists() else None,
    )
    return {
        "ok": bool(result.ok),
        "path": result.output_path,
        "background_path": result.background_path,
        "background_index": result.background_index,
        "details": result.created_assets,
        "error": result.error,
    }
