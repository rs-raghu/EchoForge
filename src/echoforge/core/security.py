"""Shared filesystem and render payload boundaries for all local editors."""
from __future__ import annotations
import math
from pathlib import Path
from urllib.parse import unquote

PUBLIC_EXTENSIONS = {".m4a", ".mp3", ".wav", ".webm", ".mp4", ".jpg", ".jpeg", ".png", ".webp", ".ttf", ".otf"}


def asset_path(project: Path, value, root: Path | None = None) -> Path:
    project = project.resolve()
    root = (root or project.parent.parent).resolve()
    raw = unquote(str(value)).replace("\\", "/")
    if raw.startswith("/media/"):
        raw = raw[7:]
    if raw.startswith("/root/"):
        raw = raw[6:]
    path = Path(raw)
    candidates = [path] if path.is_absolute() else [project / path, root / path]
    for candidate in candidates:
        resolved = candidate.resolve()
        allowed = resolved.is_relative_to(project) or resolved.is_relative_to(root / "assets")
        if allowed and resolved.suffix.lower() in PUBLIC_EXTENSIONS and not any(p.startswith(".") for p in resolved.relative_to(project if resolved.is_relative_to(project) else root / "assets").parts):
            if resolved.exists():
                return resolved
    # Missing files still require a valid boundary; caller may decide how to report them.
    for candidate in candidates:
        resolved = candidate.resolve()
        allowed = resolved.is_relative_to(project) or resolved.is_relative_to(root / "assets")
        if allowed and not any(p.startswith(".") for p in resolved.relative_to(project if resolved.is_relative_to(project) else root / "assets").parts) and resolved.suffix.lower() in PUBLIC_EXTENSIONS:
            return resolved
    raise ValueError("Asset must be public media inside this project or shared assets")


def number(value, name, low, high):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {name}") from None
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return result


def validate_editor(data, project: Path):
    if not isinstance(data, dict):
        raise ValueError("Editor project must be an object")
    canvas = data.get("canvas") or {}
    width = number(data.get("width", canvas.get("width", 1920)), "width", 320, 3840)
    height = number(data.get("height", canvas.get("height", 1080)), "height", 240, 2160)
    if int(width) != width or int(height) != height or int(width) % 2 or int(height) % 2:
        raise ValueError("Canvas dimensions must be even integers")
    for container in (data, data.get("project") or {}):
        if "duration" in container:
            number(container["duration"], "project duration", 0.001, 7200)
    tracks = data.get("tracks", [])
    if not isinstance(tracks, list) or len(tracks) > 100:
        raise ValueError("Invalid tracks")
    clips = list(data.get("clips") or [])
    for track in tracks:
        if not isinstance(track, dict) or not isinstance(track.get("clips", []), list):
            raise ValueError("Invalid track")
        clips.extend(track.get("clips", []))
    if len(clips) > 20000:
        raise ValueError("Too many clips")
    for clip in clips:
        if not isinstance(clip, dict):
            raise ValueError("Invalid clip")
        start = number(clip.get("start", 0), "clip start", 0, 7200)
        end = number(clip.get("end", start + clip.get("duration", 0)), "clip end", 0, 7200)
        if end <= start:
            raise ValueError("Clip end must follow its start")
        style = clip.get("style") or {}
        if not isinstance(style, dict) or len(str(clip.get("text", ""))) > 10000:
            raise ValueError("Invalid text or style")
        number(style.get("fontSize", style.get("font_size", clip.get("fontSize", 50))), "font size", 1, 1000)
        number(style.get("opacity", clip.get("opacity", 1)), "opacity", 0, 1)
        number(clip.get("volume", 1), "volume", 0, 10)
        for container in (clip, style):
            for key, low, high in (
                ("x", -10000, 10000), ("y", -10000, 10000),
                ("width", 0, 16384), ("height", 0, 16384),
                ("rotation", -36000, 36000), ("strokeWidth", 0, 100),
                ("stroke_width", 0, 100), ("letterSpacing", -100, 100),
                ("lineHeight", 0.1, 10), ("line_height", 0.1, 10),
            ):
                if key in container: number(container[key], key, low, high)
        for key in ("path", "src", "file", "asset", "url"):
            if clip.get(key):
                asset_path(project, clip[key])
    for key, value in (data.get("assets") or {}).items():
        if value and key not in {"final_lrc", "final_json"}:
            asset_path(project, value)
    return data
