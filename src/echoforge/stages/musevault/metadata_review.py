from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_project_dir(project: str | Path) -> Path:
    path = Path(project)
    if path.is_file():
        path = path.parent
    if not path.exists():
        raise FileNotFoundError(f"Project path not found: {path}")
    if not (path / "project_state.json").exists():
        raise FileNotFoundError(f"project_state.json not found inside: {path}")
    return path


def clean_title(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"\s+", " ", text)
    noise = [
        r"(?i)\s*[-–—|:]\s*(official\s*)?(music\s*)?video.*$",
        r"(?i)\s*[-–—|:]\s*(official\s*)?lyrics?.*$",
        r"(?i)\s*[-–—|:]\s*audio\s*$",
        r"(?i)\((official\s*)?(music\s*)?video[^)]*\)",
        r"(?i)\[(official\s*)?(music\s*)?video[^\]]*\]",
        r"(?i)\((official\s*)?lyrics?[^)]*\)",
        r"(?i)\[(official\s*)?lyrics?[^\]]*\]",
        r"(?i)\((visualizer|audio|4k|hd|remastered)[^)]*\)",
        r"(?i)\[(visualizer|audio|4k|hd|remastered)[^\]]*\]",
    ]
    for pattern in noise:
        text = re.sub(pattern, "", text).strip()
    return re.sub(r"\s+", " ", text).strip(" -–—|:")


def clean_artist(text: str) -> str:
    text = clean_title(text)
    text = re.sub(r"(?i)\bofficial\b.*$", "", text).strip()
    return re.sub(r"\s+", " ", text).strip(" -–—|:")


