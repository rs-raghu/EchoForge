import mimetypes
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def test_legacy_first_shift_click_is_safe():
    project={'projectId':'fixture','width':320,'height':240,'duration':30,'fps':24,'assets':{},
             'styleDefaultsAppliedVersion':3,'tracks':[
             {'id':'background','name':'Background','type':'background','clips':[]},
             {'id':'lyrics','name':'Lyrics','type':'lyrics','clips':[
                 {'id':'l1','type':'lyric','start':0,'end':10,'text':'One','x':160,'y':120,'fontSize':20,'opacity':100},
                 {'id':'l2','type':'lyric','start':10,'end':20,'text':'Two','x':160,'y':120,'fontSize':20,'opacity':100}]},
             {'id':'audio','name':'Audio','type':'audio','clips':[]}]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1600,'height':1000});page.set_default_timeout(5000);errors=[]
        page.on('pageerror', lambda error:errors.append(str(error)))
        def route(request):
            path=urlparse(request.request.url).path
            if path=='/api/health': request.fulfill(json={'ffmpeg':True,'ffprobe':True,'projectsRoot':'fixture'});return
            if path=='/api/projects': request.fulfill(json={'projects':[{'id':'fixture','hasLyrics':True,'hasEditorProject':True}]});return
            if path.endswith('/bootstrap'): request.fulfill(json={'project':project});return
            file=ROOT/'apps/webeditor_legacy/frontend/dist'/('index.html' if path=='/' else path.lstrip('/'))
            if file.is_file(): request.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(file)[0] or 'application/octet-stream')
            else: request.fulfill(status=404,body='')
        page.route('**/*',route);page.goto('http://fixture.test/')
        page.get_by_role('button',name='Open',exact=True).click()
        page.locator('.trackArea .clip').first.click(modifiers=['Shift'])
        assert not errors
        page.locator('.trackArea .clip').nth(1).click(modifiers=['Shift'])
        assert page.locator('.selectionBadge').inner_text().startswith('2 clips')
        assert not errors
        browser.close()
