from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw

from echoforge.core.paths import ASSETS_DIR, BACKGROUNDS_DIR


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def download_file(url: str, path: Path) -> None:
    response = requests.get(url, timeout=30, headers={"User-Agent": "EchoForge/0.1"})
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)


def fallback_image(path: Path, size: tuple[int, int], text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, (32, 32, 36))
    draw = ImageDraw.Draw(image)
    draw.text((40, 40), text, fill=(235, 235, 235))
    image.save(path, quality=95)


def collect_music_thumbnail(project_dir: Path, review: dict[str, Any]) -> dict[str, Any]:
    images_dir = project_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    status_path = images_dir / "image_status.json"
    source_url = str(review.get("thumbnail_url") or "").strip()
    youtube_thumb = images_dir / "youtube_thumbnail.jpg"
    music_thumb = images_dir / "music_thumbnail.jpg"

    if music_thumb.exists() and music_thumb.stat().st_size > 0:
        return {"ok": True, "status": "exists", "path": str(music_thumb)}

    if source_url:
        try:
            download_file(source_url, youtube_thumb)
            shutil.copy2(youtube_thumb, music_thumb)
            result = {"ok": True, "status": "downloaded", "path": str(music_thumb), "source_url": source_url, "checked_at": now_iso()}
            write_json(status_path, result)
            return result
        except Exception as exc:
            write_json(status_path, {"ok": False, "status": "download_failed", "reason": str(exc), "source_url": source_url})

    fallback_image(music_thumb, (720, 720), str(review.get("display_title") or "Song"))
    result = {"ok": True, "status": "fallback_created", "path": str(music_thumb), "checked_at": now_iso()}
    write_json(status_path, result)
    return result


def project_number(project_dir: Path) -> int:
    try:
        return int(project_dir.name.split("_", 1)[0])
    except Exception:
        return 1


def choose_background(project_dir: Path) -> Path | None:
    backgrounds = sorted(p for p in BACKGROUNDS_DIR.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if not backgrounds:
        return None
    return backgrounds[(project_number(project_dir) - 1) % len(backgrounds)]


def collect_background_source(project_dir: Path, review: dict[str, Any]) -> dict[str, Any]:
    images_dir = project_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    out = images_dir / "background_source.jpg"
    if out.exists() and out.stat().st_size > 0:
        return {"ok": True, "status": "exists", "path": str(out)}

    source = choose_background(project_dir)
    if source:
        try:
            image = Image.open(source).convert("RGB")
            image.save(out, quality=95)
        except Exception:
            shutil.copy2(source, out)
        return {"ok": True, "status": "copied", "path": str(out), "source": str(source)}

    fallback_image(out, (1920, 1080), str(review.get("display_title") or "EchoForge"))
    return {"ok": True, "status": "fallback_created", "path": str(out)}


def find_font(size: int):
    from PIL import ImageFont

    for font_dir in [ASSETS_DIR / "fonts", Path("assets/fonts")]:
        if not font_dir.exists():
            continue
        for path in list(font_dir.rglob("*.ttf")) + list(font_dir.rglob("*.otf")):
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                pass
    return ImageFont.load_default()


def cover_resize(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    img = img.convert("RGB")
    sw, sh = img.size
    dw, dh = size
    scale = max(dw / sw, dh / sh)
    img = img.resize((int(sw * scale), int(sh * scale)), Image.Resampling.LANCZOS)
    left = (img.width - dw) // 2
    top = (img.height - dh) // 2
    return img.crop((left, top, left + dw, top + dh))


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        box = draw.textbbox((0, 0), test, font=font)
        if box[2] <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines
