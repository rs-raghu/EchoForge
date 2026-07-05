from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from echoforge.core.project_builder import (
    get_selected_projects_from_db,
    init_next_project,
    init_project_by_song_id,
    list_projects,
)
from echoforge.orchestrator import doctor, init_project, run_all_placeholder, show_status, show_workflow
from echoforge.stages.musevault.asset_collector import collect_assets
from echoforge.stages.musevault.metadata_review import review_metadata
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

SONG_STATUSES = ["new", "selected", "assets_ready", "synced", "rendered", "uploaded", "used", "skipped", "failed"]


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def print_song(song: dict[str, Any] | None) -> None:
    if not song:
        print("No song found.")
        return
    print(f"#{song.get('rank') or '-'}  {song.get('title')} — {song.get('artist')}")
    print(f"id: {song.get('id')}")
    print(f"status: {song.get('status')}")
    if song.get("project_dir"):
        print(f"project: {song.get('project_dir')}")
    if song.get("youtube_url"):
        print(f"youtube: {song.get('youtube_url')}")
    if song.get("thumbnail_url"):
        print(f"thumbnail: {song.get('thumbnail_url')}")


def run_songscout_refresh(*, force: bool, max_songs: int, show_browser: bool) -> dict[str, Any]:
    init_database()
    decision = should_scrape_today(force=force)
    if not decision.should_scrape:
        return {"ok": True, "scraped": False, "reason": decision.reason, "today": decision.today, "weekday": decision.weekday, "last_successful_scrape_date": decision.last_successful_scrape_date}

    raw_rows = scrape_youtube_charts(max_songs=max_songs, headless=not show_browser)
    clean_songs = clean_rows(raw_rows)
    result = upsert_songs(clean_songs)
    record_scrape_result(success=True, row_count=len(raw_rows), clean_count=len(clean_songs), reason=decision.reason)
    delete_transient_debug_files()
    return {"ok": True, "scraped": True, "reason": decision.reason, "raw_rows": len(raw_rows), "clean_songs": len(clean_songs), **result}


def command_songscout_status(_: argparse.Namespace) -> None:
    init_database()
    decision = should_scrape_today(force=False)
    print_json({
        "counts": workflow_counts(),
        "scrape_policy": {
            "today": decision.today,
            "weekday": decision.weekday,
            "should_scrape_now": decision.should_scrape,
            "reason": decision.reason,
            "last_successful_scrape_date": decision.last_successful_scrape_date,
        },
        "metadata": get_all_metadata(),
    })


def command_songscout_refresh(args: argparse.Namespace) -> None:
    print_json(run_songscout_refresh(force=False, max_songs=args.max_songs, show_browser=args.show_browser))


def command_songscout_scrape(args: argparse.Namespace) -> None:
    print_json(run_songscout_refresh(force=args.force, max_songs=args.max_songs, show_browser=args.show_browser))


def command_songscout_clean(_: argparse.Namespace) -> None:
    print_json({"ok": True, "clean_songs": len(clean_raw_file())})


def command_songscout_top(args: argparse.Namespace) -> None:
    message = empty_database_message()
    if message:
        print(message)
        return
    print_song(get_next_song(include_failed=args.include_failed))


def command_songscout_list(args: argparse.Namespace) -> None:
    songs = list_songs(limit=args.limit, status=args.status)
    print_json([{"rank": s.get("rank"), "title": s.get("title"), "artist": s.get("artist"), "status": s.get("status"), "project_dir": s.get("project_dir"), "id": s.get("id")} for s in songs])


def command_songscout_skip(args: argparse.Namespace) -> None:
    print_json({"ok": True, "song": mark_song_skipped(args.song_id, note=args.note)})


def command_songscout_mark(args: argparse.Namespace) -> None:
    print_json({"ok": True, "song": mark_song_status(args.song_id, args.status, project_dir=args.project_dir, note=args.note)})


def command_songscout_reset(_: argparse.Namespace) -> None:
    print_json({"ok": True, "counts": reset_workflow_status()})


def command_songscout_export(args: argparse.Namespace) -> None:
    print_json(export_database_json(Path(args.output)))


def command_project_init_next(args: argparse.Namespace) -> None:
    print_json(init_next_project(include_failed=args.include_failed, allow_existing=not args.no_reuse))


def command_project_from_song(args: argparse.Namespace) -> None:
    print_json(init_project_by_song_id(args.song_id, allow_existing=not args.no_reuse))


def command_project_list(args: argparse.Namespace) -> None:
    print_json(list_projects(limit=args.limit))


def command_project_selected(args: argparse.Namespace) -> None:
    print_json(get_selected_projects_from_db(limit=args.limit))


def command_musevault_review(args: argparse.Namespace) -> None:
    print_json(review_metadata(args.project, popup=args.popup, auto=args.auto, force=args.force))


def command_musevault_collect(args: argparse.Namespace) -> None:
    print_json(collect_assets(args.project, popup=args.popup, auto_review=args.auto_review, force_review=args.force_review))


