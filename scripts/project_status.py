from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def exists(path: Path) -> bool:
    return path.exists() and (path.stat().st_size > 0 if path.is_file() else True)


def find_video_url(report: dict[str, Any]) -> str:
    if not (report.get("ok") and report.get("video_id")): return ""
    for key in ("url", "video_url", "youtube_url", "watch_url"):
        if isinstance(report.get(key), str) and report[key]:
            return report[key]
    vid = report.get("video_id") or report.get("id")
    if isinstance(vid, str) and vid:
        return f"https://www.youtube.com/watch?v={vid}"
    return ""


def status(project: Path) -> dict[str, Any]:
    project = project.resolve()
    state = load_json(project / "project_state.json")
    upload_report = load_json(project / "upload" / "youtube_upload_report.json")
    render_status = load_json(project / "upload" / "render_upload_status.json")

    checks = {
        "project_state": exists(project / "project_state.json"),
        "asset_manifest": exists(project / "asset_manifest.json"),
        "metadata_review": exists(project / "metadata_review.json"),
        "lyrics_txt": exists(project / "lyrics" / "lyrics.txt"),
        "synced_source_lrc": exists(project / "lyrics" / "synced_lyrics.lrc"),
        "audio_m4a": exists(project / "audio" / "source_audio.m4a"),
        "music_thumbnail": exists(project / "images" / "music_thumbnail.jpg"),
        "background_source": exists(project / "images" / "background_source.jpg"),
        "video_background": exists(project / "images" / "video_background.jpg"),
        "upload_thumbnail": exists(project / "renders" / "upload_thumbnail.jpg"),
        "final_sync_lrc": exists(project / "sync" / "final_synced_lyrics.lrc"),
        "final_sync_json": exists(project / "sync" / "final_synced_lyrics.json"),
        "editor_project": exists(project / "editor" / "editor_project.json"),
        "rendered_video": exists(project / "renders" / "final_video.mp4"),
        "youtube_metadata": exists(project / "upload" / "youtube_metadata.json"),
        "youtube_upload_report": exists(project / "upload" / "youtube_upload_report.json"),
    }

    stages = {
        "song_selected": checks["project_state"],
        "assets_ready": all(checks[k] for k in ["asset_manifest", "lyrics_txt", "audio_m4a", "music_thumbnail", "video_background", "upload_thumbnail"]),
        "lyrics_synced": checks["final_sync_lrc"] and checks["final_sync_json"],
        "editor_prepared": checks["editor_project"],
        "rendered": checks["rendered_video"],
        "metadata_generated": checks["youtube_metadata"],
        "uploaded": bool(upload_report.get("ok") and upload_report.get("video_id")),
    }

    return {
        "ok": True,
        "project_dir": str(project.relative_to(ROOT) if project.is_relative_to(ROOT) else project),
        "title": state.get("title") or state.get("song_title") or state.get("song", {}).get("title") or "",
        "artist": state.get("artist") or state.get("artist_text") or state.get("song", {}).get("artist") or "",
        "status": state.get("status") or state.get("stage") or "",
        "stages": stages,
        "checks": checks,
        "render_status": render_status,
        "youtube_url": find_video_url(upload_report),
        "upload_report": upload_report if upload_report else None,
    }


def print_pretty(obj: dict[str, Any]) -> None:
    mark = lambda x: "✅" if x else "❌"
    print(f"Project: {obj['project_dir']}")
    if obj.get("title") or obj.get("artist"):
        print(f"Song: {obj.get('title','')} — {obj.get('artist','')}")
    print(f"Status: {obj.get('status') or 'unknown'}")
    print("")
    labels = [
        ("song_selected", "Song selected"),
        ("assets_ready", "Assets ready"),
        ("lyrics_synced", "Lyrics synced"),
        ("editor_prepared", "Editor prepared"),
        ("rendered", "Rendered"),
        ("metadata_generated", "Metadata generated"),
        ("uploaded", "Uploaded"),
    ]
    for key, label in labels:
        print(f"{label:<20} {mark(obj['stages'].get(key))}")
    if obj.get("youtube_url"):
        print(f"\nYouTube URL: {obj['youtube_url']}")
    rs = obj.get("render_status") or {}
    if rs:
        print(f"Last render/upload: {rs.get('stage','')} - {rs.get('message','')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    project = Path(args.project)
    if not project.is_absolute():
        project = ROOT / project
    obj = status(project)
    if args.json:
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    else:
        print_pretty(obj)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
