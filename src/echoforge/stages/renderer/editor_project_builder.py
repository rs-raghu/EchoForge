from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")


@dataclass(frozen=True)
class LrcLine:
    start: float
    text: str


def _root_dir() -> Path:
    # root/src/echoforge/stages/renderer/editor_project_builder.py -> root
    return Path(__file__).resolve().parents[4]


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists(): return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path, data):
    from echoforge.core.storage import atomic_json
    atomic_json(path, data)


def parse_lrc_timestamp(minutes: str, seconds: str, frac: str | None) -> float:
    value = int(minutes) * 60 + int(seconds)
    if frac:
        if len(frac) == 1:
            value += int(frac) / 10
        elif len(frac) == 2:
            value += int(frac) / 100
        else:
            value += int(frac[:3]) / 1000
    return round(value, 3)


def parse_lrc(lrc_path: Path) -> list[LrcLine]:
    from echoforge.stages.verselock.lrc_parser import parse_lrc_file
    return [LrcLine(line.start_seconds,line.text) for line in parse_lrc_file(lrc_path)]


def ffprobe_duration(path: Path) -> float | None:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return None
        value = float((proc.stdout or "").strip())
        if value > 0:
            return round(value, 3)
    except Exception:
        return None
    return None


def find_audio(project_dir: Path) -> Path | None:
    audio_dir = project_dir / "audio"
    for name in ["source_audio.m4a", "source_audio.mp3", "source_audio.wav", "source_audio.webm", "source_audio.mp4"]:
        p = audio_dir / name
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def find_background(project_dir: Path) -> Path | None:
    images_dir = project_dir / "images"
    for name in ["video_background.jpg", "video_background.png", "background_source.jpg", "background_source.png"]:
        p = images_dir / name
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def find_optional_asset(project_dir: Path, names: list[str]) -> Path | None:
    locations = [project_dir / "images", project_dir / "renders", project_dir / "audio", project_dir]
    for loc in locations:
        for name in names:
            p = loc / name
            if p.exists() and p.stat().st_size > 0:
                return p
    return None


def build_clips(lines: list[LrcLine], audio_duration: float | None) -> list[dict[str, Any]]:
    if not lines:
        return []

    gaps: list[float] = []
    for i in range(len(lines) - 1):
        gap = lines[i + 1].start - lines[i].start
        if 0.35 <= gap <= 8.0:
            gaps.append(gap)

    default_duration = median(gaps) if gaps else 2.8
    default_duration = max(1.2, min(float(default_duration), 4.2))

    clips: list[dict[str, Any]] = []
    for idx, line in enumerate(lines):
        start = round(line.start, 3)
        if idx + 1 < len(lines):
            end = max(start + 0.35, lines[idx + 1].start - 0.04)
        elif audio_duration:
            end = min(audio_duration, start + default_duration)
        else:
            end = start + default_duration

        clips.append(
            {
                "id": f"lyric_{idx + 1:04d}",
                "type": "lyric",
                "track": "lyrics",
                "text": line.text,
                "start": start,
                "end": round(end, 3),
                "duration": round(max(0.0, end - start), 3),
                "locked": False,
                "visible": True,
                "style": {
                    "font_family": "Bernier",
                    "font_size": 50,
                    "fill": "#000000",
                    "stroke": None,
                    "stroke_width": 0,
                    "align": "center",
                    "x": 960,
                    "y": 540,
                    "anchor": "center",
                    "max_width": 1320,
                    "line_height": 1.05,
                },
            }
        )
    return clips


def project_title(project_dir: Path) -> tuple[str, str | None, str | None]:
    state = _read_json(project_dir / "project_state.json")
    manifest = _read_json(project_dir / "asset_manifest.json")
    review = _read_json(project_dir / "metadata_review.json")

    title = (
        state.get("song_title")
        or state.get("title")
        or state.get("display_title")
        or review.get("display_title")
        or manifest.get("song_title")
        or manifest.get("title")
    )
    artist = (
        state.get("artist_text")
        or state.get("artist")
        or state.get("display_artist")
        or review.get("display_artist")
        or manifest.get("artist_text")
        or manifest.get("artist")
    )
    label = project_dir.name
    if title and artist:
        label = f"{title} — {artist}"
    elif title:
        label = str(title)
    return label, str(title) if title else None, str(artist) if artist else None