def search_text(text: str) -> str:
    text = clean_title(text)
    text = re.sub(r"(?i)\b(feat\.|ft\.|featuring)\b", " ", text)
    text = re.sub(r"[&×x,]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def source_from_state(state: dict[str, Any]) -> dict[str, Any]:
    song = state.get("song") if isinstance(state.get("song"), dict) else {}
    return {
        "song_id": state.get("song_id") or song.get("id"),
        "rank": state.get("rank") or song.get("rank"),
        "source_title": state.get("title") or song.get("title") or "",
        "source_artist": state.get("artist") or song.get("artist") or "",
        "youtube_url": state.get("youtube_url") or song.get("youtube_url") or "",
        "thumbnail_url": state.get("thumbnail_url") or song.get("thumbnail_url") or "",
    }


def default_review(state: dict[str, Any]) -> dict[str, Any]:
    source = source_from_state(state)
    display_title = clean_title(source["source_title"]) or source["source_title"]
    display_artist = clean_artist(source["source_artist"]) or source["source_artist"]
    return {
        "schema_version": 1,
        "reviewed": False,
        "reviewed_at": None,
        "song_id": source["song_id"],
        "rank": source["rank"],
        "source_title": source["source_title"],
        "source_artist": source["source_artist"],
        "display_title": display_title,
        "display_artist": display_artist,
        "search_title": search_text(display_title),
        "search_artist": search_text(display_artist),
        "youtube_url": source["youtube_url"],
        "thumbnail_url": source["thumbnail_url"],
    }


def update_project_state(project_dir: Path, review: dict[str, Any]) -> None:
    path = project_dir / "project_state.json"
    state = read_json(path)
    state["title"] = review["display_title"]
    state["artist"] = review["display_artist"]
    state["youtube_url"] = review["youtube_url"]
    state["thumbnail_url"] = review["thumbnail_url"]
    state["reviewed_metadata"] = {
        "source_title": review["source_title"],
        "source_artist": review["source_artist"],
        "display_title": review["display_title"],
        "display_artist": review["display_artist"],
        "search_title": review["search_title"],
        "search_artist": review["search_artist"],
        "reviewed_at": review["reviewed_at"],
    }
    state.setdefault("stages", {})["metadata_review"] = "done"
    state["current_stage"] = "metadata_reviewed"
    state["updated_at"] = now_iso()
    write_json(path, state)


def terminal_review(payload: dict[str, Any], *, auto: bool = False) -> dict[str, Any]:
    review = dict(payload)
    if auto:
        review["reviewed"] = True
        review["reviewed_at"] = now_iso()
        return review

    print("\nMuseVault metadata review")
    print("=" * 50)
    print(f"Source title : {review['source_title']}")
    print(f"Source artist: {review['source_artist']}")
    print("-" * 50)
    print(f"Display title : {review['display_title']}")
    print(f"Display artist: {review['display_artist']}")
    print(f"Search title  : {review['search_title']}")
    print(f"Search artist : {review['search_artist']}")
    print(f"YouTube URL   : {review['youtube_url']}")
    print(f"Thumbnail URL : {review['thumbnail_url']}")

    choice = input("\nIs this correct? [Y/edit/cancel]: ").strip().lower()
    if choice in {"", "y", "yes"}:
        review["reviewed"] = True
        review["reviewed_at"] = now_iso()
        return review
    if choice in {"c", "cancel", "n", "no"}:
        raise RuntimeError("Metadata review cancelled.")

    for field in ["display_title", "display_artist", "search_title", "search_artist", "youtube_url", "thumbnail_url"]:
        current = str(review.get(field) or "")
        value = input(f"{field.replace('_', ' ').title()} [{current}]: ").strip()
        if value:
            review[field] = value

    review["reviewed"] = True
    review["reviewed_at"] = now_iso()
    return review


def popup_review(payload: dict[str, Any]) -> dict[str, Any]:
    import tkinter as tk
    from tkinter import messagebox

    result: dict[str, Any] | None = None
    root = tk.Tk()
    root.title("MuseVault Metadata Review")
    root.geometry("760x460")
    root.resizable(False, False)

    tk.Label(root, text="Check song title and artist before continuing", font=("Arial", 14, "bold")).pack(pady=(14, 8))
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=18, pady=8)

    fields = [
        ("source_title", "Source Title", True),
        ("source_artist", "Source Artist", True),
        ("display_title", "Display Title", False),
        ("display_artist", "Display Artist", False),
        ("search_title", "Search Title", False),
        ("search_artist", "Search Artist", False),
        ("youtube_url", "YouTube URL", False),
        ("thumbnail_url", "Thumbnail URL", False),
    ]
    entries: dict[str, tk.Entry] = {}
    for row, (key, label, readonly) in enumerate(fields):
        tk.Label(frame, text=label, anchor="w", width=16).grid(row=row, column=0, sticky="w", pady=4)
        entry = tk.Entry(frame, width=82)
        entry.insert(0, str(payload.get(key) or ""))
        if readonly:
            entry.configure(state="readonly")
        entry.grid(row=row, column=1, sticky="we", pady=4)
        entries[key] = entry

    def on_continue() -> None:
        nonlocal result
        review = dict(payload)
        for key, _, readonly in fields:
            if not readonly:
                review[key] = entries[key].get().strip()
        if not review.get("display_title") or not review.get("display_artist"):
            messagebox.showerror("Missing metadata", "Display title and display artist are required.")
            return
        review["reviewed"] = True
        review["reviewed_at"] = now_iso()
        result = review
        root.destroy()

    def on_cancel() -> None:
        root.destroy()

    buttons = tk.Frame(root)
    buttons.pack(pady=12)
    tk.Button(buttons, text="Continue", width=18, command=on_continue).pack(side="left", padx=8)
    tk.Button(buttons, text="Cancel", width=18, command=on_cancel).pack(side="left", padx=8)
    root.mainloop()

    if result is None:
        raise RuntimeError("Metadata review cancelled.")
    return result


def review_metadata(project: str | Path, *, popup: bool = False, auto: bool = False, force: bool = False) -> dict[str, Any]:
    project_dir = resolve_project_dir(project)
    review_path = project_dir / "metadata_review.json"
    if review_path.exists() and not force:
        review = read_json(review_path)
        if review.get("reviewed"):
            return {"ok": True, "created": False, "project_dir": str(project_dir), "review": review}

    payload = default_review(read_json(project_dir / "project_state.json"))
    if popup:
        try:
            review = popup_review(payload)
        except Exception as exc:
            print(f"Popup failed; terminal review will be used. Reason: {exc}")
            review = terminal_review(payload, auto=auto)
    else:
        review = terminal_review(payload, auto=auto)

    write_json(review_path, review)
    update_project_state(project_dir, review)
    return {"ok": True, "created": True, "project_dir": str(project_dir), "review": review}


def load_review(project: str | Path) -> dict[str, Any] | None:
    project_dir = resolve_project_dir(project)
    path = project_dir / "metadata_review.json"
    if not path.exists():
        return None
    review = read_json(path)
    return review if review.get("reviewed") else None
