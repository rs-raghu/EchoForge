from pathlib import Path
from urllib.parse import urlparse
import pytest
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('save_fails',[True,False])
def test_editor_save_and_upload_metadata_contract(save_fails):
    captured=[]
    project={'schema':'echoforge.webeditor.v2','project':{'title':'Fixture','artist':'Singer','duration':1},
             'canvas':{'width':320,'height':240},'assets':{},'tracks':[{'id':'track_lyrics','name':'Lyrics','type':'text',
             'clips':[{'id':'lyric1','type':'text','text':'Fixture','start':0,'end':1,'x':160,'y':120,'style':{'fontFamily':'Arial','fontSize':30}}]}]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(timezone_id='Asia/Kolkata')
        page.on('dialog',lambda dialog:dialog.accept())
        def route(request):
            path=urlparse(request.request.url).path
            if path in {'/','/app.js','/style.css'}:
                file=ROOT/'apps/webeditor'/('index.html' if path=='/' else path[1:])
                request.fulfill(body=file.read_text(encoding='utf-8'),content_type={'/':'text/html','/app.js':'application/javascript','/style.css':'text/css'}[path]); return
            if path=='/api/project':
                if request.request.method=='GET': data=project
                else:
                    request.fulfill(status=500 if save_fails else 200,json={'ok':not save_fails,'error':'Fixture save failed','revision':1}); return
            elif path=='/api/youtube-metadata': data={'ok':True,'metadata':{'title':'Generated title','description':'Generated','tags':['generated']}}
            elif path=='/api/render-upload/start':
                captured.append(request.request.post_data_json); data={'ok':True,'job_id':'fixture'}
            elif path.startswith('/api/render'): data={'ok':True,'running':False,'stage':'completed','progress':100}
            else: request.fulfill(status=404,body=''); return
            request.fulfill(json=data)
        page.route('**/*',route)
        page.goto('http://fixture.test/')
        page.wait_for_function('typeof window.saveProject === "function"')
        page.locator('#efRenderUploadBtn').click()
        page.locator('.efru-modal [data-title]').fill('APPROVED CUSTOM TITLE')
        page.locator('.efru-modal [data-description]').fill('Approved description')
        page.locator('.efru-modal [data-tags]').fill('one, two')
        page.locator('.efru-modal [data-visibility]').select_option('public')
        page.locator('.efru-modal [data-render-upload]').click()
        if save_fails:
            page.wait_for_function('document.querySelector(".efru-modal [data-status]").textContent.includes("Start failed")')
            assert not captured
        else:
            page.wait_for_function('document.querySelector(".efru-modal [data-status]").textContent.includes("Job started")')
            assert len(captured)==1
            assert captured[0]['visibility']=='public'
            assert captured[0]['metadata']['title']=='APPROVED CUSTOM TITLE'
            assert captured[0]['metadata']['tags']==['one','two']
        browser.close()
