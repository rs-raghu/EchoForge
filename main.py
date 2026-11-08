from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone

from editor import run_editor_checkpoint
from musevault import collect_project_assets
from paths import ensure_runtime_dirs
from renderer import render_project_video
from songscout import (
    get_metadata,
    get_next_song,
    get_workflow_counts,
    has_any_songs,
    init_database,
    reset_song,
    scrape_and_sync_chart,
)
from tubeharbor import generate_youtube_metadata, upload_project_video
from verselock import sync_project_lyrics

FRIDAY = 4  # Monday = 0, Friday = 4


def get_current_friday_window(target_date: date | None = None) -> tuple[date, date]:
    current = target_date or datetime.now(timezone.utc).date()
    days_since_friday = (current.weekday() - FRIDAY) % 7
    window_start = current - timedelta(days=days_since_friday)
    window_end = window_start + timedelta(days=7)
    return window_start, window_end


def should_scrape_chart() -> tuple[bool, str]:
    if not has_any_songs():
        return True, "Database is completely empty"

    window_start, window_end = get_current_friday_window()
    last_scraped_raw = get_metadata("last_scraped_date")

    if not last_scraped_raw:
        return True, "No previous scrape date recorded"

    last_scraped_date = date.fromisoformat(last_scraped_raw)
    if last_scraped_date < window_start:
        return (
            True,
            f"Last scrape ({last_scraped_date}) expired (Current window: {window_start} to {window_end})",
        )

    return (
        False,
        f"Already scraped for current window ({window_start} to {window_end}, last: {last_scraped_date})",
    )


def run_pipeline() -> None:
    print("=" * 55)
    print("           EchoForge Automation Pipeline")
    print("=" * 55)

    # 1. Setup folders and database
    ensure_runtime_dirs()
    init_database()

    # Reset-song command handler (e.g. run.bat reset-song, run.bat reset-song <target>, run.bat reset-song all)
    reset_args = [arg for arg in sys.argv if arg.startswith("--reset") or arg in ("reset", "reset-song")]
    if reset_args:
        target = None
        for i, a in enumerate(sys.argv):
            if a in ("reset", "reset-song", "--reset-song", "--reset"):
                if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("-"):
                    target = sys.argv[i + 1]
                break
            elif a.startswith("--reset-song="):
                target = a.split("=", 1)[1]
                break

        results = reset_song(target)
        if results:
            print(f"[+] Successfully reset {len(results)} song(s) back to 'new':")
            for r in results:
                print(f"    - [{r.get('status')}] {r['title']} - {r['artist']}")
        else:
            print(f"[-] No matching songs found to reset (target: {target or 'latest'}).")
        return

    counts = get_workflow_counts()
    print(f"[*] Database status : {counts or 'Empty (0 songs)'}")

    # CLI flag checks
    force_scrape = any(arg in sys.argv for arg in ["--force", "--force-scrape", "force"])
    skip_upload = any(arg in sys.argv for arg in ["--skip-upload", "--metadata-only"])
    privacy_status = "public"
    for arg in sys.argv:
        if arg.startswith("--privacy="):
            privacy_status = arg.split("=", 1)[1].strip().lower()

    # 2. Check Scraper Conditions
    needs_scrape, reason = should_scrape_chart()
    if force_scrape:
        needs_scrape = True
        reason = "Manual force requested"

    print(f"[*] Chart policy    : {reason}")

    if needs_scrape:
        print("[*] Triggering YouTube Charts scraper (100 songs)...")
        scraped_count = scrape_and_sync_chart(max_songs=100, headless=True)
        print(f"[+] Successfully scraped & updated {scraped_count} songs!")

    # 3. Select next song
    song = get_next_song()
    if not song:
        print("[-] No songs available to process. Pipeline stopped.")
        return

    print("\n" + "=" * 55)
    print("STAGE 1 COMPLETE: Song Selected")
    print("=" * 55)
    print(f"[+] Title   : {song['title']}")
    print(f"    Artist  : {song['artist']}")
    print(f"    Rank    : #{song.get('rank') or '-'}")
    print(f"    YouTube : {song.get('youtube_url') or 'None'}")

    # 4. Stage 2: MuseVault Asset Collection
    print("\n" + "=" * 55)
    print("STAGE 2: Collecting Assets (MuseVault)")
    print("=" * 55)
    project_dir = collect_project_assets(song)
    print(f"\n[+] STAGE 2 COMPLETE: Assets ready in {project_dir.name}")

    # 5. Stage 3: VerseLock Lyrics Timing & Synchronization
    print("\n" + "=" * 55)
    print("STAGE 3: Aligning & Synchronizing Lyrics (VerseLock)")
    print("=" * 55)
    sync_result = sync_project_lyrics(project_dir, song["id"])
    print(f"[+] STAGE 3 COMPLETE: Status = {sync_result['mode'].upper()} ({sync_result.get('line_count', 0)} lines)")

    # WebEditor Checkpoint: Visual Review, Audio Trimming & Schedule/Publish Decision
    checkpoint_result = run_editor_checkpoint(project_dir)

    # 6. Stage 4: Renderer (Video Generation)
    print("\n" + "=" * 55)
    print("STAGE 4: Rendering Lyrics Video (Renderer)")
    print("=" * 55)
    video_path = render_project_video(project_dir, song["id"])
    if video_path and video_path.exists():
        size_mb = video_path.stat().st_size / (1024 * 1024)
        print(f"[+] STAGE 4 COMPLETE: Video created -> {video_path.name} ({size_mb:.1f} MB)")

    # 7. Stage 5: TubeHarbor (Metadata Generation & YouTube Upload)
    print("\n" + "=" * 55)
    print("STAGE 5: Metadata Enrichment & YouTube Upload (TubeHarbor)")
    print("=" * 55)

    # Apply WebEditor decision if chosen from UI, else CLI flags
    effective_privacy = checkpoint_result.get("privacy") or privacy_status
    effective_publish_at = checkpoint_result.get("publish_at")

    if skip_upload:
        print("[*] Generating Gemini AI metadata only (--skip-upload active)...")
        generate_youtube_metadata(project_dir)
        print("[+] Stage 5 metadata generated!")
    else:
        upload_report = upload_project_video(
            project_dir,
            song["id"],
            privacy_status=effective_privacy,
            publish_at=effective_publish_at,
        )
        print(f"\n[+] PIPELINE COMPLETE! Video published: {upload_report['video_url']}")


if __name__ == "__main__":
    run_pipeline()
