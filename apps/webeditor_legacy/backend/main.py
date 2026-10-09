from __future__ import annotations

import json
import sys
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from echoforge.core.storage import atomic_json, update_json
from echoforge.core.security import asset_path, validate_editor

APP_DIR = Path(__file__).resolve().parent
WEBEDITOR_ROOT = APP_DIR.parent
# Clean EF_CLEAN layout: apps/webeditor_legacy/backend/main.py -> EF_CLEAN
EF_ROOT = Path(os.environ.get("ECHOFORGE_ROOT", WEBEDITOR_ROOT.parent.parent)).resolve()
PROJECTS_ROOT = Path(os.environ.get("ECHOFORGE_PROJECTS_ROOT", EF_ROOT / "projects")).resolve()
# Rendering uses real project fonts. The Vite frontend uses frontend/public/fonts, copied by the patch script.
FONTS_DIR = Path(os.environ.get("ECHOFORGE_FONTS_DIR", EF_ROOT / "assets" / "fonts")).resolve()

VIDEO_WIDTH = int(os.environ.get("ECHOFORGE_VIDEO_WIDTH", "1920"))
VIDEO_HEIGHT = int(os.environ.get("ECHOFORGE_VIDEO_HEIGHT", "1080"))
FPS = int(os.environ.get("ECHOFORGE_FPS", "30"))

DEFAULT_LYRIC_FONT = os.environ.get("ECHOFORGE_DEFAULT_LYRIC_FONT", "Bernier")
DEFAULT_LYRIC_FONT_SIZE = int(os.environ.get("ECHOFORGE_DEFAULT_LYRIC_FONT_SIZE", "50"))
DEFAULT_LYRIC_COLOR = os.environ.get("ECHOFORGE_DEFAULT_LYRIC_COLOR", "#000000")
DEFAULT_LYRIC_STROKE_COLOR = os.environ.get("ECHOFORGE_DEFAULT_LYRIC_STROKE_COLOR", "#000000")
DEFAULT_LYRIC_STROKE_WIDTH = float(os.environ.get("ECHOFORGE_DEFAULT_LYRIC_STROKE_WIDTH", "0"))
LYRIC_DEFAULTS_VERSION = 3

EDITOR_FILENAME = "editor/editor_project.json"
ALLOWED_MEDIA_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp",
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".mp4", ".mov", ".webm",
    ".srt", ".vtt", ".ass", ".json",
}

