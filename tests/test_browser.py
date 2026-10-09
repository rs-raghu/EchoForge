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


def test_studio_delayed_save_preserves_newer_input(isolated, monkeypatch):
    from fastapi.testclient import TestClient
    from echoforge import studio
    monkeypatch.setattr(studio,'PROJECTS_DIR',isolated/'projects')
    monkeypatch.setattr(studio,'APP_STATE_DIR',isolated/'data')
    client=TestClient(studio.app)
    project=client.post('/api/projects',json={'title':'Fixture','artist':'Singer','sourceUrl':''}).json()
    base='/api/projects/'+project['id']+'/lyrics'
    client.put(base+'?draft=true',json={'lines':[{'id':'l1','index':1,'type':'lyric','text':'Before','timestamp':None}]})
    pending=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True); page=browser.new_page()
        def fulfill(request):
            parsed=urlparse(request.request.url); path=parsed.path+('?' + parsed.query if parsed.query else '')
            if parsed.path=='/' or parsed.path.startswith('/assets/'):
                file=ROOT/'apps/web-studio/frontend/dist'/('index.html' if parsed.path=='/' else parsed.path.lstrip('/'))
                request.fulfill(body=file.read_bytes(),content_type={'.html':'text/html','.js':'application/javascript','.css':'text/css'}[file.suffix])
                return
            response=client.request(request.request.method,path,content=request.request.post_data,
                                    headers={'content-type':'application/json'})
            request.fulfill(status=response.status_code,body=response.content,
                            content_type=response.headers.get('content-type','application/json'))
        def route(request):
            if '/lyrics' in request.request.url and request.request.method=='PUT': pending.append(request)
            else: fulfill(request)
        page.route('**/*',route)
        page.goto('http://fixture.test/')
        page.get_by_role('button',name='Lyrics',exact=True).click()
        field=page.locator('.lyric-lines .lyric-row input').first
        field.wait_for(); page.get_by_label('Auto-save draft').uncheck()
        field.fill('Requested save')
        page.get_by_role('button',name='Save Draft',exact=True).click()
        page.wait_for_timeout(150)
        assert len(pending)==1
        field.fill('Typed while saving')
        fulfill(pending.pop())
        page.wait_for_function('document.querySelector(".save-state").textContent.includes("Unsaved changes")')
        assert field.input_value()=='Typed while saving'
        page.get_by_role('button',name='Save Draft',exact=True).click()
        page.wait_for_timeout(150)
        assert pending[0].request.post_data_json['lines'][0]['text']=='Typed while saving'
        fulfill(pending.pop())
        page.wait_for_function('document.querySelector(".save-state").textContent.includes("Draft saved")')
        assert client.get(base).json()['lines'][0]['text']=='Typed while saving'
        page.get_by_role('button',name='Upload Manager',exact=True).click()
        metadata_save=page.get_by_role('button',name='Save Metadata',exact=True)
        metadata_save.wait_for()
        for _ in range(2):
            with page.expect_response(lambda response:'/upload/metadata' in response.url and response.request.method=='PUT'):
                metadata_save.click()
            page.wait_for_function('document.querySelector(".mutation-lock").disabled === false')
            assert metadata_save.is_enabled()
        browser.close()
