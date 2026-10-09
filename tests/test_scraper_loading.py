"""Public-page fixtures: never contact YouTube or change the real song database."""
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from playwright.sync_api import sync_playwright

from echoforge.stages.songscout import scraper, database, refresh
from echoforge.core.storage import atomic_json, read_json


@pytest.fixture
def chart_browser(tmp_path, monkeypatch):
    """Intercept every request in the scraper's actual Chromium context."""
    chart_url = 'https://charts.youtube.com/charts/TopSongs/global/weekly'
    fixture = {'html': '', 'status': 200, 'response_headers': {}, 'requests': []}
    @contextmanager
    def patched_playwright():
        with sync_playwright() as pw:
            class Chromium:
                def launch(self, **kwargs):
                    browser = pw.chromium.launch(**kwargs)
                    original_context = browser.new_context
                    def new_context(**options):
                        context = original_context(**options)
                        def route(request):
                            fixture['requests'].append(request.request.url)
                            if request.request.url == chart_url:
                                request.fulfill(body=fixture['html'], content_type='text/html')
                            elif '/youtubei/v1/browse' in request.request.url:
                                request.fulfill(status=fixture['status'], headers=fixture['response_headers'],
                                    json={'error': {'code': fixture['status']}})
                            else: request.fulfill(status=404, body='')
                        context.route('**/*', route)
                        return context
                    browser.new_context = new_context
                    return browser
            yield type('Playwright', (), {'chromium': Chromium()})()
    monkeypatch.setattr(scraper, 'sync_playwright', patched_playwright)
    monkeypatch.setattr(scraper, '_dismiss_consent', lambda page: None)
    monkeypatch.setattr(scraper, '_save_debug_files', lambda page: None)
    fixture['url'] = chart_url
    fixture['raw'] = tmp_path/'chart_raw.json'
    return fixture


@pytest.mark.parametrize('status',[429,503])
def test_chart_data_failure_is_explained_and_preserves_previous_raw(chart_browser,status):
    fixture=chart_browser
    fixture.update(status=status,response_headers={'retry-after':'120'},html='''
        <script>fetch('/youtubei/v1/browse',{method:'POST'});</script>''')
    atomic_json(fixture['raw'], {'rows': ['PREVIOUS VALID CHART']})
    with pytest.raises(scraper.ChartScrapeError,match=f'HTTP {status}') as error:
        scraper.scrape_youtube_charts(url=fixture['url'],max_songs=1,
                                    raw_output_path=fixture['raw'],load_timeout_ms=2000)
    assert read_json(fixture['raw'])=={'rows':['PREVIOUS VALID CHART']}
    if status==429: assert 'Retry-After: 120' in str(error.value)
    assert sum('/youtubei/v1/browse' in url for url in fixture['requests'])==1


def test_delayed_chart_rows_are_waited_for_and_cleaned(chart_browser):
    fixture=chart_browser
    fixture['html']='''<script>setTimeout(()=>{
      document.body.innerHTML='<div role="row" data-rank="1">1<br><span class="song-title">Delayed Song</span><br><span class="artist">Singer</span></div>';
    },800)</script>'''
    rows=scraper.scrape_youtube_charts(url=fixture['url'],max_songs=1,
                                     raw_output_path=fixture['raw'],load_timeout_ms=3000)
    from echoforge.stages.songscout.cleaner import clean_rows
    assert clean_rows(rows)[0]['title']=='Delayed Song'
    assert read_json(fixture['raw'])['row_count']==1


def test_blank_page_fails_without_creating_empty_raw_chart(chart_browser):
    fixture=chart_browser
    with pytest.raises(scraper.ChartScrapeError,match='without readable song rows'):
        scraper.scrape_youtube_charts(url=fixture['url'],raw_output_path=fixture['raw'],load_timeout_ms=200)
    assert not fixture['raw'].exists()


