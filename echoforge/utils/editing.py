import os
import shutil
import time


FINAL_VIDEO = "final_video.mp4"
PREVIEW_VIDEO = "final_video_preview.mp4"
EDITED_EXPORT = "edited_final_video.mp4"
ORIGINAL_BACKUP = "final_video_original.mp4"
HANDOFF_MARKER = ".clipchamp_handoff_started"


def find_ready_edited_export(workspace_dir: str, stable_seconds: int = 15) -> str | None:
    if not workspace_dir or not os.path.isdir(workspace_dir):
        return None

    preferred = os.path.join(workspace_dir, EDITED_EXPORT)
    candidates: list[str] = []
    if os.path.exists(preferred):
        candidates.append(preferred)

    for name in os.listdir(workspace_dir):
        lower = name.lower()
        if not lower.endswith(".mp4"):
            continue
        if lower in {FINAL_VIDEO, PREVIEW_VIDEO, ORIGINAL_BACKUP}:
            continue
        path = os.path.join(workspace_dir, name)
        if path not in candidates:
            candidates.append(path)

    marker_path = os.path.join(workspace_dir, HANDOFF_MARKER)
    marker_time = os.path.getmtime(marker_path) if os.path.exists(marker_path) else 0
    now = time.time()
    ready: list[tuple[float, str]] = []
    for path in candidates:
        try:
            stat = os.stat(path)
        except OSError:
            continue
        if stat.st_size <= 0:
            continue
        if stat.st_mtime <= marker_time:
            continue
        if now - stat.st_mtime < stable_seconds:
            continue
        ready.append((stat.st_mtime, path))

    if not ready:
        return None
    return max(ready)[1]


def promote_edited_export(workspace_dir: str, stable_seconds: int = 15) -> str | None:
    export_path = find_ready_edited_export(workspace_dir, stable_seconds=stable_seconds)
    if not export_path:
        return None

    final_path = os.path.join(workspace_dir, FINAL_VIDEO)
    backup_path = os.path.join(workspace_dir, ORIGINAL_BACKUP)

    if os.path.abspath(export_path) == os.path.abspath(final_path):
        return final_path

    if os.path.exists(final_path) and not os.path.exists(backup_path):
        shutil.copy2(final_path, backup_path)

    shutil.copy2(export_path, final_path)
    return export_path
