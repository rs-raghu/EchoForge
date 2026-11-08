from __future__ import annotations

import json
import mimetypes
import subprocess
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from echoforge.paths import ROOT_DIR


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_audio_duration(audio_path: Path) -> float:
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


def prepare_editor_project(project_dir: Path) -> Path:
    """Prepare editor/editor_project.json from synced lyrics and media."""
    editor_dir = project_dir / "editor"
    editor_dir.mkdir(parents=True, exist_ok=True)
    editor_json = editor_dir / "editor_project.json"

    sync_json = project_dir / "sync" / "final_synced_lyrics.json"
    audio_file = project_dir / "audio" / "source_audio.m4a"
    bg_file = project_dir / "images" / "video_background.jpg"

    state_file = project_dir / "project_state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    title = state.get("title")
    artist = state.get("artist")
    if not title:
        import re
        raw = re.sub(r"^\d+_", "", project_dir.name)
        parts = raw.split("_")
        title = parts[0].title() if parts else project_dir.name
        artist = parts[1].upper() if len(parts) > 1 else ""

    # Ensure official video background is built so WebEditor has full preview
    from echoforge.renderer import build_template_background
    try:
        build_template_background(project_dir, title, artist)
    except Exception as exc:
        print(f"[!] Warning: Could not pre-build template background: {exc}")

    duration = get_audio_duration(audio_file) if audio_file.exists() else 180.0

    lines: list[dict[str, Any]] = []
    if sync_json.exists():
        data = json.loads(sync_json.read_text(encoding="utf-8"))
        lines = data.get("lines", [])

    first_lyric_start = float(lines[0]["start_seconds"]) if lines else 10.0
    intro_end = min(5.0, max(1.5, first_lyric_start - 0.4))

    lyric_clips: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        lyric_clips.append(
            {
                "id": f"lyric_{idx:04d}",
                "type": "text",
                "name": f"Lyric {idx}",
                "start": round(float(line.get("start_seconds", 0)), 3),
                "end": round(float(line.get("end_seconds", 3)), 3),
                "text": line.get("text", ""),
                "x": 960,
                "y": 540,
                "width": 1320,
                "height": 140,
                "rotation": 0,
                "style": {
                    "fontFamily": "Bernier",
                    "fontSize": 120,
                    "color": "#000000",
                    "align": "center",
                    "opacity": 1.0,
                },
            }
        )

    editor_data = {
        "schema": "echoforge.webeditor.v2",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "project": {
            "title": title,
            "artist": artist,
            "duration": duration,
            "project_dir": str(project_dir),
        },
        "intro": {
            "title": title,
            "artist": artist,
            "start": 0.0,
            "end": round(intro_end, 3),
        },
        "canvas": {"width": 1920, "height": 1080},
        "assets": {
            "audio": str(audio_file.relative_to(project_dir)).replace("\\", "/") if audio_file.exists() else "",
            "background": str(bg_file.relative_to(project_dir)).replace("\\", "/") if bg_file.exists() else "",
            "font_bernier": "assets/fonts/Bernier/Bernier-Regular.ttf",
        },
        "tracks": [
            {
                "id": "track_background",
                "name": "Background",
                "type": "image",
                "locked": True,
                "clips": [
                    {
                        "id": "bg_0001",
                        "type": "image",
                        "name": "Background",
                        "start": 0,
                        "end": duration,
                        "asset": str(bg_file.relative_to(project_dir)).replace("\\", "/") if bg_file.exists() else "",
                        "x": 960,
                        "y": 540,
                        "width": 1920,
                        "height": 1080,
                        "opacity": 1.0,
                    }
                ],
            },
            {
                "id": "track_intro",
                "name": "Intro Card",
                "type": "intro",
                "locked": False,
                "clips": [
                    {
                        "id": "intro_0001",
                        "type": "intro",
                        "name": f"Intro ({intro_end:.1f}s)",
                        "start": 0.0,
                        "end": round(intro_end, 3),
                        "text": f"{title}\n{artist}",
                        "style": {
                            "fontFamily": "Bernier",
                            "fontSize": 120,
                            "color": "#000000",
                            "align": "center",
                            "opacity": 1.0,
                        },
                    }
                ],
            },
            {
                "id": "track_lyrics",
                "name": "Lyrics",
                "type": "text",
                "locked": False,
                "clips": lyric_clips,
            },
            {
                "id": "track_audio",
                "name": "Audio",
                "type": "audio",
                "locked": False,
                "clips": [
                    {
                        "id": "audio_0001",
                        "type": "audio",
                        "name": "Source Audio",
                        "start": 0,
                        "end": duration,
                        "asset": str(audio_file.relative_to(project_dir)).replace("\\", "/"),
                        "volume": 1.0,
                    }
                ],
            },
        ],
    }

    editor_json.write_text(json.dumps(editor_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return editor_json


def save_editor_changes_to_sync(project_dir: Path, editor_data: dict[str, Any]) -> None:
    """Save modified editor clips back to sync/final_synced_lyrics.json."""
    tracks = editor_data.get("tracks", [])
    lyric_clips: list[dict[str, Any]] = []

    for t in tracks:
        if t.get("id") == "track_lyrics" or t.get("type") == "text":
            lyric_clips = t.get("clips", [])
            break

    if not lyric_clips and "clips" in editor_data:
        lyric_clips = [c for c in editor_data["clips"] if c.get("type") in ("text", "lyric")]

    updated_lines: list[dict[str, Any]] = []
    for idx, c in enumerate(sorted(lyric_clips, key=lambda x: float(x.get("start", 0)))):
        start = round(float(c.get("start", 0)), 3)
        end = round(float(c.get("end", start + 3)), 3)
        updated_lines.append(
            {
                "index": idx,
                "start_seconds": start,
                "end_seconds": end,
                "start_ms": int(start * 1000),
                "end_ms": int(end * 1000),
                "timestamp": f"[{int(start // 60):02d}:{int(start % 60):02d}.{int((start % 1) * 100):02d}]",
                "text": c.get("text", "").strip(),
            }
        )

    sync_path = project_dir / "sync" / "final_synced_lyrics.json"
    if sync_path.exists():
        existing = json.loads(sync_path.read_text(encoding="utf-8"))
        existing["lines"] = updated_lines
        existing["line_count"] = len(updated_lines)
        existing["updated_at"] = now_iso()
        sync_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

    out_lrc = project_dir / "sync" / "final_synced_lyrics.lrc"
    out_lrc.write_text(
        "\n".join(f"{item['timestamp']} {item['text']}" for item in updated_lines) + "\n",
        encoding="utf-8",
    )


def run_editor_checkpoint(project_dir: Path, port: int = 8765) -> None:
    """Launch the WebEditor HTTP server, open browser, and wait for user completion."""
    prepare_editor_project(project_dir)
    web_dir = ROOT_DIR / "apps" / "webeditor"

    class EditorHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, payload: Any, status: int = 200):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_file_with_range(self, path: Path):
            if not path.is_file():
                self.send_response(404)
                self.end_headers()
                return

            size = path.stat().st_size
            start, end = 0, size - 1
            status = 200

            range_header = self.headers.get("Range")
            if range_header and range_header.startswith("bytes="):
                try:
                    parts = range_header.split("=")[1].split("-")
                    if parts[0]:
                        start = int(parts[0])
                    if len(parts) > 1 and parts[1]:
                        end = int(parts[1])
                    status = 206
                except Exception:
                    pass

            self.send_response(status)
            mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.send_header("Content-Type", mime)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()

            with path.open("rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/project":
                ep = project_dir / "editor" / "editor_project.json"
                if ep.exists():
                    self.send_json(json.loads(ep.read_text(encoding="utf-8")))
                else:
                    self.send_json({"error": "Project not found"}, 404)
                return

            if path.startswith("/media/"):
                sub = unquote(path[7:])
                self.send_file_with_range(project_dir / sub)
                return

            if path.startswith("/root/"):
                sub = unquote(path[6:])
                self.send_file_with_range(ROOT_DIR / sub)
                return

            # Static files
            clean_name = path.lstrip("/") or "index.html"
            target_file = web_dir / clean_name
            if target_file.exists():
                self.send_file_with_range(target_file)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/api/project":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                    # Save to editor_project.json
                    ep = project_dir / "editor" / "editor_project.json"
                    ep.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                    # Sync back to final_synced_lyrics.json
                    save_editor_changes_to_sync(project_dir, payload)
                    print("\n[+] [WebEditor] Timeline changes saved successfully!")
                    self.send_json({"ok": True})
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)}, 400)
                return

            self.send_response(404)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", port), EditorHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    url = f"http://127.0.0.1:{port}/"
    print(f"\n" + "=" * 55)
    print(f"WEBEDITOR CHECKPOINT: {url}")
    print("=" * 55)
    print(f"[*] Visual WebEditor launched in your browser.")
    print(f"[*] Instructions:")
    print(f"    1. Scrub audio & adjust any lyric timing on the timeline.")
    print(f"    2. Trim intro dialogue offset if needed.")
    print(f"    3. Click 'Save' (Ctrl+S) in the editor.")
    print(f"    4. Return here and press [ENTER] to proceed to video rendering.")
    print("=" * 55)

    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        input("\n>>> Press [ENTER] when done editing to render video: ")
    except (EOFError, KeyboardInterrupt):
        pass

    server.shutdown()
    print("[*] WebEditor closed. Proceeding to Renderer...")