def test_invalid_candidates_do_not_consume_requested_song_limit(chart_browser):
    fixture=chart_browser
    fixture['html']='''<div role="row" data-rank="1">1<br>Weekly views<br>20M views</div>
        <div role="row" data-rank="2">2<br><span class="song-title">Valid Song</span><br><span class="artist">Singer</span></div>'''
    rows=scraper.scrape_youtube_charts(url=fixture['url'],max_songs=1,
                                     raw_output_path=fixture['raw'],load_timeout_ms=1000)
    from echoforge.stages.songscout.cleaner import clean_rows
    assert clean_rows(rows)[0]['title']=='Valid Song'
    assert len(rows)==1


def test_unparseable_rows_preserve_previous_raw(chart_browser):
    fixture=chart_browser
    fixture['html']='<div role="row" data-rank="1">1<br>Weekly views<br>20M views</div>'
    atomic_json(fixture['raw'], {'rows': ['PREVIOUS']})
    with pytest.raises(scraper.ChartScrapeError,match='could not be parsed'):
        scraper.scrape_youtube_charts(url=fixture['url'],max_songs=1,raw_output_path=fixture['raw'],load_timeout_ms=1000)
    assert read_json(fixture['raw'])=={'rows':['PREVIOUS']}


def test_refresh_rate_limit_preserves_snapshot_and_retry_eligibility(isolated,monkeypatch):
    from echoforge.stages.songscout.policy import should_scrape_today
    database.upsert_songs([{'id':'old','rank':1,'title':'Old chart song','artist':'Singer'}],chart_snapshot=True)
    fetch=Mock(side_effect=scraper.ChartScrapeError('YouTube Charts rate-limited its chart-data request (HTTP 429).'))
    monkeypatch.setattr(refresh,'scrape_youtube_charts',fetch)
    with pytest.raises(scraper.ChartScrapeError,match='429'): refresh.refresh_chart()
    assert database.get_next_available_song()['id']=='old'
    assert should_scrape_today().should_scrape
    assert database.get_metadata('last_scrape_status')=='failed'


def test_cli_chart_failure_exits_without_traceback(monkeypatch,capsys):
    import sys
    from echoforge import cli
    monkeypatch.setattr(cli,'run_songscout_refresh',Mock(side_effect=scraper.ChartScrapeError('HTTP 429: wait before retrying')))
    monkeypatch.setattr(sys,'argv',['echoforge','songscout','scrape'])
    with pytest.raises(SystemExit) as error: cli.main()
    assert error.value.code==1
    stderr=capsys.readouterr().err
    assert 'SongScout: HTTP 429' in stderr
    assert 'Traceback' not in stderr


def test_scraper_chart_failure_classifier_ignores_analytics():
    assert not scraper._chart_request('https://charts.youtube.com/youtubei/v1/log_event')
    assert not scraper._chart_request('https://another.example/youtubei/v1/browse')
    assert scraper._chart_request('https://charts.youtube.com/youtubei/v1/browse?alt=json')


def test_virtualized_rows_are_retained(tmp_path,monkeypatch):
    """The final viewport must not replace songs collected from earlier viewports."""
    first={'rank_attr':'1','lines':['1','First','Singer']}
    second={'rank_attr':'2','lines':['2','Second','Second Singer']}
    page=Mock()
    rows=iter([[first],[second]])
    def evaluate(js):
        if js==scraper.EXTRACT_CHART_ROWS_JS: return next(rows)
        return 1000
    page.evaluate.side_effect=evaluate
    page.goto.return_value=Mock(status=200)
    browser=Mock(); browser.new_context.return_value.new_page.return_value=page
    pw=Mock(); pw.chromium.launch.return_value=browser
    @contextmanager
    def fixture_playwright(): yield pw
    monkeypatch.setattr(scraper,'sync_playwright',fixture_playwright)
    monkeypatch.setattr(scraper,'_dismiss_consent',lambda page:None)
    monkeypatch.setattr(scraper,'_save_debug_files',lambda page:None)
    assert scraper.scrape_youtube_charts(max_songs=2,raw_output_path=tmp_path/'rows.json')==[first,second]