def add_songscout_parser(subparsers: argparse._SubParsersAction) -> None:
    songscout = subparsers.add_parser("songscout", help="SongScout chart database commands")
    sub = songscout.add_subparsers(dest="songscout_command", required=True)

    p = sub.add_parser("status", help="Show SongScout counts and Friday scrape policy"); p.set_defaults(func=command_songscout_status)
    p = sub.add_parser("refresh", help="Scrape only if Friday and not already scraped today"); p.add_argument("--max-songs", type=int, default=100); p.add_argument("--show-browser", action="store_true"); p.set_defaults(func=command_songscout_refresh)
    p = sub.add_parser("scrape", help="Manual scrape. Use --force outside Friday"); p.add_argument("--force", action="store_true"); p.add_argument("--max-songs", type=int, default=100); p.add_argument("--show-browser", action="store_true"); p.set_defaults(func=command_songscout_scrape)
    p = sub.add_parser("clean", help="Clean latest raw scrape JSON only"); p.set_defaults(func=command_songscout_clean)
    p = sub.add_parser("top", help="Show next unused top-rank song"); p.add_argument("--include-failed", action="store_true"); p.set_defaults(func=command_songscout_top)
    p = sub.add_parser("list", help="List songs"); p.add_argument("--limit", type=int, default=20); p.add_argument("--status", choices=SONG_STATUSES, default=None); p.set_defaults(func=command_songscout_list)
    p = sub.add_parser("skip", help="Mark skipped"); p.add_argument("song_id"); p.add_argument("--note", default="Skipped manually"); p.set_defaults(func=command_songscout_skip)
    p = sub.add_parser("mark", help="Set song status"); p.add_argument("song_id"); p.add_argument("status", choices=SONG_STATUSES); p.add_argument("--project-dir", default=None); p.add_argument("--note", default=None); p.set_defaults(func=command_songscout_mark)
    p = sub.add_parser("reset-status", help="Reset all songs to new"); p.set_defaults(func=command_songscout_reset)
    p = sub.add_parser("export-json", help="Export DB"); p.add_argument("--output", default="data/songscout/songs_export.json"); p.set_defaults(func=command_songscout_export)


def add_project_parser(subparsers: argparse._SubParsersAction) -> None:
    project = subparsers.add_parser("project", help="Project commands")
    sub = project.add_subparsers(dest="project_command", required=True)
    p = sub.add_parser("init-next", help="Create project for next song"); p.add_argument("--include-failed", action="store_true"); p.add_argument("--no-reuse", action="store_true"); p.set_defaults(func=command_project_init_next)
    p = sub.add_parser("from-song", help="Create project for song id"); p.add_argument("song_id"); p.add_argument("--no-reuse", action="store_true"); p.set_defaults(func=command_project_from_song)
    p = sub.add_parser("list", help="List projects"); p.add_argument("--limit", type=int, default=20); p.set_defaults(func=command_project_list)
    p = sub.add_parser("selected", help="List workflow songs"); p.add_argument("--limit", type=int, default=20); p.set_defaults(func=command_project_selected)


def add_musevault_parser(subparsers: argparse._SubParsersAction) -> None:
    muse = subparsers.add_parser("musevault", help="MuseVault review and asset collection")
    sub = muse.add_subparsers(dest="musevault_command", required=True)
    p = sub.add_parser("review", help="Review/edit title, artist and search metadata")
    p.add_argument("--project", required=True); p.add_argument("--popup", action="store_true"); p.add_argument("--auto", action="store_true"); p.add_argument("--force", action="store_true"); p.set_defaults(func=command_musevault_review)
    p = sub.add_parser("collect", help="Collect synced/plain lyrics, audio, thumbnail and background")
    p.add_argument("--project", required=True); p.add_argument("--popup", action="store_true"); p.add_argument("--auto-review", action="store_true"); p.add_argument("--force-review", action="store_true"); p.set_defaults(func=command_musevault_collect)




def command_verselock_sync(args: argparse.Namespace) -> None:
    from echoforge.stages.verselock.sync_runner import run_verselock_sync

    print_json(run_verselock_sync(args.project, force=args.force))



def add_verselock_parser(subparsers: argparse._SubParsersAction) -> None:
    verse = subparsers.add_parser("verselock", help="VerseLock lyric sync commands")
    sub = verse.add_subparsers(dest="verselock_command", required=True)
    p = sub.add_parser("sync", help="Reuse MuseVault synced lyrics if available")
    p.add_argument("--project", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=command_verselock_sync)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="echoforge", description="Clean EchoForge workflow runner")
    subparsers = parser.add_subparsers(dest="command")
    p = subparsers.add_parser("init", help="Create runtime folders"); p.set_defaults(func=lambda _: init_project())
    p = subparsers.add_parser("status", help="Show status"); p.set_defaults(func=lambda _: show_status())
    p = subparsers.add_parser("doctor", help="Check structure"); p.set_defaults(func=lambda _: doctor())
    p = subparsers.add_parser("workflow", help="Show workflow"); p.set_defaults(func=lambda _: show_workflow())
    p = subparsers.add_parser("all", help="Run current workflow checkpoint"); p.set_defaults(func=lambda _: run_all_placeholder())
    add_songscout_parser(subparsers)
    add_project_parser(subparsers)
    add_musevault_parser(subparsers)
    add_verselock_parser(subparsers)
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
