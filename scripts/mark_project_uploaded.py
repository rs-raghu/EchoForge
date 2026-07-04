from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def video_url(video_id: str | None, url: str | None) -> str:
    if url:
        return url
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return ""


def find_song_id(state: dict[str, Any]) -> str:
    for key in ("song_id", "selected_song_id", "songscout_id"):
        if isinstance(state.get(key), str) and state[key]:
            return state[key]
    song = state.get("song")
    if isinstance(song, dict):
        for key in ("id", "song_id"):
            if isinstance(song.get(key), str) and song[key]:
                return song[key]
    return ""


def mark_songscout_used(project: Path, state: dict[str, Any]) -> dict[str, Any]:
    dbs = list((ROOT / "data" / "songscout").glob("*.sqlite*"))
    if not dbs:
        return {"ok": False, "reason": "No SongScout sqlite database found."}
    db = dbs[0]
    song_id = find_song_id(state)
    title = state.get("title") or state.get("song_title") or state.get("song", {}).get("title")
    artist = state.get("artist") or state.get("artist_text") or state.get("song", {}).get("artist")
    try:
        con = sqlite3.connect(str(db))
        cur = con.cursor()
        cols = {row[1] for row in cur.execute("PRAGMA table_info(songs)").fetchall()}
        if "songs" not in {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
            return {"ok": False, "reason": "songs table missing", "db": str(db)}
        sets = []
        values: list[Any] = []
        if "status" in cols:
            sets.append("status=?")
            values.append("used")
        if "status_updated_at" in cols:
            sets.append("status_updated_at=?")
            values.append(now())
        if "project_dir" in cols:
            sets.append("project_dir=?")
            values.append(str(project.relative_to(ROOT)))
        if not sets:
            return {"ok": False, "reason": "No supported status columns in songs table", "db": str(db)}
        if song_id and "id" in cols:
            values.append(song_id)
            cur.execute(f"UPDATE songs SET {', '.join(sets)} WHERE id=?", values)
        elif title and "title" in cols:
            values.append(title)
            cur.execute(f"UPDATE songs SET {', '.join(sets)} WHERE title=?", values)
        else:
            return {"ok": False, "reason": "No song id/title available to update SongScout", "db": str(db)}
        con.commit()
        rows = cur.rowcount
        con.close()
        return {"ok": rows > 0, "rows_updated": rows, "db": str(db), "song_id": song_id, "title": title, "artist": artist}
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "db": str(db)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Mark a project and its SongScout song as uploaded/used.")
    ap.add_argument("--project", required=True)
    ap.add_argument("--video-id", default="")
    ap.add_argument("--url", default="")
    args = ap.parse_args()

    project = Path(args.project)
    if not project.is_absolute():
        project = ROOT / project
    state_path = project / "project_state.json"
    state = load_json(state_path)
    upload_report_path = project / "upload" / "youtube_upload_report.json"
    upload_report = load_json(upload_report_path)

    video_id = args.video_id or upload_report.get("video_id") or upload_report.get("id") or ""
    url = args.url or upload_report.get("url") or upload_report.get("video_url") or upload_report.get("youtube_url") or video_url(video_id, "")

    state["status"] = "uploaded"
    state["uploaded_at"] = now()
    if video_id:
        state["youtube_video_id"] = video_id
    if url:
        state["youtube_url"] = url
    state.setdefault("stages", {})
    if isinstance(state["stages"], dict):
        state["stages"]["uploaded"] = True
    save_json(state_path, state)

    upload_report.update({
        "ok": upload_report.get("ok", True),
        "video_id": video_id,
        "url": url,
        "marked_uploaded_at": now(),
    })
    save_json(upload_report_path, upload_report)

    songscout = mark_songscout_used(project, state)
    result = {
        "ok": True,
        "mode": "mark_project_uploaded",
        "project_dir": str(project.relative_to(ROOT) if project.is_relative_to(ROOT) else project),
        "video_id": video_id,
        "url": url,
        "project_state": str(state_path),
        "upload_report": str(upload_report_path),
        "songscout": songscout,
    }
    save_json(project / "upload" / "mark_uploaded_report.json", result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