def _json_for_html(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def write_preview_html(
    path: Path,
    *,
    title: str,
    audio_src: str,
    background_src: str,
    font_src: str | None,
    clips: list[dict[str, Any]],
) -> None:
    font_face = ""
    if font_src:
        font_face = f'''
  @font-face {{
    font-family: 'Bernier';
    src: url('{font_src}') format('truetype');
    font-weight: normal;
    font-style: normal;
  }}
'''
    html = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>EchoForge Editor Preview</title>
<style>
{font_face}
  html, body {{
    margin: 0;
    width: 100%;
    height: 100%;
    background: #101010;
    color: #f5f5f5;
    font-family: Arial, sans-serif;
    overflow: hidden;
  }}
  #stageWrap {{
    width: 100vw;
    height: calc(100vh - 92px);
    display: grid;
    place-items: center;
    background: #080808;
  }}
  #stage {{
    position: relative;
    aspect-ratio: 16 / 9;
    width: min(100vw, calc((100vh - 92px) * 16 / 9));
    height: auto;
    background-image: url({_json_for_html(background_src)});
    background-size: cover;
    background-position: center;
    overflow: hidden;
  }}
  #lyric {{
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: 70%;
    min-height: 80px;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    color: #000000;
    font-family: 'Bernier', Impact, 'Arial Black', sans-serif;
    font-size: clamp(30px, 4.2vw, 64px);
    line-height: 1.05;
    white-space: pre-wrap;
    user-select: none;
    pointer-events: none;
  }}
  #controls {{
    box-sizing: border-box;
    height: 118px;
    padding: 10px 16px;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 16px;
    align-items: center;
    background: #181818;
    border-top: 1px solid #333;
  }}
  #leftControls {{
    display: grid;
    gap: 8px;
  }}
  #buttons {{
    display: flex;
    gap: 8px;
    align-items: center;
  }}
  button {{
    background: #2b2b2b;
    color: #fff;
    border: 1px solid #555;
    border-radius: 8px;
    padding: 7px 12px;
    cursor: pointer;
  }}
  button:hover {{ background: #3a3a3a; }}
  #seek {{ width: 100%; }}
  audio {{ width: 100%; }}
  #info {{
    font-size: 12px;
    line-height: 1.45;
    color: #bbb;
    min-width: 230px;
    text-align: right;
  }}
  #time {{ color: #fff; font-weight: 700; }}
  #title {{ color: #fff; font-weight: 700; }}
</style>
</head>
<body>
<div id="stageWrap">
  <div id="stage"><div id="lyric">Press play</div></div>
</div>
<div id="controls">
  <div id="leftControls">
    <div id="buttons">
      <button id="playBtn" type="button">Play/Pause</button>
      <button id="backBtn" type="button">−5s</button>
      <button id="fwdBtn" type="button">+5s</button>
    </div>
    <input id="seek" type="range" min="0" max="1000" value="0" step="1" />
    <audio id="audio" controls src={_json_for_html(audio_src)}></audio>
  </div>
  <div id="info">
    <div id="title"></div>
    <div><span id="time">0.00</span>s</div>
    <div id="clipCount"></div>
    <div id="fontStatus">Font: checking…</div>
    <div>Space = play/pause · ←/→ = seek · buttons also work</div>
  </div>
