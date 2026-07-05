from __future__ import annotations

import argparse
import json
from typing import Any

from echoforge.orchestrator import (
    doctor,
    init_project,
    run_all_placeholder,
    show_status,
    show_workflow,
)
from echoforge.stages.songscout.cleaner import clean_raw_file, clean_rows
from echoforge.stages.songscout.database import (
    export_database_json,
    get_all_metadata,
    init_database,
    mark_song_status,
    record_scrape_result,
    reset_workflow_status,
    upsert_songs,
    workflow_counts,
)
from echoforge.stages.songscout.policy import empty_database_message, should_scrape_today
from echoforge.stages.songscout.scraper import delete_transient_debug_files, scrape_youtube_charts
from echoforge.stages.songscout.selector import get_next_song, list_songs, mark_song_skipped


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def print_song(song: dict[str, Any] | None) -> None:
    if not song:
        print("No song found.")
        return
    print(f"#{song.get('rank') or '-'}  {song.get('title')} — {song.get('artist')}")
    print(f"id: {song.get('id')}")
    print(f"status: {song.get('status')}")
    if song.get("youtube_url"):
        print(f"youtube: {song.get('youtube_url')}")
    if song.get("thumbnail_url"):
        print(f"thumbnail: {song.get('thumbnail_url')}")


def run_songscout_refresh(*, force: bool, max_songs: int, show_browser: bool) -> dict[str, Any]:
    init_database()
    decision = should_scrape_today(force=force)

    if not decision.should_scrape:
        return {
            "ok": True,
            "scraped": False,
            "reason": decision.reason,
            "today": decision.today,
            "weekday": decision.weekday,
            "last_successful_scrape_date": decision.last_successful_scrape_date,
        }

    try:
        raw_rows = scrape_youtube_charts(max_songs=max_songs, headless=not show_browser)
        clean_songs = clean_rows(raw_rows)
        result = upsert_songs(clean_songs)
        record_scrape_result(success=True, row_count=len(raw_rows), clean_count=len(clean_songs), reason=decision.reason)
        delete_transient_debug_files()
        return {
            "ok": True,
            "scraped": True,
            "reason": decision.reason,
            "raw_rows": len(raw_rows),
            "clean_songs": len(clean_songs),
            **result,
        }
    except Exception as exc:
        record_scrape_result(success=False, reason=str(exc))
        raise


def command_songscout_status(_: argparse.Namespace) -> None:
    init_database()
    decision = should_scrape_today(force=False)
    payload = {
        "counts": workflow_counts(),
        "scrape_policy": {
            "today": decision.today,
            "weekday": decision.weekday,
            "should_scrape_now": decision.should_scrape,
            "reason": decision.reason,
            "last_successful_scrape_date": decision.last_successful_scrape_date,
        },
        "metadata": get_all_metadata(),
    }
    print_json(payload)


def command_songscout_refresh(args: argparse.Namespace) -> None:
    result = run_songscout_refresh(force=False, max_songs=args.max_songs, show_browser=args.show_browser)
    print_json(result)


def command_songscout_scrape(args: argparse.Namespace) -> None:
    result = run_songscout_refresh(force=args.force, max_songs=args.max_songs, show_browser=args.show_browser)
    print_json(result)


def command_songscout_clean(_: argparse.Namespace) -> None:
    songs = clean_raw_file()
    print_json({"ok": True, "clean_songs": len(songs)})


def command_songscout_top(args: argparse.Namespace) -> None:
    message = empty_database_message()
    if message:
        print(message)
        return
    print_song(get_next_song(include_failed=args.include_failed))


def command_songscout_list(args: argparse.Namespace) -> None:
    songs = list_songs(limit=args.limit, status=args.status)
    compact = [
        {
            "rank": song.get("rank"),
            "title": song.get("title"),
            "artist": song.get("artist"),
            "status": song.get("status"),
            "id": song.get("id"),
        }
        for song in songs
    ]
    print_json(compact)