app = FastAPI(title="EchoForge WebEditor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware('http')
async def local_boundary(request: Request, call_next):
    origin=request.headers.get('origin')
    allowed={str(request.base_url).rstrip('/'),'http://localhost:5173','http://127.0.0.1:5173'}
    if request.url.hostname not in {'localhost','127.0.0.1','::1','testserver'} or (origin and origin not in allowed):
        return JSONResponse({'detail':'Local editor origin required'},status_code=403)
    if request.method in {'POST','PUT','PATCH'}:
        length=request.headers.get('content-length','0')
        if not length.isdigit() or int(length)>8*1024*1024:
            return JSONResponse({'detail':'Invalid request size'},status_code=413)
    return await call_next(request)


class SaveProjectRequest(BaseModel):
    project: dict[str, Any]


class UpdateClipRequest(BaseModel):
    patch: dict[str, Any]


class ReloadLyricsRequest(BaseModel):
    keep_style: bool = True


class ScheduleUploadRequest(BaseModel):
    privacy: str = "scheduled"
    publish_at: str | None = None
    video_path: str | None = None
    start_upload: bool = False


RENDER_EXECUTOR = ThreadPoolExecutor(max_workers=1)
RENDER_JOBS: dict[str, dict[str, Any]] = {}
RENDER_JOBS_LOCK = threading.Lock()


# =====================================================================
# INTERNAL CONSOLIDATED FACTORIES & HELPERS
# =====================================================================

def _clean_hex(hex_val: str, fallback: str = "000000") -> str:
    """Normalizes 3-digit or 6-digit hex strings into pure 6-char hex."""
    val = str(hex_val or f"#{fallback}").strip().lstrip("#")
    if len(val) == 3:
        val = "".join(ch * 2 for ch in val)
    return val if len(val) == 6 else fallback


def _create_lyric_clip(line: dict[str, Any], width: int, height: int, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Single factory for standard lyric clip payloads."""
    clip = {
        "id": f"lyric_{line['index']:04d}",
        "type": "text",
        "start": line["start"],
        "end": line["end"],
        "text": line["text"],
        "x": width / 2,
        "y": height / 2,
        "fontSize": DEFAULT_LYRIC_FONT_SIZE,
        "fontFamily": DEFAULT_LYRIC_FONT,
        "color": DEFAULT_LYRIC_COLOR,
        "strokeColor": DEFAULT_LYRIC_STROKE_COLOR,
        "strokeWidth": DEFAULT_LYRIC_STROKE_WIDTH,
        "align": "center",
        "opacity": 100,
        "letterSpacing": 0,
        "visible": True,
        "locked": False,
    }
    if overrides:
        clip.update(overrides)
    return clip


def validate_legacy(project_dir,project):
    import copy
    normalized=copy.deepcopy(project)
    for track in normalized.get('tracks',[]):
        for clip in track.get('clips',[]):
            clip['opacity']=float(clip.get('opacity',100))/100
    try: validate_editor(normalized,project_dir)
    except (ValueError,TypeError) as exc: raise HTTPException(422,str(exc)) from exc


def save_project_bundle(project_dir: Path, project: dict[str, Any]) -> None:
    """Guarantees editor project and state contracts update together."""
    validate_legacy(project_dir,project)
    write_json(project_dir / EDITOR_FILENAME, project)
    write_project_state(project_dir, project)


# =====================================================================
# CORE SYSTEM
# =====================================================================

def set_render_job(job_id: str, **patch: Any) -> None:
    with RENDER_JOBS_LOCK:
        job = RENDER_JOBS.setdefault(job_id, {})
        job.update(patch)
        job["updatedAt"] = time.time()


def get_render_job(job_id: str) -> dict[str, Any] | None:
    with RENDER_JOBS_LOCK:
        job = RENDER_JOBS.get(job_id)
        return dict(job) if job else None


def ensure_projects_root() -> Path:
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    return PROJECTS_ROOT


def safe_project_dir(project_id: str) -> Path:
    project_id = project_id.strip().replace("\\", "/")
    if not project_id or project_id in {".", ".."} or "/" in project_id:
        raise HTTPException(status_code=400, detail="Invalid project id")

    project_dir = (PROJECTS_ROOT / project_id).resolve()
    try:
        project_dir.relative_to(PROJECTS_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project path")

    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    return project_dir


def safe_child(project_dir: Path, relative_path: str | Path) -> Path:
    rel = str(relative_path).strip().replace("\\", "/")
    if not rel:
        raise HTTPException(status_code=400, detail="Empty path")

    target = (project_dir / rel).resolve()
    try:
        target.relative_to(project_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Path escapes project folder")

    return target


def rel_to_project(project_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_dir.resolve()).as_posix()
    except Exception:
        return path.as_posix()


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_json(path, payload)

def get_tubeharbor_dir() -> Path:
    """
    Finds TubeHarbor folder from EF root.
    Your actual folder is: EF/5. TubeHarbor
    """
    candidates = [
        EF_ROOT / "5. TubeHarbor",
        EF_ROOT / "TubeHarbor",
    ]

    for candidate in candidates:
        if (candidate / "run.py").exists():
            return candidate.resolve()

    raise FileNotFoundError(
        f"TubeHarbor run.py not found. Checked: {[str(c) for c in candidates]}"
    )


def get_tubeharbor_python(tubeharbor_dir: Path) -> str:
    """
    Prefer TubeHarbor's own venv Python so google/youtube dependencies are available.
    Falls back to current backend Python.
    """
    candidates = [
        tubeharbor_dir / ".venv" / "Scripts" / "python.exe",
        tubeharbor_dir / ".venv" / "bin" / "python",
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return sys.executable


def wait_for_tubeharbor_process(process: subprocess.Popen, log_file, log_path: Path) -> None:
    """Append TubeHarbor exit code to the same project log and close the handle."""
    try:
        code = process.wait()
        log_file.write(f"\nTubeHarbor exited with code: {code}\n")
        log_file.flush()
    except Exception as exc:
        try:
            log_file.write(f"\nTubeHarbor monitor failed: {exc}\n")
            log_file.flush()
        except Exception:
            pass
    finally:
        try:
            log_file.close()
        except Exception:
            pass


def start_tubeharbor_upload_for_render(project_dir: Path, privacy: str | None = None) -> dict[str, Any]:
    from echoforge.stages.tubeharbor.youtube_uploader import upload_to_youtube
    result=upload_to_youtube(project_dir/'renders/final_lyrics_video.mp4',project_dir,{'visibility':privacy or 'private'})
    if not result.get('ok'): raise RuntimeError(result.get('reason','Upload failed'))
    return result


def find_first_existing(project_dir: Path, candidates: list[str]) -> str | None:
    for candidate in candidates:
        path = project_dir / candidate
        if path.exists() and path.is_file():
            return candidate.replace("\\", "/")
    return None


def find_first_by_suffix(project_dir: Path, folders: list[str], suffixes: set[str]) -> str | None:
    for folder in folders:
        root = project_dir / folder
        if not root.exists():
            continue
        files = sorted(
            [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in suffixes],
            key=lambda p: (len(p.parts), p.name.lower()),
        )
        if files:
            return rel_to_project(project_dir, files[0])
    return None


def ffprobe_duration_seconds(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.exists():
        return None

    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        value = completed.stdout.strip()
        return float(value) if value else None
    except Exception:
        return None


def detect_assets(project_dir: Path) -> dict[str, Any]:
    manifest = read_json(project_dir / "asset_manifest.json") or {}
    project_json = read_json(project_dir / "project_state.json") or read_json(project_dir / "metadata_review.json") or read_json(project_dir / "project.json") or {}

    audio_suffixes = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".mp4"}
    image_suffixes = {".jpg", ".jpeg", ".png", ".webp"}

    def try_rel(value: Any) -> str | None:
        if not value:
            return None
        p = Path(str(value))
        if p.is_absolute() and p.exists():
            try:
                return p.resolve().relative_to(project_dir.resolve()).as_posix()
            except Exception:
                return None
        rel = str(value).replace("\\", "/").strip()
        if not rel:
            return None
        return rel if (project_dir / rel).is_file() else None

    def nested_get(data: dict[str, Any], *keys: str) -> Any:
        cur: Any = data
        for key in keys:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        return cur

    def first_from_keys(keys: list[str], *sources: dict[str, Any]) -> str | None:
        for key in keys:
            for source in sources:
                found = try_rel(source.get(key)) if isinstance(source, dict) else None
                if found:
                    return found
        return None

    background = first_from_keys(
        ["video_background", "background", "background_path", "video_background_path"],
        manifest, project_json
    )
    audio = first_from_keys(
        ["audio", "audio_path", "song_audio", "song_audio_path", "downloaded_audio", "downloaded_audio_path", "audio_file"],
        manifest, project_json
    )
    thumbnail = first_from_keys(
        ["upload_thumbnail", "thumbnail", "thumbnail_path", "upload_thumbnail_path"],
        manifest, project_json
    )

    background = background or try_rel(nested_get(manifest, "results", "lyrics_video_background", "output_path")) or try_rel(nested_get(manifest, "results", "lyrics_video_background", "path"))
    audio = audio or try_rel(nested_get(manifest, "results", "youtube", "audio_path")) or try_rel(nested_get(manifest, "results", "youtube", "downloaded_audio_path")) or try_rel(nested_get(manifest, "results", "youtube", "path"))
    thumbnail = thumbnail or try_rel(nested_get(manifest, "results", "upload_thumbnail", "output_path")) or try_rel(nested_get(manifest, "results", "upload_thumbnail", "path"))

    background = background or find_first_existing(project_dir, [
        "renders/lyrics_video_background.jpg", "renders/lyrics_video_background.png",
        "renders/video_background.jpg", "renders/video_background.png",
        "images/video_background.jpg", "images/video_background.png",
        "media/video_background.jpg", "media/background.jpg",
        "kdenlive_edit/media/background_1920x1080.jpg", "background_1920x1080.jpg",
    ])
    audio = audio or find_first_existing(project_dir, [
        "audio/song_audio.wav", "audio/song_audio.mp3", "audio/song_audio.m4a", "audio/song_audio.webm", "audio/song_audio.opus",
        "youtube/audio/song_audio.wav", "youtube/audio/song_audio.mp3", "youtube/audio/song_audio.m4a",
        "media/song_audio.wav", "media/song_audio.mp3", "song_audio.wav", "song_audio.mp3",
    ])
    thumbnail = thumbnail or find_first_existing(project_dir, [
        "renders/upload_thumbnail.jpg", "renders/upload_thumbnail.png",
        "images/upload_thumbnail.jpg", "images/thumbnail.jpg", "thumbnail.jpg",
    ])

    background = background or find_first_by_suffix(project_dir, ["renders", "images", "media", "assets", "kdenlive_edit/media"], image_suffixes)
    audio = audio or find_first_by_suffix(project_dir, ["audio", "youtube/audio", "media", "assets", "downloads", "kdenlive_edit/media"], audio_suffixes)
    thumbnail = thumbnail or find_first_by_suffix(project_dir, ["renders", "images", "media", "assets"], image_suffixes)

    if audio and str(audio).replace("\\", "/").startswith("kdenlive_edit/"):
        orig = find_first_by_suffix(project_dir, ["youtube/audio"], audio_suffixes)
        if orig:
            audio = orig

    if not audio:
        ignored = {".venv", "node_modules", "__pycache__", "renders", "editor_render_temp"}
        candidates: list[Path] = [
            f for f in project_dir.rglob("*") 
            if f.is_file() and f.suffix.lower() in audio_suffixes and not any(p in ignored for p in f.parts)
        ]
        if candidates:
            candidates.sort(key=lambda p: (0 if ("song" in p.name.lower() or "audio" in p.name.lower()) else 1, len(p.as_posix()), p.name.lower()))
            audio = rel_to_project(project_dir, candidates[0])

    return {"background": background, "audio": audio, "thumbnail": thumbnail}


def parse_srt_time(value: str) -> float:
    parts = value.strip().replace(",", ".").split(":")
    if len(parts) != 3:
        return 0.0
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def parse_srt(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except Exception:
        text = path.read_text(encoding="utf-8", errors="ignore")

    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n").strip())
    lines: list[dict[str, Any]] = []

    for block in blocks:
        rows = [row.strip() for row in block.split("\n") if row.strip()]
        if not rows:
            continue

        time_row_idx = next((i for i, r in enumerate(rows) if "-->" in r), None)
        if time_row_idx is None:
            continue

        start_s, end_s = [part.strip() for part in rows[time_row_idx].split("-->", 1)]
        text_value = " ".join(rows[time_row_idx + 1:]).strip()
        if not text_value:
            continue

        lines.append({
            "index": len(lines) + 1,
            "start": round(parse_srt_time(start_s), 3),
            "end": round(parse_srt_time(end_s), 3),
            "text": re.sub(r"<[^>]+>", "", text_value),
        })

    return lines


def detect_lyrics(project_dir: Path) -> list[dict[str, Any]]:
    from echoforge.core.sync_state import validate_sync_pair
    validate_sync_pair(project_dir)
    for path in [project_dir / "sync/final_synced_lyrics.json", project_dir / "subtitles/final_synced_lyrics.json"]:
        payload = read_json(path)
        if payload and (raw := payload.get("lines") or payload.get("lyrics")):
            return normalize_lines(raw)

    for path in [project_dir / "sync/final_synced_lyrics.srt", project_dir / "final_synced_lyrics.srt", project_dir / "lyrics.srt"]:
        if path.exists() and (lines := parse_srt(path)):
            return normalize_lines(lines)

    return []


def normalize_lines(raw_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    for raw in raw_lines:
        text = re.sub(r"\s+", " ", str(raw.get("text", "")).strip())
        if not text:
            continue
        start = float(raw.get("start", raw.get("start_seconds", 0.0)) or 0.0)
        end = float(raw.get("end", raw.get("end_seconds", start + 2.0)) or (start + 2.0))
        normalized.append({
            "index": 0,
            "start": round(max(0.0, start), 3),
            "end": round(max(start + 0.35, end), 3),
            "text": text,
        })

    normalized.sort(key=lambda item: item["start"])
    for i, item in enumerate(normalized, start=1):
        item["index"] = i
    return normalized


def build_editor_project(project_dir: Path) -> dict[str, Any]:
    project_id = project_dir.name
    assets = detect_assets(project_dir)
    lines = detect_lyrics(project_dir)

    audio_path = project_dir / assets["audio"] if assets.get("audio") else None
    audio_dur = ffprobe_duration_seconds(audio_path) if audio_path else None
    lyric_dur = max([float(l["end"]) for l in lines], default=180.0)
    duration = round(float(audio_dur or lyric_dur or 180.0), 3)

    project_json = read_json(project_dir / "project_state.json") or read_json(project_dir / "metadata_review.json") or read_json(project_dir / "project.json") or {}
    title = next((str(project_json[k]) for k in ["song_title", "title", "name"] if project_json.get(k)), project_id)
    artist = next((str(project_json[k]) for k in ["artist_text", "artist", "artists"] if project_json.get(k)), "")

    lyric_clips = [_create_lyric_clip(line, VIDEO_WIDTH, VIDEO_HEIGHT) for line in lines]

    return {
        "schemaVersion": 1,
        "projectId": project_id,
        "title": title,
        "artist": artist,
        "width": VIDEO_WIDTH,
        "height": VIDEO_HEIGHT,
        "fps": FPS,
        "duration": duration,
        "assets": assets,
        "tracks": [
            {
                "id": "background",
                "name": "Background",
                "type": "image",
                "clips": [{
                    "id": "background_1", "type": "image", "start": 0, "end": duration,
                    "src": assets.get("background"), "x": 0, "y": 0,
                    "width": VIDEO_WIDTH, "height": VIDEO_HEIGHT, "fit": "cover",
                    "visible": True, "locked": False,
                }],
            },
            {"id": "lyrics", "name": "Lyrics", "type": "text", "clips": lyric_clips},
            {
                "id": "audio",
                "name": "Audio",
                "type": "audio",
                "clips": [{
                    "id": "audio_1", "type": "audio", "start": 0, "end": duration,
                    "src": assets.get("audio"),
                    "sourceStart": 0,
                    "sourceEnd": duration,
                    "volume": 1.0, "visible": True, "locked": False,
                }],
            },
        ],
        "createdBy": "EchoForge WebEditor",
        "styleDefaultsAppliedVersion": LYRIC_DEFAULTS_VERSION,
    }


def apply_default_lyric_style(project: dict[str, Any]) -> dict[str, Any]:
    width = int(project.get("width") or VIDEO_WIDTH)
    height = int(project.get("height") or VIDEO_HEIGHT)

    style_patch = {
        "x": width / 2,
        "y": height / 2,
        "fontSize": DEFAULT_LYRIC_FONT_SIZE,
        "fontFamily": DEFAULT_LYRIC_FONT,
        "color": DEFAULT_LYRIC_COLOR,
        "strokeColor": DEFAULT_LYRIC_STROKE_COLOR,
        "strokeWidth": DEFAULT_LYRIC_STROKE_WIDTH,
        "align": "center",
        "opacity": 100,
        "letterSpacing": 0,
        "visible": True,
    }

    for track in project.get("tracks", []):
        if track.get("id") == "lyrics":
            for clip in track.get("clips", []):
                if clip.get("type") == "text":
                    # Only patch styling/position. Never overwrite id/start/end/text.
                    clip.update(style_patch)

    project["styleDefaultsAppliedVersion"] = LYRIC_DEFAULTS_VERSION
    return project


def write_project_state(project_dir: Path, project: dict[str, Any]) -> None:
    def merge(state):
        state.update(title=project.get('title') or state.get('title',project_dir.name),
                     artist=project.get('artist') or state.get('artist',''), assets=project.get('assets') or {},
                     editorProject=EDITOR_FILENAME, updated_at=time.time())
    update_json(project_dir / 'project_state.json',merge,{})


def repair_editor_project_assets(project_dir: Path, project: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    detected = detect_assets(project_dir)
    assets = dict(project.get("assets") or {})
    changed = False

    def is_stale(key: str, rel: Any) -> bool:
        val = str(rel or "").replace("\\", "/")
        if not val or not safe_child(project_dir, val).exists():
            return True
        if key == "background":
            return val.startswith("kdenlive_edit/") or val.endswith("music_thumbnail_from_chart.jpg")
        return val.startswith("kdenlive_edit/") or (key == "audio" and val.startswith("sync/"))

    for key in ("background", "audio", "thumbnail"):
        if detected.get(key) and is_stale(key, assets.get(key)):
            if assets.get(key) != detected[key]:
                assets[key] = detected[key]
                changed = True

    if changed:
        project["assets"] = assets

    for track in project.get("tracks", []):
        if (t_id := track.get("id")) in {"background", "audio"} and assets.get(t_id):
            for clip in track.get("clips", []):
                if is_stale(t_id, clip.get("src")) and clip.get("src") != assets[t_id]:
                    clip["src"] = assets[t_id]
                    changed = True
                if t_id == "audio":
                    start = float(clip.get("start", 0) or 0)
                    end = float(clip.get("end", start) or start)
                    if "sourceStart" not in clip:
                        clip["sourceStart"] = 0.0
                        changed = True
                    if "sourceEnd" not in clip:
                        clip["sourceEnd"] = round(float(clip.get("sourceStart") or 0.0) + max(0.0, end - start), 3)
                        changed = True
                    if "volume" not in clip:
                        clip["volume"] = 1.0
                        changed = True

    for track in project.get("tracks", []):
        if track.get("id") == "lyrics":
            for clip in track.get("clips", []):
                if clip.get("type") == "text":
                    if "opacity" not in clip: clip["opacity"] = 100; changed = True
                    if "letterSpacing" not in clip: clip["letterSpacing"] = 0; changed = True

    return project, changed


def load_or_bootstrap(project_dir: Path, force: bool = False) -> dict[str, Any]:
    path = project_dir / EDITOR_FILENAME
    if path.exists() and not force:
        payload = read_json(path)
        if payload:
            changed = False
            if int(payload.get("styleDefaultsAppliedVersion", 0) or 0) < LYRIC_DEFAULTS_VERSION:
                payload = apply_default_lyric_style(payload)
                changed = True
            payload, repaired = repair_editor_project_assets(project_dir, payload)
            if changed or repaired:
                save_project_bundle(project_dir, payload)
            return payload

    project, _ = repair_editor_project_assets(project_dir, build_editor_project(project_dir))
    save_project_bundle(project_dir, project)
    return project


def get_track(project: dict[str, Any], track_id: str) -> dict[str, Any] | None:
    return next((t for t in project.get("tracks", []) if t.get("id") == track_id), None)


def find_clip(project: dict[str, Any], clip_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for track in project.get("tracks", []):
        for clip in track.get("clips", []):
            if clip.get("id") == clip_id:
                return track, clip
    return None


def seconds_to_ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600); seconds -= h * 3600
    m = int(seconds // 60); seconds -= m * 60
    s = int(seconds); cs = int(round((seconds - s) * 100))
    if cs >= 100: s += 1; cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def hex_to_ass_color(hex_value: str, alpha: str = "00") -> str:
    val = _clean_hex(hex_value, "ffffff")
    return f"&H{alpha}{val[4:6]}{val[2:4]}{val[0:2]}"


def hex_to_rgba(hex_value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    val = _clean_hex(hex_value, "000000")
    try:
        return (int(val[0:2], 16), int(val[2:4], 16), int(val[4:6], 16), alpha)
    except ValueError:
        return (0, 0, 0, alpha)


def has_project_fonts() -> bool:
    if not FONTS_DIR.exists():
        return False
    return any(
        p.is_file() and p.suffix.lower() in {".ttf", ".otf", ".woff", ".woff2"}
        for p in FONTS_DIR.rglob("*")
    )


def find_render_font_file() -> Path | None:
    if not FONTS_DIR.exists():
        return None

    preferred_names = [
        "Bernier-Regular.ttf", "Bernier-Regular.otf",
        "Bernier.ttf", "Bernier.otf",
        "BERNIER™ Regular.ttf", "BERNIER#U2122 Regular.ttf",
    ]

    all_fonts = sorted(
        [f for f in FONTS_DIR.rglob("*") if f.is_file() and f.suffix.lower() in {".ttf", ".otf"}],
        key=lambda p: (len(p.parts), p.name.lower()),
    )

    for name in preferred_names:
        for font in all_fonts:
            if font.name == name:
                return font

    return next((f for f in all_fonts if "bernier" in f.name.lower()), all_fonts[0] if all_fonts else None)


def load_pillow_font(font_family: str, font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_file := find_render_font_file():
        try: return ImageFont.truetype(str(font_file), font_size)
        except Exception: pass

    for cand in [font_family, "Arial", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/calibri.ttf"]:
        try: return ImageFont.truetype(str(cand), font_size)
        except Exception: continue
    return ImageFont.load_default()


def text_bbox_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, stroke_width: int = 0, letter_spacing: float = 0.0) -> tuple[int, int]:
    if not (text := str(text or "")): return 0, 0
    if abs(float(letter_spacing or 0.0)) < 0.01 or len(text) <= 1:
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        return max(1, bbox[2] - bbox[0]), max(1, bbox[3] - bbox[1])

    total_w = sum(max(1, draw.textbbox((0, 0), ch, font=font, stroke_width=stroke_width)[2] - draw.textbbox((0, 0), ch, font=font, stroke_width=stroke_width)[0]) for ch in text)
    total_w += int(round(float(letter_spacing))) * (len(text) - 1)
    max_h = max(max(1, draw.textbbox((0, 0), ch, font=font, stroke_width=stroke_width)[3] - draw.textbbox((0, 0), ch, font=font, stroke_width=stroke_width)[1]) for ch in text)
    return max(1, int(round(total_w))), max_h


def measure_multiline(draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.ImageFont, stroke_width: int, letter_spacing: float = 0.0) -> tuple[int, int, list[tuple[int, int]]]:
    sizes = [text_bbox_size(draw, l, font, stroke_width, letter_spacing) for l in lines]
    w = max((s[0] for s in sizes), default=0)
    h = sum(s[1] for s in sizes) + (int(max(4, getattr(font, "size", 40) * 0.25)) * (len(lines) - 1) if len(lines) > 1 else 0)
    return w, h, sizes


def draw_text_with_letter_spacing(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, font: ImageFont.ImageFont, fill: tuple[int, int, int, int], stroke_width: int, stroke_fill: tuple[int, int, int, int], letter_spacing: float = 0.0) -> None:
    if abs(float(letter_spacing or 0.0)) < 0.01 or len(text) <= 1:
        draw.text(xy, text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        return

    x, y = xy
    for char in text:
        draw.text((int(round(x)), y), char, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        x += text_bbox_size(draw, char, font, stroke_width, 0)[0] + float(letter_spacing)


def opacity_to_alpha(value: Any) -> int:
    try: op = float(value)
    except Exception: op = 100.0
    if op <= 1.0: op *= 100.0
    return int(round(255 * (max(0.0, min(100.0, op)) / 100.0)))


def wrap_text_for_render(text: str, font: ImageFont.ImageFont, max_width: int, letter_spacing: float = 0.0) -> list[str]:
    if not (text := re.sub(r"\s+", " ", str(text or "").strip())): return []
    draw = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    lines, current = [], ""

    for word in text.split():
        test = f"{current} {word}".strip()
        if text_bbox_size(draw, test, font, letter_spacing=letter_spacing)[0] <= max_width or not current:
            current = test
        else:
            lines.append(current); current = word

    if current: lines.append(current)
    return lines[:4]


def draw_lyric_clip_on_image(image: Image.Image, clip: dict[str, Any], width: int, height: int) -> bool:
    if not (text := str(clip.get("text", "")).strip()) or clip.get("visible") is False:
        return False

    font_size = int(round(float(clip.get("fontSize", DEFAULT_LYRIC_FONT_SIZE))))
    font = load_pillow_font(str(clip.get("fontFamily", DEFAULT_LYRIC_FONT)), font_size)

    alpha = opacity_to_alpha(clip.get("opacity", 100))
    color = hex_to_rgba(str(clip.get("color", DEFAULT_LYRIC_COLOR)), alpha)
    stroke_color = hex_to_rgba(str(clip.get("strokeColor", DEFAULT_LYRIC_STROKE_COLOR)), alpha)
    stroke_w = max(0, int(round(float(clip.get("strokeWidth", DEFAULT_LYRIC_STROKE_WIDTH) or 0))))
    spacing = float(clip.get("letterSpacing", 0) or 0)

    max_w = int(width * 0.86)
    if not (lines := wrap_text_for_render(text, font, max_w, letter_spacing=spacing)):
        return False

    draw = ImageDraw.Draw(image)
    _, total_h, sizes = measure_multiline(draw, lines, font, stroke_w, letter_spacing=spacing)
    line_gap = int(max(4, font_size * 0.25))

    align = str(clip.get("align", "center")).lower()
    xc, yc = float(clip.get("x", width / 2)), float(clip.get("y", height / 2))
    y = int(round(yc - total_h / 2))

    for line, (lw, lh) in zip(lines, sizes):
        x = int(round(xc - max_w / 2 if align == "left" else xc + max_w / 2 - lw if align == "right" else xc - lw / 2))
        draw_text_with_letter_spacing(draw, (x, y), line, font=font, fill=color, stroke_width=stroke_w, stroke_fill=stroke_color, letter_spacing=spacing)
        y += lh + line_gap
    return True


def track_enabled(project, track_id):
    track=get_track(project,track_id)
    return bool(track and track.get("visible") is not False and not track.get("muted")
                and (not any(t.get("solo") for t in project.get("tracks",[])) or track.get("solo")))


def normalized_lyric_clips(project: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    if not track_enabled(project, "lyrics"): return []
    clips = []
    for clip in (get_track(project, "lyrics") or {}).get("clips", []):
        if clip.get("visible") is False or not str(clip.get("text", "")).strip():
            continue
        start = max(0.0, float(clip.get("start", 0)))
        if start >= duration: continue
        
        end = float(clip.get("end", start + 2))
        end = min(float(duration), max(start + 0.05, start + 0.35 if end <= start else end))
        clips.append({**clip, "start": start, "end": end})

    return sorted(clips, key=lambda item: float(item["start"]))




def normalized_audio_clips(project_dir: Path, project: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    """Return timeline audio clips with source offsets.

    start/end are timeline seconds.
    sourceStart/sourceEnd are seconds inside the source audio file.
    """
    assets = project.get("assets") or {}
    default_src = assets.get("audio")
    if not track_enabled(project, "audio"): return []
    clips: list[dict[str, Any]] = []

    for clip in (get_track(project, "audio") or {}).get("clips", []):
        if clip.get("visible") is False:
            continue

        src = str(clip.get("src") or default_src or "").replace("\\", "/").strip()
        if not src:
            continue

        start = max(0.0, float(clip.get("start", 0) or 0))
        end = float(clip.get("end", start) or start)
        if end <= start:
            continue

        start = min(start, duration)
        end = min(max(start + 0.01, end), duration)
        if end <= start:
            continue

        source_start = max(0.0, float(clip.get("sourceStart", clip.get("source_start", 0.0)) or 0.0))
        source_end_raw = clip.get("sourceEnd", clip.get("source_end"))
        if source_end_raw is None:
            source_end = source_start + (end - start)
        else:
            source_end = max(source_start + 0.01, float(source_end_raw or 0.0))

        # Do not let the requested source segment exceed the source file duration when ffprobe can read it.
        try:
            source_duration = ffprobe_duration_seconds(safe_child(project_dir, src))
            if source_duration:
                source_start = min(source_start, max(0.0, source_duration - 0.01))
                source_end = min(source_end, source_duration)
        except Exception:
            pass

        clip_duration = min(end - start, source_end - source_start)
        if clip_duration <= 0.01:
            continue

        clips.append({
            **clip,
            "src": src,
            "start": round(start, 3),
            "end": round(start + clip_duration, 3),
            "sourceStart": round(source_start, 3),
            "sourceEnd": round(source_start + clip_duration, 3),
            "volume": float(clip.get("volume", 1.0) if clip.get("volume", 1.0) is not None else 1.0),
        })

    return sorted(clips, key=lambda item: (float(item["start"]), str(item.get("id", ""))))


def build_audio_timeline_file(project_dir: Path, project: dict[str, Any], temp_dir: Path, ffmpeg: str, duration: float) -> dict[str, Any]:
    """Render edited audio clips into one audio file used by final export.

    This is what makes split/delete/move audio clips real in the final MP4.
    """
    audio_clips = normalized_audio_clips(project_dir, project, duration)
    output_path = temp_dir / "editor_audio_timeline.m4a"

    # If there are no enabled audio clips, generate a silent audio bed so video still renders.
    if not audio_clips:
        cmd = [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", f"{duration:.3f}",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ]
        if (res := subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True)).returncode != 0:
            raise HTTPException(status_code=500, detail={"message": "FFmpeg silent audio build failed", "stderr": res.stderr[-4000:]})
        return {"path": output_path, "clipCount": 0, "renderMode": "silent_audio_timeline"}

    input_paths: list[Path] = []
    input_index_by_src: dict[str, int] = {}
    for clip in audio_clips:
        src = str(clip["src"])
        if src not in input_index_by_src:
            path = safe_child(project_dir, src)
            if not path.exists():
                raise HTTPException(status_code=404, detail=f"Audio clip source missing: {src}")
            input_index_by_src[src] = len(input_paths)
            input_paths.append(path)

    cmd = [ffmpeg, "-y"]
    for path in input_paths:
        cmd.extend(["-i", str(path)])

    filter_parts: list[str] = []
    concat_labels: list[str] = []
    cursor = 0.0
    seg_index = 0

    def add_silence(seconds: float) -> None:
        nonlocal seg_index
        seconds = float(seconds)
        if seconds <= 0.005:
            return
        label = f"s{seg_index}"
        filter_parts.append(
            f"anullsrc=channel_layout=stereo:sample_rate=44100,"
            f"atrim=duration={seconds:.6f},asetpts=PTS-STARTPTS[{label}]"
        )
        concat_labels.append(f"[{label}]")
        seg_index += 1

    for clip in audio_clips:
        start = max(0.0, float(clip["start"]))
        end = min(duration, float(clip["end"]))
        if end <= start:
            continue

        if start > cursor:
            add_silence(start - cursor)

        # No overlapping mix yet: if clips overlap, trim the later one to begin at cursor.
        effective_start = max(start, cursor)
        if effective_start >= end:
            continue

        source_start = float(clip["sourceStart"]) + (effective_start - start)
        source_end = source_start + (end - effective_start)
        volume = max(0.0, float(clip.get("volume", 1.0)))
        input_idx = input_index_by_src[str(clip["src"])]
        label = f"a{seg_index}"

        filter_parts.append(
            f"[{input_idx}:a]"
            f"atrim=start={source_start:.6f}:end={source_end:.6f},"
            f"asetpts=PTS-STARTPTS,"
            f"aresample=44100,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={volume:.6f}"
            f"[{label}]"
        )
        concat_labels.append(f"[{label}]")
        seg_index += 1
        cursor = end

    if cursor < duration:
        add_silence(duration - cursor)

    if not concat_labels:
        filter_parts.append(
            f"anullsrc=channel_layout=stereo:sample_rate=44100,"
            f"atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[silent]"
        )
        concat_labels.append("[silent]")

    filter_parts.append("".join(concat_labels) + f"concat=n={len(concat_labels)}:v=0:a=1[aout]")
    filter_complex = ";".join(filter_parts)

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path),
    ])

    if (res := subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True)).returncode != 0:
        raise HTTPException(status_code=500, detail={"message": "FFmpeg edited audio timeline build failed", "stderr": res.stderr[-4000:]})

    return {
        "path": output_path,
        "clipCount": len(audio_clips),
        "renderMode": "edited_audio_timeline",
    }


def render_timed_lyrics_overlay_video(project: dict[str, Any], temp_dir: Path, width: int, height: int, fps: int, duration: float, ffmpeg: str) -> dict[str, Any]:
    segments_dir = temp_dir / "lyric_segments"
    if segments_dir.exists(): shutil.rmtree(segments_dir)
    segments_dir.mkdir(parents=True, exist_ok=True)

    clips = normalized_lyric_clips(project, duration)
    boundaries = {0.0, float(duration)}
    for c in clips: boundaries.update([round(c["start"], 3), round(c["end"], 3)])

    points = sorted(v for v in boundaries if 0.0 <= v <= duration)
    if len(points) < 2: points = [0.0, float(duration)]

    concat_lines, seg_count, last_name = [], 0, None

    for left, right in zip(points, points[1:]):
        if (seg_dur := float(right) - float(left)) < 0.01: continue
        mid = left + seg_dur / 2.0
        active = [c for c in clips if c["start"] <= mid < c["end"]]

        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        for c in active: draw_lyric_clip_on_image(canvas, c, width, height)

        seg_count += 1
        name = f"segment_{seg_count:04d}.png"
        canvas.save(segments_dir / name)
        concat_lines.extend([f"file '{name}'", f"duration {seg_dur:.6f}"])
        last_name = name

    if last_name: concat_lines.append(f"file '{last_name}'")
    (concat_path := segments_dir / "overlay_concat.txt").write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-vf", f"fps={fps},format=argb", "-c:v", "qtrle", "-pix_fmt", "argb", str(overlay_video := temp_dir / "lyrics_overlay_alpha.mov")]
    if (res := subprocess.run(cmd, cwd=str(segments_dir), capture_output=True, text=True)).returncode != 0:
        raise HTTPException(status_code=500, detail={"message": "FFmpeg lyric overlay-video build failed", "stderr": res.stderr[-4000:]})

    return {"path": overlay_video, "clipCount": len(clips), "segmentCount": seg_count}


def escape_ass_text(text: str) -> str:
    return str(text or "").replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def build_ass(project: dict[str, Any], output_path: Path) -> None:
    width, height = int(project.get("width") or VIDEO_WIDTH), int(project.get("height") or VIDEO_HEIGHT)
    clips = sorted((get_track(project, "lyrics") or {}).get("clips", []), key=lambda c: float(c.get("start", 0)))

    header = f"""[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,{DEFAULT_LYRIC_FONT},{DEFAULT_LYRIC_FONT_SIZE},&H00000000,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""

    events = []
    for c in clips:
        if c.get("visible") is False or not (text := escape_ass_text(str(c.get("text", "")).strip())): continue
        start, end = float(c.get("start", 0)), float(c.get("end", float(c.get("start", 0)) + 2))
        override = rf"{{\fn{str(c.get('fontFamily', DEFAULT_LYRIC_FONT)).replace(',', '')}\fs{int(round(float(c.get('fontSize', DEFAULT_LYRIC_FONT_SIZE))))}\c{hex_to_ass_color(str(c.get('color', DEFAULT_LYRIC_COLOR)))}\3c{hex_to_ass_color(str(c.get('strokeColor', DEFAULT_LYRIC_STROKE_COLOR)))}\bord{float(c.get('strokeWidth', DEFAULT_LYRIC_STROKE_WIDTH))}\shad0\an5\pos({int(round(float(c.get('x', width/2))))},{int(round(float(c.get('y', height/2))))})}}"
        events.append(f"Dialogue: 0,{seconds_to_ass_time(start)},{seconds_to_ass_time(max(start+0.35, end))},Default,,0,0,0,,{override}{text}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")


def run_ffmpeg_render(project_dir: Path, project: dict[str, Any], skip_repair: bool = False) -> dict[str, Any]:
    if not skip_repair:
        project, repaired = repair_editor_project_assets(project_dir, project)
        if repaired: save_project_bundle(project_dir, project)

    if not (ffmpeg := shutil.which("ffmpeg")): raise HTTPException(status_code=500, detail="ffmpeg not in PATH")

    assets = project.get("assets", {})
    if not (bg_rel := assets.get("background")): raise HTTPException(status_code=400, detail="No background asset")
    if not (audio_rel := assets.get("audio")): raise HTTPException(status_code=400, detail="No audio asset")

    if not (bg_path := safe_child(project_dir, bg_rel)).exists(): raise HTTPException(status_code=404, detail="Background missing")
    if not (audio_path := safe_child(project_dir, audio_rel)).exists(): raise HTTPException(status_code=404, detail="Audio missing")

    (render_dir := project_dir / "renders").mkdir(parents=True, exist_ok=True)
    (temp_dir := project_dir / "editor_render_temp").mkdir(parents=True, exist_ok=True)

    build_ass(project, ass_path := temp_dir / "editor_lyrics.ass")
    duration = float(project.get("duration") or ffprobe_duration_seconds(audio_path) or 180.0)
    width, height, fps = int(project.get("width") or VIDEO_WIDTH), int(project.get("height") or VIDEO_HEIGHT), int(project.get("fps") or FPS)

    overlay = render_timed_lyrics_overlay_video(project, temp_dir, width, height, fps, duration, ffmpeg)
    audio_timeline = build_audio_timeline_file(project_dir, project, temp_dir, ffmpeg, duration)

    filter_complex = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,format=rgba[bg];[1:v]format=rgba[lyrics];[bg][lyrics]overlay=0:0:format=auto,format=yuv420p[vout]"
    background_input = ["-loop","1","-framerate",str(fps),"-i",str(bg_path)] if track_enabled(project,"background") else ["-f","lavfi","-i",f"color=c=white:s={width}x{height}:r={fps}"]
    cmd = [ffmpeg, "-y", *background_input, "-i", str(overlay["path"]), "-i", str(audio_timeline["path"]), "-t", f"{duration:.3f}", "-filter_complex", filter_complex, "-map", "[vout]", "-map", "2:a:0", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", str(output_path := render_dir / "final_lyrics_video.mp4")]

    if (res := subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True)).returncode != 0:
        raise HTTPException(status_code=500, detail={"message": "FFmpeg final render failed", "stderr": res.stderr[-4000:]})

    return {
        "ok": True, "output": rel_to_project(project_dir, output_path), "absoluteOutput": str(output_path),
        "ass": rel_to_project(project_dir, ass_path), "fontFileUsed": str(f) if (f := find_render_font_file()) else None,
        "overlayVideo": rel_to_project(project_dir, overlay["path"]), "overlayClipCount": overlay["clipCount"],
        "overlaySegmentCount": overlay["segmentCount"],
        "audioTimeline": rel_to_project(project_dir, audio_timeline["path"]),
        "audioClipCount": audio_timeline["clipCount"],
        "renderMode": "pillow_timed_alpha_overlay_video_plus_edited_audio_timeline",
    }


def merge_lyrics_from_sync(project_dir: Path, project: dict[str, Any], keep_style: bool = True) -> dict[str, Any]:
    if not (lines := detect_lyrics(project_dir)): raise HTTPException(status_code=404, detail="No synced lyrics found")

    existing = (get_track(project, "lyrics") or {}).get("clips", [])
    base_style = {k: existing[0][k] for k in ["fontFamily", "fontSize", "color", "strokeColor", "strokeWidth", "align", "opacity", "letterSpacing", "x", "y"] if k in existing[0]} if keep_style and existing else {}
    
    w, h = int(project.get("width") or VIDEO_WIDTH), int(project.get("height") or VIDEO_HEIGHT)
    new_clips = [_create_lyric_clip(line, w, h, base_style) for line in lines]

    tracks, found = [], False
    for track in project.get("tracks", []):
        if track.get("id") == "lyrics": track["clips"] = new_clips; found = True
        tracks.append(track)

    if not found: tracks.insert(1, {"id": "lyrics", "name": "Lyrics", "type": "text", "clips": new_clips})
    project["tracks"] = tracks
    project["styleDefaultsAppliedVersion"] = LYRIC_DEFAULTS_VERSION
    write_json(project_dir / EDITOR_FILENAME, project)
    return project


def patch_clip_in_project(project: dict[str, Any], clip_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    found, safe_patch = False, {k: v for k, v in (patch or {}).items() if k != "id"}
    for track in project.get("tracks", []):
        for clip in track.get("clips", []):
            if clip.get("id") == clip_id:
                clip.update(safe_patch); found = True
    if not found: raise HTTPException(status_code=404, detail=f"Clip not found: {clip_id}")
    return project


def render_job_worker(job_id: str, project_id: str, project: dict[str, Any]) -> None:
    try:
        set_render_job(job_id, status="running", progress=5, message="Preparing render")
        project_dir = safe_project_dir(project_id)

        set_render_job(job_id, progress=20, message="Rendering lyric overlay")
        result = run_ffmpeg_render(project_dir, project, skip_repair=True)

        set_render_job(job_id, progress=92, message="Starting TubeHarbor upload")

        upload_info = None
        upload_error = None

        try:
            # Rendering alone is never authorization to publish.
            upload_info = {'ok':True,'skipped':True,'reason':'Upload requires an explicit upload action'}
        except Exception as upload_exc:
            upload_error = str(upload_exc)

        result["autoUpload"] = upload_info
        result["autoUploadError"] = upload_error

        if upload_error:
            set_render_job(
                job_id,
                status="completed",
                progress=100,
                message="Render complete, TubeHarbor upload failed to start",
                result=result,
            )
        else:
            set_render_job(
                job_id,
                status="completed",
                progress=100,
                message="Render complete, TubeHarbor upload started",
                result=result,
            )

    except Exception as exc:
        set_render_job(
            job_id,
            status="failed",
            progress=100,
            message="Render failed",
            error=getattr(exc, "detail", str(exc)),
        )

def create_upload_schedule(project_dir: Path, request: ScheduleUploadRequest) -> dict[str, Any]:
    from echoforge.stages.tubeharbor.youtube_uploader import privacy, upload_to_youtube
    options={'visibility':request.privacy,'scheduleAt':request.publish_at}
    privacy(options)
    video=asset_path(project_dir,request.video_path or 'renders/final_lyrics_video.mp4',EF_ROOT)
    payload={'ok':True,'projectId':project_dir.name,'privacy':request.privacy,'publish_at':request.publish_at,
             'video_path':str(video),'start_upload':request.start_upload,'created_at':time.time()}
    write_json(project_dir/'upload/upload_schedule.json',payload)
    if request.start_upload: payload['upload']=upload_to_youtube(video,project_dir,options)
    return payload



# =====================================================================
# ROUTES
# =====================================================================

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "efRoot": str(EF_ROOT), "projectsRoot": str(PROJECTS_ROOT), "ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe")), "hasProjectFonts": has_project_fonts()}


@app.get("/api/projects")
def list_projects() -> dict[str, Any]:
    ensure_projects_root()
    return {
        "ok": True, "projectsRoot": str(PROJECTS_ROOT),
        "projects": [{
            "id": p.name, "path": str(p), "hasEditorProject": (p / EDITOR_FILENAME).exists(),
            "hasBackground": bool((a := detect_assets(p)).get("background")), "hasAudio": bool(a.get("audio")),
            "hasLyrics": bool(detect_lyrics(p)), "modified": p.stat().st_mtime
        } for p in sorted([x for x in PROJECTS_ROOT.iterdir() if x.is_dir()], reverse=True)]
    }


@app.post("/api/projects/{project_id}/bootstrap")
def bootstrap_project(project_id: str, force: bool = Query(False)) -> dict[str, Any]:
    return {"ok": True, "project": load_or_bootstrap(safe_project_dir(project_id), force=force)}


@app.get("/api/projects/{project_id}/editor")
def get_editor_project(project_id: str) -> dict[str, Any]:
    return {"ok": True, "project": load_or_bootstrap(safe_project_dir(project_id), force=False)}


@app.post("/api/projects/{project_id}/editor")
def save_editor_project(project_id: str, request: SaveProjectRequest) -> dict[str, Any]:
    project_dir = safe_project_dir(project_id)
    payload = {**request.project, "projectId": project_id}
    save_project_bundle(project_dir, payload)
    return {"ok": True, "path": str(project_dir / EDITOR_FILENAME), "project": payload}


@app.post("/api/projects/{project_id}/render")
def render_project(project_id: str, request: SaveProjectRequest | None = None) -> dict[str, Any]:
    project_dir = safe_project_dir(project_id)
    if request and request.project:
        project = {**request.project, "projectId": project_id}
        save_project_bundle(project_dir, project)
        return run_ffmpeg_render(project_dir, project, skip_repair=False)
    return run_ffmpeg_render(project_dir, load_or_bootstrap(project_dir, force=False), skip_repair=True)


@app.patch("/api/projects/{project_id}/clips/{clip_id}")
def patch_editor_clip(project_id: str, clip_id: str, request: UpdateClipRequest) -> dict[str, Any]:
    project_dir = safe_project_dir(project_id)
    project = patch_clip_in_project(load_or_bootstrap(project_dir), clip_id, request.patch)
    validate_legacy(project_dir,project)
    write_json(project_dir / EDITOR_FILENAME, project)
    return {"ok": True, "project": project, "clipId": clip_id}


@app.post("/api/projects/{project_id}/reload-lyrics")
def reload_project_lyrics(project_id: str, request: ReloadLyricsRequest | None = None) -> dict[str, Any]:
    project_dir = safe_project_dir(project_id)
    project = merge_lyrics_from_sync(project_dir, load_or_bootstrap(project_dir), keep_style=(request.keep_style if request else True))
    return {"ok": True, "project": project, "lineCount": len((get_track(project, "lyrics") or {}).get("clips", []))}


@app.post("/api/projects/{project_id}/render/start")
def start_render_project(project_id: str, request: SaveProjectRequest | None = None) -> dict[str, Any]:
    project_dir = safe_project_dir(project_id)
    
    # Use requested project, or load existing
    project = request.project if request and request.project else load_or_bootstrap(project_dir, force=False)
    project["projectId"] = project_id
    
    # Synchronously save the project state before handing off to the worker thread
    save_project_bundle(project_dir, project)
    
    job_id = uuid.uuid4().hex
    set_render_job(job_id, id=job_id, projectId=project_id, status="queued", progress=0, message="Queued")
    RENDER_EXECUTOR.submit(render_job_worker, job_id, project_id, project)
    return {"ok": True, "jobId": job_id}


@app.get("/api/render-jobs/{job_id}")
def get_render_status(job_id: str) -> dict[str, Any]:
    if not (job := get_render_job(job_id)): raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job": job}


@app.get("/api/render-jobs/{job_id}/events")
def stream_render_status(job_id: str) -> StreamingResponse:
    def event_stream():
        while True:
            if not (job := get_render_job(job_id)):
                yield 'event: error\ndata: {"error":"Render job not found"}\n\n'; return
            yield f"data: {json.dumps(job, ensure_ascii=False)}\n\n"
            if job.get("status") in {"completed", "failed"}: return
            time.sleep(1.0)
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/projects/{project_id}/upload/schedule")
def schedule_project_upload(project_id: str, request: ScheduleUploadRequest) -> dict[str, Any]:
    return {"ok": True, "schedule": create_upload_schedule(safe_project_dir(project_id), request)}


@app.get("/api/projects/{project_id}/media")
def get_media(project_id: str, path: str, request: Request):
    target = asset_path(safe_project_dir(project_id), path, EF_ROOT)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if target.suffix.lower() not in ALLOWED_MEDIA_SUFFIXES:
        raise HTTPException(status_code=400, detail="Forbidden file type")

    file_size = target.stat().st_size
    content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    range_header = request.headers.get("range")

    if not range_header:
        return FileResponse(str(target), media_type=content_type, headers={"Accept-Ranges": "bytes"})

    # Browser audio/video seeking needs HTTP Range support.
    try:
        units, rng = range_header.split("=", 1)
        if units.strip().lower() != "bytes":
            raise ValueError("Only bytes range supported")
        start_s, end_s = (rng.split("-", 1) + [""])[:2]
        start = int(start_s) if start_s.strip() else 0
        end = int(end_s) if end_s.strip() else file_size - 1
        start = max(0, min(start, file_size - 1))
        end = max(start, min(end, file_size - 1))
    except Exception:
        start, end = 0, file_size - 1

    length = end - start + 1

    def iter_file():
        with target.open("rb") as f:
            f.seek(start)
            remaining = length
            chunk_size = 1024 * 1024
            while remaining > 0:
                chunk = f.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Type": content_type,
    }
    return StreamingResponse(iter_file(), status_code=206, headers=headers)


@app.get("/api/projects/{project_id}/download")
def download_file(project_id: str, path: str) -> FileResponse:
    target = asset_path(safe_project_dir(project_id), path, EF_ROOT)
    if not target.is_file(): raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(target), filename=target.name)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=False)