from __future__ import annotations

import json
import math
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from echoforge.paths import ASSETS_DIR, BACKGROUNDS_DIR, FONTS_DIR
from echoforge.songscout import mark_song_status


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_audio_duration(audio_path: Path) -> float:
    """Read exact duration of audio file using ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 180.0


def parse_project_number(project_dir: Path) -> int:
    """Extract project sequence number (e.g. 0001 -> 1)."""
    match = re.match(r"^(\d{4})_", project_dir.name)
    return int(match.group(1)) if match else 1


def build_template_background(
    project_dir: Path,
    title: str,
    artist: str,
    size: tuple[int, int] = (1920, 1080),
) -> Image.Image:
    """
    Generate the official EchoForge video background:
    1. Selects one of the 20 backgrounds based on project number.
    2. Soft grayscale blur + light overlay.
    3. Top-left: Rounded cover art + Title & Artist in Odibee Sans.
    4. Bottom-left: EchoForge logo.
    """
    out_path = project_dir / "images" / "video_background.jpg"
    thumb_path = project_dir / "images" / "thumbnail.jpg"
    logo_path = ASSETS_DIR / "defaults" / "logo.png"

    # 1. Select background from 20 background assets
    bg_files = sorted([p for p in BACKGROUNDS_DIR.glob("*.jpg")])
    project_no = parse_project_number(project_dir)

    if bg_files:
        chosen_bg = bg_files[(project_no - 1) % len(bg_files)]
        raw_bg = Image.open(chosen_bg).convert("RGB")
    else:
        raw_bg = Image.new("RGB", size, (214, 214, 214))

    # Center-crop to 1920x1080
    tw, th = size
    scale = max(tw / raw_bg.width, th / raw_bg.height)
    nw, nh = int(raw_bg.width * scale), int(raw_bg.height * scale)
    raw_bg = raw_bg.resize((nw, nh), Image.Resampling.LANCZOS)
    left, top = (nw - tw) // 2, (nh - th) // 2
    canvas = raw_bg.crop((left, top, left + tw, top + th))

    # Grayscale blur & light overlay
    canvas = ImageOps.grayscale(canvas).convert("RGB").filter(ImageFilter.GaussianBlur(radius=1.1))
    overlay = Image.new("RGBA", canvas.size, (255, 255, 255, 74))
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(overlay)
    canvas = canvas_rgba

    # 2. Top-Left: Rounded Thumbnail + Title & Artist (0.9x scale)
    thumb_size = 63   # 70 * 0.9
    thumb_radius = 4  # 4 * 0.9
    thumb_x, thumb_y = 42, 38
    if thumb_path.exists():
        try:
            with Image.open(thumb_path) as t_img:
                thumb = t_img.convert("RGB").resize((thumb_size, thumb_size), Image.Resampling.LANCZOS)
                mask = Image.new("L", (thumb_size, thumb_size), 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, thumb_size, thumb_size), radius=thumb_radius, fill=255)
                thumb.putalpha(mask)
                canvas.paste(thumb, (thumb_x, thumb_y), thumb)
        except Exception:
            pass

    odibee_font = FONTS_DIR / "Odibee_Sans" / "OdibeeSans-Regular.ttf"
    try:
        font_title = ImageFont.truetype(str(odibee_font), 27)   # 30 * 0.9
        font_artist = ImageFont.truetype(str(odibee_font), 23)  # 25 * 0.9
    except Exception:
        font_title = font_artist = ImageFont.load_default()

    draw = ImageDraw.Draw(canvas)
    text_x = thumb_x + thumb_size + 14  # 119
    draw.text((text_x, 42), title, font=font_title, fill=(0, 0, 0))
    draw.text((text_x, 72), artist, font=font_artist, fill=(18, 18, 18))

    # 3. Bottom-Left: Logo
    if logo_path.exists():
        try:
            with Image.open(logo_path) as l_img:
                logo = l_img.convert("RGBA")
                target_h = 138
                target_w = int(target_h * (logo.width / max(logo.height, 1)))
                logo = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)
                canvas.paste(logo, (15, 1080 - 42 - target_h + 30), logo)
        except Exception:
            pass

    final_bg = canvas.convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final_bg.save(out_path, quality=95)
    return final_bg


def get_bernier_font(size: int = 50) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load Bernier font for lyrics and title intro."""
    for p in [
        FONTS_DIR / "Bernier" / "Bernier-Regular.ttf",
        FONTS_DIR / "Bernier" / "BERNIERRegular-Regular.ttf",
        Path("C:/Windows/Fonts/arial.ttf"),
    ]:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def wrap_text(text: str, font: Any, max_width: int = 1320) -> str:
    """Word-wrap text so it doesn't overflow screen margins."""
    words = text.split()
    if not words:
        return text

    lines = []
    current_line = words[0]

    for word in words[1:]:
        test = current_line + " " + word
        try:
            bbox = font.getbbox(test)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(test) * 20

        if w <= max_width:
            current_line = test
        else:
            lines.append(current_line)
            current_line = word

    lines.append(current_line)
    return "\n".join(lines)


