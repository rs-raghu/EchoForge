from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from echoforge.core.config import settings
from echoforge.core.paths import SONGSCOUT_DATA_DIR
from echoforge.core.storage import atomic_json

RAW_DATA_PATH = SONGSCOUT_DATA_DIR / "youtube_charts_raw.json"
DEBUG_HTML_PATH = SONGSCOUT_DATA_DIR / "debug_latest_page.html"
DEBUG_TEXT_PATH = SONGSCOUT_DATA_DIR / "debug_latest_text.txt"
DEBUG_SCREENSHOT_PATH = SONGSCOUT_DATA_DIR / "debug_latest_page.png"

_CONSENT_RE = re.compile(r"Accept all|I agree|Agree|Accept|Reject all|No thanks", re.I)


class ChartScrapeError(ValueError):
    """Expected chart load failure, safe for the CLI to display without a traceback."""


def _chart_request(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname == 'charts.youtube.com' and parsed.path in {
        '/youtubei/v1/browse', '/youtubei/v1/music/get_charts'}


def _check_chart_failure(failures: list[dict[str, Any]]) -> None:
    if not failures: return
    failure = failures[-1]
    status = failure.get('status')
    if status == 429:
        retry = failure.get('retry_after')
        hint = f' Retry-After: {retry}.' if retry else ''
        raise ChartScrapeError(
            'YouTube Charts rate-limited its chart-data request (HTTP 429). '
            'No songs were received; the previous chart is preserved. '
            'Wait before retrying and check the chart in your regular browser.' + hint)
    if status:
        raise ChartScrapeError(f'YouTube Charts chart-data request failed (HTTP {status}). '
                              'The previous chart is preserved; retry after the service recovers.')
    raise ChartScrapeError('YouTube Charts chart-data request could not connect. '
                          'Check your connection; the previous chart is preserved.')


def _wait_for_chart_rows(page, failures, timeout_ms):
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        rows = page.evaluate(EXTRACT_CHART_ROWS_JS)
        if rows: return rows
        _check_chart_failure(failures)
        if time.monotonic() >= deadline:
            raise ChartScrapeError('YouTube Charts loaded without readable song rows. '
                                  'The page may be blank, require consent, or have changed its layout. '
                                  'Check it in your browser or retry with --show-browser. '
                                  'The previous chart is preserved.')
        page.wait_for_timeout(min(500, max(1, int((deadline - time.monotonic()) * 1000))))

EXTRACT_CHART_ROWS_JS = r"""
() => {
  const textCache = new WeakMap();
  const visCache = new WeakMap();
  const childrenCache = new WeakMap();

  function getChildren(el) {
    if (!childrenCache.has(el)) {
      const out = [];
      const walk = (node) => {
        if (node && node.nodeType === Node.ELEMENT_NODE) {
          out.push(node);
          if (node.shadowRoot) walk(node.shadowRoot);
        }
        const children = node.children || [];
        for (const child of children) walk(child);
      };
      walk(el);
      childrenCache.set(el, out);
    }
    return childrenCache.get(el);
  }

  function getText(el) {
    if (!textCache.has(el)) {
      const raw = el.innerText || el.textContent || "";
      textCache.set(el, raw.replace(/\u00a0/g, " ").replace(/[ \t]+/g, " ").trim());
    }
    return textCache.get(el);
  }

  function getLines(el) {
    return getText(el).split(/\n+/).map((x) => x.trim()).filter(Boolean);
  }

  function isVisible(el) {
    if (!visCache.has(el)) {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      visCache.set(el, rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none");
    }
    return visCache.get(el);
  }

  function safeAttr(el, name) {
    return el.getAttribute ? el.getAttribute(name) || "" : "";
  }

  function meta(el) {
    return [safeAttr(el, "id"), safeAttr(el, "class"), safeAttr(el, "aria-label"), safeAttr(el, "title"), safeAttr(el, "data-rank"), el.tagName || ""].join(" ").toLowerCase();
  }

  function firstMeaningfulText(nodes, terms) {
    for (const n of nodes) {
      const m = meta(n);
      if (!terms.some((t) => m.includes(t))) continue;
      const t = getText(n) || safeAttr(n, "aria-label") || safeAttr(n, "title");
      if (t && t.length <= 140) return t;
    }
    return "";
  }

  function firstLink(nodes) {
    for (const n of nodes) {
      const ep = safeAttr(n, "endpoint");
      if (ep) {
        try {
          const parsed = JSON.parse(ep);
          const rawUrl = parsed?.urlEndpoint?.url || parsed?.watchEndpoint?.videoId;
          if (rawUrl) {
            if (rawUrl.startsWith("http")) return rawUrl;
            if (rawUrl.startsWith("/")) return new URL(rawUrl, location.href).href;
            return `https://www.youtube.com/watch?v=${rawUrl}`;
          }
        } catch {}
      }

      if ((n.tagName || "").toLowerCase() === "a") {
        const href = safeAttr(n, "href");
        if (href && (href.includes("watch") || href.includes("youtu.be"))) {
          try { return new URL(href, location.href).href; } catch { return href; }
        }
      }
    }
    return "";
  }

  function firstImage(nodes) {
    for (const img of nodes) {
      if ((img.tagName || "").toLowerCase() !== "img") continue;
      const src = img.currentSrc || safeAttr(img, "src") || safeAttr(img, "data-src");
      if (src && !src.startsWith("data:")) return src;
    }
    return "";
  }

  const all = getChildren(document);
  const selectorCandidates = [];
  const selectors = [
    "ytmc-entry-row",
    "ytmc-chart-table-entry",
    "ytmc-chart-entry",
    "ytmusic-responsive-list-item-renderer",
    "[role='row']",
    "[data-rank]",
    "[class*='entry-row']",
    "[class*='chart-row']",
    "[class*='song-row']",
    "[class*='table-row']",
  ];

  const searchRoots = [document, ...all.filter((e) => e.shadowRoot).map((e) => e.shadowRoot)];
  for (const sel of selectors) {
    for (const root of searchRoots) {
      try { selectorCandidates.push(...root.querySelectorAll(sel)); } catch {}
    }
  }

  const textCandidates = all.filter((el) => {
    if (!isVisible(el)) return false;
    const lines = getLines(el);
    if (lines.length < 4 || lines.length > 24) return false;
    const txt = getText(el);
    const firstLineRank = /^#?\d{1,3}$/.test(lines[0]);
    const hasChartWords = /last week|weeks on chart|weekly views|views|release date/i.test(txt);
    if (!firstLineRank && !hasChartWords) return false;
    const rect = el.getBoundingClientRect();
    if (rect.height >= 380) return false;
    const children = getChildren(el);
    return children.some((n) => (n.tagName || "").toLowerCase() === "img");
  });

  const candidates = [...selectorCandidates, ...textCandidates];
  const seen = new Set();
  const rows = [];

  for (const el of candidates) {
    if (!el || seen.has(el)) continue;
    seen.add(el);
    if (!isVisible(el)) continue;

    const lines = getLines(el);
    if (lines.length < 3) continue;

    const rowText = getText(el);
    if (rowText.length > 1500) continue;

    const rowMeta = meta(el);
    const likelyRow = /^#?\d{1,3}$/.test(lines[0]) || /rank|chart|entry|song|track|row/.test(rowMeta) || /last week|weeks on chart|weekly views|release date/i.test(rowText);
    if (!likelyRow) continue;

    const children = getChildren(el);
    const rankAttr = safeAttr(el, "data-rank") || safeAttr(el, "aria-posinset") || "";

    rows.push({
      rank_attr: rankAttr,
      title_hint: firstMeaningfulText(children, ["title", "song-title", "track-title", "name"]),
      artist_hint: firstMeaningfulText(children, ["artist", "subtitle", "byline", "channel"]),
      thumbnail_url: firstImage(children),
      video_url: firstLink(children),
      lines,
      text: rowText,
    });
  }

  const compact = [];
  const rowKeys = new Set();
  for (const row of rows) {
    const key = `${row.rank_attr}|${row.lines.slice(0, 8).join("|")}`;
    if (rowKeys.has(key)) continue;
    rowKeys.add(key);
    compact.push(row);
  }

  return compact;
}
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dismiss_consent(page) -> None:
    try:
        page.get_by_role("button", name=_CONSENT_RE).first.click(timeout=2000)
        page.wait_for_timeout(1000)
    except Exception:
        pass


def _save_debug_files(page) -> None:
    SONGSCOUT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DEBUG_HTML_PATH.write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        DEBUG_TEXT_PATH.write_text(page.locator("body").inner_text(timeout=3000), encoding="utf-8")
    except Exception:
        pass
    try:
        page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
    except Exception:
        pass


def delete_transient_debug_files() -> None:
    for path in (DEBUG_HTML_PATH, DEBUG_TEXT_PATH, DEBUG_SCREENSHOT_PATH):
        path.unlink(missing_ok=True)


def scrape_youtube_charts(
    *,
    url: str | None = None,
    max_songs: int | None = None,
    headless: bool = True,
    raw_output_path: Path = RAW_DATA_PATH,
    load_timeout_ms: int = 30_000,
) -> list[dict[str, Any]]:
    url = url or settings.youtube_charts_url
    max_songs = settings.max_songs if max_songs is None else max_songs
    if not isinstance(max_songs, int) or not 1 <= max_songs <= 500:
        raise ValueError('max_songs must be between 1 and 500')
    if not isinstance(load_timeout_ms, int) or not 1 <= load_timeout_ms <= 60_000:
        raise ValueError('load_timeout_ms must be between 1 and 60000')
    from echoforge.stages.songscout.cleaner import clean_row, clean_rows

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            locale="en-US",
        )
        page = context.new_page()
        failures: list[dict[str, Any]] = []

        def chart_response(response):
            if _chart_request(response.url) and response.status >= 400:
                failures.append({'status': response.status,
                                 'retry_after': response.headers.get('retry-after')})

        def chart_request_failed(request):
            if _chart_request(request.url): failures.append({'status': None})

        page.on('response', chart_response)
        page.on('requestfailed', chart_request_failed)

        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            if response and response.status >= 400:
                _check_chart_failure([{'status': response.status, 'retry_after': response.headers.get('retry-after')}])
            _dismiss_consent(page)
            raw_rows = _wait_for_chart_rows(page, failures, load_timeout_ms)

            last_height = 0
            stable_rounds = 0
            for _ in range(14):
                if len(clean_rows(raw_rows)) >= max_songs: break
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(900)
                _check_chart_failure(failures)
                more_rows = page.evaluate(EXTRACT_CHART_ROWS_JS)
                # Retain earlier rows if the site virtualizes its list while scrolling.
                known = {json.dumps(row, sort_keys=True) for row in raw_rows}
                raw_rows.extend(row for row in more_rows if json.dumps(row, sort_keys=True) not in known)
                height = page.evaluate("document.body.scrollHeight")
                if height == last_height:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                last_height = height
                if stable_rounds >= 3:
                    break

            _check_chart_failure(failures)
            valid_rows = []
            seen_songs = set()
            for index, row in enumerate(raw_rows, start=1):
                song = clean_row(row, fallback_rank=index)
                if song and song['id'] not in seen_songs:
                    seen_songs.add(song['id'])
                    valid_rows.append((song.get('rank') or index, row))
            valid_rows.sort(key=lambda item: item[0])
            raw_rows = [row for _, row in valid_rows[:max_songs]]
            if not raw_rows:
                raise ChartScrapeError('YouTube Charts rows could not be parsed into song titles and artists. '
                                      'The chart layout may have changed; the previous chart is preserved.')
        except PlaywrightTimeoutError as exc:
            raise ChartScrapeError('YouTube Charts page timed out while loading. '
                                  'Check your connection; the previous chart is preserved.') from exc
        finally:
            _save_debug_files(page)
            browser.close()

    payload = {
        "source_url": url,
        "scraped_at": _now_iso(),
        "row_count": len(raw_rows),
        "rows": raw_rows[:max_songs],
    }

    atomic_json(raw_output_path, payload)
    return payload["rows"]