</div>
<script>
const clips = {_json_for_html(clips)};
const projectTitle = {_json_for_html(title)};
const audio = document.getElementById('audio');
const lyric = document.getElementById('lyric');
const timeBox = document.getElementById('time');
const seekBar = document.getElementById('seek');
const playBtn = document.getElementById('playBtn');
const backBtn = document.getElementById('backBtn');
const fwdBtn = document.getElementById('fwdBtn');
const fontStatus = document.getElementById('fontStatus');
document.getElementById('title').textContent = projectTitle;
document.getElementById('clipCount').textContent = clips.length + ' lyric clips';
if (document.fonts && fontStatus) {{
  document.fonts.load('50px Bernier').then((fonts) => {{
    fontStatus.textContent = fonts.length ? 'Font: Bernier loaded' : 'Font: Bernier not loaded';
  }}).catch(() => {{ fontStatus.textContent = 'Font: Bernier failed'; }});
}}
function activeClip(t) {{
  let lo = 0, hi = clips.length - 1;
  while (lo <= hi) {{
    const mid = Math.floor((lo + hi) / 2);
    const c = clips[mid];
    if (t < c.start) hi = mid - 1;
    else if (t >= c.end) lo = mid + 1;
    else return c;
  }}
  return null;
}}
function clampTime(value) {{
  const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
  if (!duration) return Math.max(0, value);
  return Math.min(duration, Math.max(0, value));
}}
function seekBy(delta) {{
  audio.currentTime = clampTime((audio.currentTime || 0) + delta);
}}
function togglePlay() {{
  audio.paused ? audio.play() : audio.pause();
}}
let draggingSeek = false;
seekBar.addEventListener('pointerdown', () => {{ draggingSeek = true; }});
seekBar.addEventListener('pointerup', () => {{ draggingSeek = false; }});
seekBar.addEventListener('input', () => {{
  const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
  if (duration > 0) audio.currentTime = (Number(seekBar.value) / 1000) * duration;
}});
playBtn.addEventListener('click', togglePlay);
backBtn.addEventListener('click', () => seekBy(-5));
fwdBtn.addEventListener('click', () => seekBy(5));
function tick() {{
  const t = audio.currentTime || 0;
  timeBox.textContent = t.toFixed(2);
  const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
  if (!draggingSeek && duration > 0) seekBar.value = String(Math.round((t / duration) * 1000));
  const c = activeClip(t);
  lyric.textContent = c ? c.text : '';
  requestAnimationFrame(tick);
}}
tick();
window.addEventListener('keydown', (ev) => {{
  if (ev.code === 'Space') {{
    ev.preventDefault();
    ev.stopPropagation();
    togglePlay();
    return;
  }}
  if (ev.code === 'ArrowRight') {{
    ev.preventDefault();
    ev.stopPropagation();
    seekBy(5);
    return;
  }}
  if (ev.code === 'ArrowLeft') {{
    ev.preventDefault();
    ev.stopPropagation();
    seekBy(-5);
    return;
  }}
}}, true);
</script>
</body>
</html>
'''
    path.write_text(html, encoding="utf-8", newline="\n")


def prepare_editor_project(project: str | Path, force: bool = False) -> dict[str, Any]:
    root = _root_dir()
    project_dir = Path(project)
    if not project_dir.is_absolute():
        project_dir = root / project_dir
    project_dir = project_dir.resolve()

    sync_dir = project_dir / "sync"
    editor_dir = project_dir / "editor"
    editor_dir.mkdir(parents=True, exist_ok=True)

    final_lrc = sync_dir / "final_synced_lyrics.lrc"
    final_json = sync_dir / "final_synced_lyrics.json"
    audio = find_audio(project_dir)
    background = find_background(project_dir)
    music_thumbnail = find_optional_asset(project_dir, ["music_thumbnail.jpg", "music_thumbnail.png", "thumbnail.jpg"])
    upload_thumbnail = find_optional_asset(project_dir, ["upload_thumbnail.jpg", "upload_thumbnail.png"])

    missing: list[str] = []
    if not project_dir.exists():
        missing.append(str(project_dir))
    if not final_lrc.exists():
        missing.append(_rel(final_lrc, root))
    if not audio:
        missing.append(_rel(project_dir / "audio" / "source_audio.m4a", root))
    if not background:
        missing.append(_rel(project_dir / "images" / "video_background.jpg", root))
    if missing:
        return {
            "ok": False,
            "mode": "prepare_editor_project",
            "reason": "Missing required renderer inputs.",
            "missing": missing,
            "project_dir": _rel(project_dir, root),
        }

    editor_project_path = editor_dir / "editor_project.json"
    timeline_path = editor_dir / "timeline.json"
    preview_path = editor_dir / "preview.html"
    report_path = editor_dir / "prepare_report.json"

    if not force and editor_project_path.exists():
        # An edited V2 timeline need not have Stage 1 preview/timeline artifacts.
        # Preserve it rather than rebuilding over the user's manual work.
        from echoforge.core.storage import read_json
        from echoforge.core.security import validate_editor
        validate_editor(read_json(editor_project_path), project_dir)
        return {
            "ok": True,
            "mode": "prepare_editor_project",
            "reused_existing_outputs": True,
            "editor_project": _rel(editor_project_path, root),
            "timeline": _rel(timeline_path, root),
            "preview_html": _rel(preview_path, root),
            "project_dir": _rel(project_dir, root),
        }

    from echoforge.core.sync_state import validate_sync_pair
    from echoforge.core.storage import file_lock
    with file_lock(sync_dir / "publish.lock"):
        validate_sync_pair(project_dir)
        lines = parse_lrc(final_lrc)
    duration = ffprobe_duration(audio) if audio else None
    clips = build_clips(lines, duration)
    label, song_title, artist = project_title(project_dir)

    assets_dir = root / "assets"
    bernier = assets_dir / "fonts" / "Bernier" / "Bernier-Regular.ttf"
    font_rel_for_preview = "../../../assets/fonts/Bernier/Bernier-Regular.ttf" if bernier.exists() else None

    timeline = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": _rel(final_lrc, project_dir),
        "audio_duration": duration,
        "clip_count": len(clips),
        "tracks": [
            {"id": "background", "type": "image", "locked": True},
            {"id": "audio", "type": "audio", "locked": True},
            {"id": "lyrics", "type": "text", "locked": False},
        ],
        "clips": clips,
    }

    editor_project = {
        "schema_version": 1,
        "stage": "renderer_stage1_editor_project",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_dir": _rel(project_dir, root),
        "title": label,
        "song_title": song_title,
        "artist": artist,
        "canvas": {"width": 1920, "height": 1080, "fps": 30},
        "assets": {
            "audio": _rel(audio, project_dir) if audio else None,
            "background": _rel(background, project_dir) if background else None,
            "music_thumbnail": _rel(music_thumbnail, project_dir) if music_thumbnail else None,
            "upload_thumbnail": _rel(upload_thumbnail, project_dir) if upload_thumbnail else None,
            "final_lrc": _rel(final_lrc, project_dir),
            "final_json": _rel(final_json, project_dir) if final_json.exists() else None,
            "font_bernier": _rel(bernier, root) if bernier.exists() else None,
        },
        "defaults": {
            "lyric_font_family": "Bernier",
            "lyric_font_size": 50,
            "lyric_fill": "#000000",
            "lyric_stroke": None,
            "lyric_position": {"x": 960, "y": 540},
            "lyric_max_width": 1320,
        },
        "timeline": _rel(timeline_path, project_dir),
        "clips": clips,
    }

    _write_json(timeline_path, timeline)
    _write_json(editor_project_path, editor_project)
    write_preview_html(
        preview_path,
        title=label,
        audio_src="../" + _rel(audio, project_dir),
        background_src="../" + _rel(background, project_dir),
        font_src=font_rel_for_preview,
        clips=clips,
    )

    report = {
        "ok": True,
        "mode": "prepare_editor_project",
        "reused_existing_outputs": False,
        "editor_project": _rel(editor_project_path, root),
        "timeline": _rel(timeline_path, root),
        "preview_html": _rel(preview_path, root),
        "clip_count": len(clips),
        "audio_duration": duration,
        "project_dir": _rel(project_dir, root),
        "note": "Open preview.html to verify background + audio + synced lyrics before WebEditor migration.",
    }
    _write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare EchoForge renderer/WebEditor editor_project.json.")
    parser.add_argument("--project", required=True, help="Project directory, relative to EF_CLEAN or absolute.")
    parser.add_argument("--force", action="store_true", help="Regenerate editor files if they already exist.")
    args = parser.parse_args()
    result = prepare_editor_project(args.project, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
