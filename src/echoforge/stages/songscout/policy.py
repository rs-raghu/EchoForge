from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from echoforge.stages.songscout.database import get_metadata, has_any_songs, init_database

FRIDAY = 4  # Python: Monday=0, Friday=4


def get_local_timezone() -> ZoneInfo:
    tz_name = os.getenv("ECHOFORGE_TIMEZONE", "Asia/Kolkata")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def today_local() -> datetime:
    return datetime.now(get_local_timezone())


def weekday_name(weekday: int) -> str:
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][weekday]


@dataclass(frozen=True)
class ScrapeDecision:
    should_scrape: bool
    reason: str
    today: str
    weekday: str
    last_successful_scrape_date: str | None
    is_forced: bool = False


def current_window_start(now: datetime) -> str:
    return (now.date() - timedelta(days=(now.weekday() - FRIDAY) % 7)).isoformat()


def should_scrape_today(force: bool = False) -> ScrapeDecision:
    init_database()
    now = today_local()
    today = now.date().isoformat()
    weekday = weekday_name(now.weekday())
    last_successful_scrape_date = get_metadata("last_successful_scrape_date")

    if force:
        return ScrapeDecision(
            should_scrape=True,
            reason="manual force enabled",
            today=today,
            weekday=weekday,
            last_successful_scrape_date=last_successful_scrape_date,
            is_forced=True,
        )

    window = current_window_start(now)
    completed = get_metadata("last_successful_scrape_window")
    if not completed and last_successful_scrape_date:
        try:
            completed = current_window_start(datetime.combine(date.fromisoformat(last_successful_scrape_date), datetime.min.time()))
        except ValueError:
            pass
    if completed and completed >= window:
        return ScrapeDecision(
            should_scrape=False,
            reason="chart already scraped successfully for the current Friday cycle",
            today=today,
            weekday=weekday,
            last_successful_scrape_date=last_successful_scrape_date,
        )

    return ScrapeDecision(
        should_scrape=True,
        reason=f"chart refresh pending for Friday cycle {window}",
        today=today,
        weekday=weekday,
        last_successful_scrape_date=last_successful_scrape_date,
    )


def empty_database_message() -> str | None:
    if has_any_songs():
        return None
    decision = should_scrape_today(force=False)
    if decision.should_scrape:
        return (
            "SongScout database is empty. Run `run.bat songscout refresh` to initialize the current weekly cycle."
        )
    return None
