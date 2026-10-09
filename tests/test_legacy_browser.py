import mimetypes
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def test_legacy_first_shift_click_is_safe():
    saved=[]
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
            if path.endswith('/editor') and request.request.method=='POST':
                saved.append(request.request.post_data_json['project'])
                request.fulfill(json={'ok':True});return
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
        audio_row=page.locator('.trackRow').filter(has=page.locator('.trackLabelName',has_text='Audio'))
        audio_row.get_by_title('Mute track',exact=True).click()
        audio_row.get_by_title('Solo track',exact=True).click()
        page.get_by_title('Ctrl+S',exact=True).click()
        page.wait_for_function('document.body.textContent.includes("Saved")')
        assert saved[-1]['tracks'][-1]['muted'] is True
        assert saved[-1]['tracks'][-1]['solo'] is True
        assert not page.locator('.previewLyric').count()
        # Reopening the persisted project restores the controls.
        project=saved[-1]
        page.locator('.brand').click()
        page.get_by_role('button',name='Open',exact=True).click()
        assert 'trackActive' in audio_row.get_by_title('Mute track',exact=True).get_attribute('class')
        assert 'trackActive' in audio_row.get_by_title('Solo track',exact=True).get_attribute('class')
        assert not errors
        browser.close()
