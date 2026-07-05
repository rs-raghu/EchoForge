from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
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

    if now.weekday() != FRIDAY:
        return ScrapeDecision(
            should_scrape=False,
            reason=f"today is {weekday}; automatic scraping is allowed only on Friday",
            today=today,
            weekday=weekday,
            last_successful_scrape_date=last_successful_scrape_date,
        )

    if last_successful_scrape_date == today:
        return ScrapeDecision(
            should_scrape=False,
            reason="chart already scraped successfully today",
            today=today,
            weekday=weekday,
            last_successful_scrape_date=last_successful_scrape_date,
        )

    return ScrapeDecision(
        should_scrape=True,
        reason="today is Friday and chart has not been scraped today",
        today=today,
        weekday=weekday,
        last_successful_scrape_date=last_successful_scrape_date,
    )


def empty_database_message() -> str | None:
    if has_any_songs():
        return None
    decision = should_scrape_today(force=False)
    if decision.weekday != "Friday":
        return (
            "SongScout database is empty. Today is not Friday, so automatic scraping is disabled. "
            "Run `run.bat songscout scrape --force` once to initialize manually."
        )
    return None
