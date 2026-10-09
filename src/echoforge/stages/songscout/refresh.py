from __future__ import annotations

from datetime import datetime
from echoforge.core.paths import SONGSCOUT_DATA_DIR
from echoforge.core.storage import file_lock
from echoforge.stages.songscout.cleaner import clean_rows
from echoforge.stages.songscout.database import init_database, record_scrape_result, upsert_songs
from echoforge.stages.songscout.policy import should_scrape_today, current_window_start
from echoforge.stages.songscout.scraper import scrape_youtube_charts, delete_transient_debug_files


def refresh_chart(*, force=False, max_songs=100, show_browser=False, country=None):
    if not 1 <= max_songs <= 500:
        raise ValueError("max_songs must be between 1 and 500")
    with file_lock(SONGSCOUT_DATA_DIR / "refresh.lock", timeout=600):
        init_database()
        decision = should_scrape_today(force=force)
        if country:
            from echoforge.stages.songscout.database import get_metadata
            if get_metadata('last_chart_country') not in {None, country}:
                force=True
                decision=should_scrape_today(force=True)
        if not decision.should_scrape:
            return {"ok": True, "scraped": False, "reason": decision.reason}
        try:
            kwargs={'max_songs':max_songs, 'headless':not show_browser}
            if country: kwargs['url']=f'https://charts.youtube.com/charts/TopSongs/{country}/weekly'
            rows = scrape_youtube_charts(**kwargs)
            songs = clean_rows(rows)
            if not songs:
                raise ValueError("Chart returned no valid songs; previous chart and refresh eligibility preserved")
            result = upsert_songs(songs)
            if country:
                from echoforge.stages.songscout.database import set_metadata
                set_metadata("last_chart_country",country)
            record_scrape_result(success=True, row_count=len(rows), clean_count=len(songs),
                                 reason=decision.reason, local_date=decision.today,
                                 window=current_window_start(datetime.fromisoformat(decision.today)))
        except Exception as exc:
            record_scrape_result(success=False, reason=str(exc))
            raise
        delete_transient_debug_files()
        return {"ok": True, "scraped": True, "raw_rows": len(rows), "clean_songs": len(songs), **result}