def render_project_video(
    project_dir: Path,
    song_id: str | None = None,
    *,
    fps: int = 24,
    size: tuple[int, int] = (1920, 1080),
) -> Path | None:
    """Render the official template lyrics video with 5s intro card & synchronized lyrics."""
    sync_json_path = project_dir / "sync" / "final_synced_lyrics.json"
    audio_path = project_dir / "audio" / "source_audio.m4a"

    if not sync_json_path.exists() or not audio_path.exists():
        print("[!] Cannot render: Missing synced lyrics or audio.")
        return None

    sync_data = json.loads(sync_json_path.read_text(encoding="utf-8"))
    lyric_lines: list[dict[str, Any]] = sync_data.get("lines", [])

    # Read project metadata
    state_file = project_dir / "project_state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    title = state.get("title")
    artist = state.get("artist")
    if not title:
        raw = re.sub(r"^\d+_", "", project_dir.name)
        parts = raw.split("_")
        title = parts[0].title() if parts else project_dir.name
        artist = parts[1].upper() if len(parts) > 1 else ""

    # 1. Build the official template background
    base_bg = build_template_background(project_dir, title, artist, size)

    renders_dir = project_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)
    output_video = renders_dir / "final_video.mp4"

    # Read editor_project.json for potential user audio trims or offsets
    editor_json_path = project_dir / "editor" / "editor_project.json"
    audio_ss = 0.0
    audio_dur = None
    if editor_json_path.exists():
        try:
            ed_data = json.loads(editor_json_path.read_text(encoding="utf-8"))
            for tr in ed_data.get("tracks", []):
                if tr.get("type") == "audio" or tr.get("id") == "track_audio":
                    for c in tr.get("clips", []):
                        audio_ss = float(c.get("sourceStart", 0.0) or 0.0)
                        c_start = float(c.get("start", 0.0) or 0.0)
                        c_end = float(c.get("end", 0.0) or 0.0)
                        if c_end > c_start:
                            audio_dur = c_end - c_start
                        break
        except Exception:
            pass

    total_duration = audio_dur if audio_dur and audio_dur > 0 else get_audio_duration(audio_path)
    total_frames = max(1, int(math.ceil(total_duration * fps)))

    # Fonts
    lyrics_font_size = 120
    intro_font_size = 120
    if editor_json_path.exists():
        try:
            for tr in ed_data.get("tracks", []):
                if tr.get("type") == "text" or tr.get("id") == "track_lyrics":
                    for c in tr.get("clips", []):
                        if c.get("style", {}).get("fontSize"):
                            lyrics_font_size = int(c["style"]["fontSize"])
                            break
                elif tr.get("type") == "intro" or tr.get("id") == "track_intro":
                    for c in tr.get("clips", []):
                        if c.get("style", {}).get("fontSize"):
                            intro_font_size = int(c["style"]["fontSize"])
                            break
        except Exception:
            pass

    font_intro_title = get_bernier_font(size=intro_font_size)
    font_intro_artist = get_bernier_font(size=max(20, int(intro_font_size * 0.55)))
    font_lyrics = get_bernier_font(size=lyrics_font_size)

    # 2. Determine Intro Window (reads customizable intro clip from editor_project.json)
    intro_start = 0.0
    first_lyric_start = lyric_lines[0]["start_seconds"] if lyric_lines else 10.0
    intro_end = min(5.0, max(1.5, first_lyric_start - 0.4))
    intro_title_text = title
    intro_artist_text = artist

    if editor_json_path.exists():
        try:
            for tr in ed_data.get("tracks", []):
                if tr.get("type") == "intro" or tr.get("id") == "track_intro":
                    for c in tr.get("clips", []):
                        intro_start = float(c.get("start", 0.0))
                        intro_end = float(c.get("end", intro_end))
                        txt = c.get("text", "")
                        if txt:
                            if "\n" in txt:
                                p_lines = txt.split("\n", 1)
                                intro_title_text, intro_artist_text = p_lines[0].strip(), p_lines[1].strip()
                            elif " — " in txt:
                                p_lines = txt.split(" — ", 1)
                                intro_title_text, intro_artist_text = p_lines[0].strip(), p_lines[1].strip()
                            elif " - " in txt:
                                p_lines = txt.split(" - ", 1)
                                intro_title_text, intro_artist_text = p_lines[0].strip(), p_lines[1].strip()
                            else:
                                intro_title_text = txt.strip()
                        break
        except Exception:
            pass

    project_no = parse_project_number(project_dir)
    print(f"[*] Background image : 0{project_no}.jpg (from 20 assets)")
    print(f"[*] Intro Title Card : {intro_start:.1f}s -> {intro_end:.1f}s")
    if audio_ss > 0:
        print(f"[*] Audio Trimmed    : Start offset {audio_ss:.2f}s")
    print(f"[*] Total duration   : {total_duration:.1f}s ({total_frames} frames)")

    # Launch FFmpeg stream
    audio_input_args = ["-ss", f"{audio_ss:.3f}", "-i", str(audio_path)] if audio_ss > 0 else ["-i", str(audio_path)]
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-nostats",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{size[0]}x{size[1]}",
        "-r",
        str(fps),
        "-i",
        "-",
        *audio_input_args,
        "-t",
        f"{total_duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(output_video),
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    last_log_time = time.time()
    line_ptr = 0
    num_lines = len(lyric_lines)

    try:
        for frame_idx in range(total_frames):
            t = frame_idx / fps
            frame = base_bg.copy()
            draw = ImageDraw.Draw(frame)

            # ------------------------------------------------------------------
            # Phase A: Intro Title Card (Song Title & Artist)
            # ------------------------------------------------------------------
            if intro_start <= t <= intro_end:
                # Fade in for first 0.8s, fade out during last 0.8s
                fade_in = min(1.0, (t - intro_start) / 0.8)
                fade_out = min(1.0, (intro_end - t) / 0.8)
                opacity = min(fade_in, fade_out)
                alpha = int(255 * max(0.05, opacity))

                text_title = intro_title_text.upper()
                text_artist = intro_artist_text.upper()

                # Center Title & Artist block vertically
                bbox_t = draw.textbbox((0, 0), text_title, font=font_intro_title)
                tw, th = bbox_t[2] - bbox_t[0], bbox_t[3] - bbox_t[1]

                bbox_a = draw.textbbox((0, 0), text_artist, font=font_intro_artist)
                aw, ah = bbox_a[2] - bbox_a[0], bbox_a[3] - bbox_a[1]

                gap = 20
                total_h = th + gap + ah
                x_t = (size[0] - tw) // 2
                y_t = (size[1] - total_h) // 2

                draw.text((x_t, y_t), text_title, font=font_intro_title, fill=(0, 0, 0, alpha))

                x_a = (size[0] - aw) // 2
                y_a = y_t + th + gap
                draw.text((x_a, y_a), text_artist, font=font_intro_artist, fill=(35, 35, 35, alpha))

            # ------------------------------------------------------------------
            # Phase B: Synchronized Lyrics
            # ------------------------------------------------------------------
            else:
                while line_ptr < num_lines and lyric_lines[line_ptr]["end_seconds"] < t:
                    line_ptr += 1

                active_lyric: dict[str, Any] | None = None
                if line_ptr < num_lines:
                    cand = lyric_lines[line_ptr]
                    if cand["start_seconds"] <= t <= cand["end_seconds"]:
                        active_lyric = cand

                if active_lyric:
                    text = wrap_text(active_lyric["text"], font_lyrics, max_width=1320)
                    start_s = active_lyric["start_seconds"]
                    end_s = active_lyric["end_seconds"]

                    fade = min(1.0, (t - start_s) / 0.22, (end_s - t) / 0.22)
                    fade = max(0.1, fade)
                    alpha = int(255 * fade)

                    try:
                        bbox = draw.multiline_textbbox(
                            (0, 0), text, font=font_lyrics, spacing=10, align="center"
                        )
                        lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    except Exception:
                        lw, lh = 800, 100

                    x = (size[0] - lw) // 2
                    y = (size[1] - lh) // 2

                    draw.multiline_text(
                        (x, y),
                        text,
                        font=font_lyrics,
                        fill=(0, 0, 0, alpha),
                        spacing=10,
                        align="center",
                    )

            # Stream frame to FFmpeg
            proc.stdin.write(frame.tobytes())

            now = time.time()
            if now - last_log_time > 1.5 or frame_idx == total_frames - 1:
                pct = int(((frame_idx + 1) / total_frames) * 100)
                print(f"    [Rendering] {pct:3d}% | Frame {frame_idx + 1}/{total_frames}", end="\r", flush=True)
                last_log_time = now

        proc.stdin.close()
        proc.wait(timeout=300)
        print()

    except Exception as exc:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        proc.kill()
        print(f"\n[!] Video render failed: {exc}")
        return None

    if output_video.exists() and output_video.stat().st_size > 1000:
        if state_file.exists():
            state["status"] = "rendered"
            state["video_path"] = str(output_video)
            state["rendered_at"] = now_iso()
            state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
            if not song_id:
                song_id = state.get("song_id")

        if song_id:
            mark_song_status(song_id, "rendered", project_dir=str(project_dir))

        return output_video

    return None