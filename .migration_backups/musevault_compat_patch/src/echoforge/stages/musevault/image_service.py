from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from echoforge.core.paths import ASSETS_DIR, BACKGROUNDS_DIR, ROOT_DIR

DEFAULTS_DIR = ASSETS_DIR / 'defaults'
FONTS_DIR = ASSETS_DIR / 'fonts'

SUPPORTED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}
SUPPORTED_FONT_EXTS = {'.ttf', '.otf'}

FONT_KEYWORDS = {
    'Cherry Bomb One': ['cherry', 'bomb'],
    'Odibee Sans': ['odibee'],
    'Bernier': ['bernier'],
    'regular': ['arial', 'roboto', 'dejavu', 'open', 'sans'],
    'bold': ['bold', 'arialbd', 'roboto', 'dejavu'],
    'heavy': ['impact', 'black', 'condensed', 'bebas', 'bold'],
}


def _iter_files(folder: Path, exts: set[str]) -> list[Path]:
    if not folder.exists():
        return []
    return sorted([p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in exts])


def list_background_files() -> list[Path]:
    return _iter_files(BACKGROUNDS_DIR, SUPPORTED_IMAGE_EXTS)


def list_font_files() -> list[Path]:
    return _iter_files(FONTS_DIR, SUPPORTED_FONT_EXTS)


def asset_defaults() -> dict[str, Path]:
    return {
        'logo': DEFAULTS_DIR / 'logo.png',
        'player': DEFAULTS_DIR / 'player.png',
    }


def _project_index(project_no: int, total: int) -> int:
    if total <= 0:
        return 0
    return (max(project_no, 1) - 1) % total


def resolve_background(project_no: int, size: tuple[int, int], explicit_path: str | Path | None = None) -> tuple[Image.Image, Path | None, int]:
    if explicit_path:
        explicit = Path(explicit_path)
        if explicit.exists():
            img = open_rgb(explicit)
            return cover_image(img, size), explicit, 1

    backgrounds = list_background_files()
    if backgrounds:
        idx = _project_index(project_no, len(backgrounds))
        chosen = backgrounds[idx]
        img = open_rgb(chosen)
        return cover_image(img, size), chosen, idx + 1

    fallback = Image.new('RGB', size, (214, 214, 214))
    return fallback, None, 0


def find_font_path(kind: str) -> Path | None:
    fonts = list_font_files()
    lowered_map = [(p, p.name.lower()) for p in fonts]
    keywords = FONT_KEYWORDS.get(kind, [kind.lower()])

    for path, name in lowered_map:
        if all(k in name for k in keywords):
            return path

    folder_hint = {
        'Cherry Bomb One': 'Cherry_Bomb_One',
        'Odibee Sans': 'Odibee_Sans',
        'Bernier': 'Bernier',
    }.get(kind)
    if folder_hint:
        hint_dir = FONTS_DIR / folder_hint
        for p in _iter_files(hint_dir, SUPPORTED_FONT_EXTS):
            return p

    if kind == 'heavy':
        for candidate in ['Cherry Bomb One', 'Odibee Sans', 'bold', 'regular']:
            path = find_font_path(candidate)
            if path:
                return path
    if kind == 'bold':
        for candidate in ['Odibee Sans', 'regular']:
            path = find_font_path(candidate)
            if path:
                return path
    if kind == 'regular':
        for p in fonts:
            return p
    return None


def find_font(kind: str = 'regular', size: int = 40) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = find_font_path(kind)
    if path:
        try:
            return ImageFont.truetype(str(path), size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def download_image(url: str, output_path: str | Path, timeout: int = 30) -> Path:
    if not url:
        raise ValueError('Image URL is missing.')
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=timeout, headers={'User-Agent': 'Mozilla/5.0'})
    response.raise_for_status()
    out_path.write_bytes(response.content)
    return out_path


def open_rgb(path: str | Path) -> Image.Image:
    return Image.open(path).convert('RGB')


def _ensure_rgb(image: Image.Image) -> Image.Image:
    return image if image.mode == 'RGB' else image.convert('RGB')