def command_songscout_skip(args: argparse.Namespace) -> None:
    song = mark_song_skipped(args.song_id, note=args.note)
    print_json({"ok": bool(song), "song": song})


def command_songscout_mark(args: argparse.Namespace) -> None:
    song = mark_song_status(args.song_id, args.status, project_dir=args.project_dir, note=args.note)
    print_json({"ok": bool(song), "song": song})


def command_songscout_reset(_: argparse.Namespace) -> None:
    print_json({"ok": True, "counts": reset_workflow_status()})


def command_songscout_export(args: argparse.Namespace) -> None:
    print_json(export_database_json(args.output))


def add_songscout_parser(subparsers: argparse._SubParsersAction) -> None:
    songscout = subparsers.add_parser("songscout", help="SongScout chart database commands")
    song_sub = songscout.add_subparsers(dest="songscout_command", required=True)

    status = song_sub.add_parser("status", help="Show SongScout counts and Friday scrape policy")
    status.set_defaults(func=command_songscout_status)

    refresh = song_sub.add_parser("refresh", help="Scrape only if Friday and not already scraped today")
    refresh.add_argument("--max-songs", type=int, default=100)
    refresh.add_argument("--show-browser", action="store_true")
    refresh.set_defaults(func=command_songscout_refresh)

    scrape = song_sub.add_parser("scrape", help="Manual scrape. Use --force outside Friday")
    scrape.add_argument("--force", action="store_true", help="Scrape even when today is not Friday")
    scrape.add_argument("--max-songs", type=int, default=100)
    scrape.add_argument("--show-browser", action="store_true")
    scrape.set_defaults(func=command_songscout_scrape)

    clean = song_sub.add_parser("clean", help="Clean latest raw scrape JSON only")
    clean.set_defaults(func=command_songscout_clean)

    top = song_sub.add_parser("top", help="Show next unused top-rank song")
    top.add_argument("--include-failed", action="store_true", help="Allow failed songs to retry")
    top.set_defaults(func=command_songscout_top)

    list_cmd = song_sub.add_parser("list", help="List songs in rank order")
    list_cmd.add_argument("--limit", type=int, default=20)
    list_cmd.add_argument("--status", choices=["new", "used", "skipped", "failed"], default=None)
    list_cmd.set_defaults(func=command_songscout_list)

    skip = song_sub.add_parser("skip", help="Mark a song as skipped")
    skip.add_argument("song_id")
    skip.add_argument("--note", default="Skipped manually")
    skip.set_defaults(func=command_songscout_skip)

    mark = song_sub.add_parser("mark", help="Set song status")
    mark.add_argument("song_id")
    mark.add_argument("status", choices=["new", "used", "skipped", "failed"])
    mark.add_argument("--project-dir", default=None)
    mark.add_argument("--note", default=None)
    mark.set_defaults(func=command_songscout_mark)

    reset = song_sub.add_parser("reset-status", help="Reset all songs back to new")
    reset.set_defaults(func=command_songscout_reset)

    export = song_sub.add_parser("export-json", help="Export DB to JSON for debug")
    export.add_argument("--output", default="data/songscout/songs_export.json")
    export.set_defaults(func=command_songscout_export)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="echoforge",
        description="Clean EchoForge workflow runner",
    )

    subparsers = parser.add_subparsers(dest="command")

    init = subparsers.add_parser("init", help="Create required runtime folders")
    init.set_defaults(func=lambda _: init_project())

    status = subparsers.add_parser("status", help="Show project status and paths")
    status.set_defaults(func=lambda _: show_status())

    doctor_cmd = subparsers.add_parser("doctor", help="Check clean project structure")
    doctor_cmd.set_defaults(func=lambda _: doctor())

    workflow = subparsers.add_parser("workflow", help="Show official workflow")
    workflow.set_defaults(func=lambda _: show_workflow())

    all_cmd = subparsers.add_parser("all", help="Run current connected workflow")
    all_cmd.set_defaults(func=lambda _: run_all_placeholder())

    add_songscout_parser(subparsers)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