def cover_image(image: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    target_w, target_h = target_size
    image = _ensure_rgb(image)
    src_w, src_h = image.size
    scale = max(target_w / src_w, target_h / src_h)
    new_size = (int(src_w * scale), int(src_h * scale))
    image = image.resize(new_size, Image.Resampling.LANCZOS)
    left = (new_size[0] - target_w) // 2
    top = (new_size[1] - target_h) // 2
    return image.crop((left, top, left + target_w, top + target_h))


def contain_image(image: Image.Image, box_size: tuple[int, int], fill=(0, 0, 0)) -> Image.Image:
    canvas = Image.new('RGB', box_size, fill)
    image = _ensure_rgb(image)
    image.thumbnail(box_size, Image.Resampling.LANCZOS)
    x = (box_size[0] - image.width) // 2
    y = (box_size[1] - image.height) // 2
    canvas.paste(image, (x, y))
    return canvas


def add_rounded_corners(image: Image.Image, radius: int = 24) -> Image.Image:
    image = image.convert('RGBA')
    mask = Image.new('L', image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width, image.height), radius=radius, fill=255)
    image.putalpha(mask)
    return image


def paste_rgba(base: Image.Image, overlay: Image.Image, xy: tuple[int, int]) -> None:
    if overlay.mode != 'RGBA':
        overlay = overlay.convert('RGBA')
    base.paste(overlay, xy, overlay)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def fit_font(text: str, max_width: int, start_size: int, min_size: int, kind: str = 'heavy') -> ImageFont.ImageFont:
    probe = Image.new('RGB', (8, 8))
    draw = ImageDraw.Draw(probe)
    for size in range(start_size, min_size - 1, -2):
        font = find_font(kind, size)
        if text_size(draw, text, font)[0] <= max_width:
            return font
    return find_font(kind, min_size)


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    center_x: int,
    y: int,
    font: ImageFont.ImageFont,
    fill=(0, 0, 0),
    stroke_width: int = 0,
    stroke_fill=(255, 255, 255),
) -> tuple[int, int, int, int]:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    width = bbox[2] - bbox[0]
    x = center_x - width // 2
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
    return draw.textbbox((x, y), text, font=font, stroke_width=stroke_width)


def draw_letter_spaced_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    center_x: int,
    y: int,
    font: ImageFont.ImageFont,
    tracking: int = 6,
    fill=(0, 0, 0),
) -> tuple[int, int, int, int]:
    widths = []
    total_width = 0
    for ch in text:
        ch_bbox = draw.textbbox((0, 0), ch, font=font)
        ch_w = ch_bbox[2] - ch_bbox[0]
        widths.append(ch_w)
        total_width += ch_w
    if len(text) > 1:
        total_width += tracking * (len(text) - 1)
    x = center_x - total_width // 2
    start_x = x
    max_h = 0
    for i, ch in enumerate(text):
        draw.text((x, y), ch, font=font, fill=fill)
        ch_bbox = draw.textbbox((x, y), ch, font=font)
        max_h = max(max_h, ch_bbox[3] - ch_bbox[1])
        x += widths[i] + tracking
    return (start_x, y, start_x + total_width, y + max_h)


def grayscale_blur(image: Image.Image, blur_radius: float = 2) -> Image.Image:
    image = ImageOps.grayscale(image).convert('RGB')
    if blur_radius > 0:
        image = image.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    return image


def add_soft_overlay(image: Image.Image, mode: str = 'light') -> Image.Image:
    overlay = Image.new('RGBA', image.size, (255, 255, 255, 74 if mode == 'light' else 36))
    base = image.convert('RGBA')
    base.alpha_composite(overlay)
    return base


def validate_musevault_assets() -> dict:
    defaults = asset_defaults()
    backgrounds = list_background_files()
    fonts = list_font_files()
    report = {
        'ok': True,
        'root': str(ROOT_DIR),
        'assets_dir': str(ASSETS_DIR),
        'backgrounds_dir': str(BACKGROUNDS_DIR),
        'defaults_dir': str(DEFAULTS_DIR),
        'background_count': len(backgrounds),
        'backgrounds_present': len(backgrounds) > 0,
        'player_exists': defaults['player'].exists(),
        'logo_exists': defaults['logo'].exists(),
        'fonts_found': [str(p) for p in fonts],
        'font_checks': {},
        'missing': [],
    }
    for family in ['Cherry Bomb One', 'Odibee Sans', 'Bernier']:
        path = find_font_path(family)
        report['font_checks'][family] = str(path) if path else None
        if path is None:
            report['missing'].append(f'missing font: {family}')
    if not backgrounds:
        report['missing'].append('no backgrounds found in assets/backgrounds')
    if not defaults['player'].exists():
        report['missing'].append('missing assets/defaults/player.png')
    if not defaults['logo'].exists():
        report['missing'].append('missing assets/defaults/logo.png')
    report['ok'] = not report['missing']
    return report
