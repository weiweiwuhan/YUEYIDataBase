"""Integration checks, isolated data directory; never touches the user's data."""
import tempfile,os,sys,subprocess,time,json,urllib.request,urllib.error,io,zipfile,sqlite3,http.cookiejar
import auth
from pathlib import Path
ROOT=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
    env=dict(os.environ,AOI_DATA=tmp,PORT='18765',DB_ENGINE='sqlite',HOST='0.0.0.0',PYTHONDONTWRITEBYTECODE='1')
    db=sqlite3.connect(Path(tmp)/'aoi.db');db.row_factory=sqlite3.Row
    auth.initialize(db,lambda c,q,args=():c.execute(q,args),False)
    db.execute('INSERT INTO app_users (username,password_hash,role) VALUES (?,?,?)',('admin',auth.password_hash('test-admin-password'),'admin'))
    db.execute('INSERT INTO app_users (username,password_hash,role) VALUES (?,?,?)',('editor',auth.password_hash('test-editor-password'),'editor'));db.commit();db.close()
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    p=subprocess.Popen([sys.executable,str(ROOT/'app.py'),'--no-browser'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def req(path,data=None,raw=None):
        b=raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
        r=opener.open(urllib.request.Request('http://127.0.0.1:18765'+path,data=b,headers={'X-AOI-Client':'local-v1','Content-Type':'application/json'}),timeout=10)
        return json.load(r)
    try:
        for _ in range(100):
            try:s=req('/api/state');break
            except Exception:time.sleep(.05)
        assert len(s['schema'])==23 and all(not x for x in s['data'].values())
        def denied(path,data=None,raw=None):
            try:req(path,data,raw);assert False,'Expected forbidden '+path
            except urllib.error.HTTPError as e:assert e.code==403
        denied('/api/auth/login',{'username':'admin','password':'wrong-password-123'})
        assert s['auth'] is None and 'app_users' not in s['data']
        denied('/api/save',{'table':'materials','record':{'name':'blocked'}})
        denied('/api/upload?name=blocked.png',raw=b'blocked')
        denied('/api/auth/users')
        req('/api/auth/login',{'username':'admin','password':'test-admin-password'})
        req('/api/seed',{});s=req('/api/state');assert len(s['data']['images'])==3
        assert len(s['data']['image_defects'])==1 and len(s['data']['asset_defects'])==3
        req('/api/save',{'table':'process_types','record':{'name':'热处理'}})
        req('/api/save',{'table':'products','id':1,'record':{**s['data']['products'][0],'remark':'后来补充'}})
        assert req('/api/state')['data']['products'][0]['remark']=='后来补充'
        agreement=req('/api/save',{'table':'technical_agreements','record':{'project_id':1,'code':'TA-1','name':'技术协议','requirements':'要求'*400}})['id']
        attachment=req('/api/upload?kind=agreement&agreement_id='+str(agreement)+'&name=spec.pdf',raw=b'%PDF-test-bytes')['asset_id']
        assert opener.open('http://127.0.0.1:18765/api/media?id='+str(attachment)+'&mode=original').read()==b'%PDF-test-bytes'
        assert any(f['asset_id']==attachment for f in req('/api/state')['data']['agreement_files'])
        textfile=req('/api/upload?kind=agreement&agreement_id='+str(agreement)+'&name=agreement.txt',raw='技术协议编号：TA-1\n检测精度：0.01mm'.encode())['asset_id']
        file_id=next(f['id'] for f in req('/api/state')['data']['agreement_files'] if f['asset_id']==textfile)
        previous_files=set(Path(tmp,'uploads').iterdir())
        try:req('/api/upload?kind=agreement&agreement_id=999999&name=bad.pdf',raw=b'bad');assert False
        except urllib.error.HTTPError:pass
        assert previous_files==set(Path(tmp,'uploads').iterdir())
        second=req('/api/save',{'table':'products','record':{'name':'协议第二产品'}})['id']
        for product in (1,second):req('/api/save',{'table':'agreement_products','record':{'agreement_id':agreement,'product_id':product}})
        req('/api/save',{'table':'after_sales','record':{'project_id':1,'product_id':1,'name':'售后经验','status':'已解决','experience':'预防措施'}})
        req('/api/auth/logout',{})
        req('/api/auth/login',{'username':'editor','password':'test-editor-password'})
        req('/api/save',{'table':'materials','record':{'name':'录入员新增'}})
        denied('/api/delete',{'table':'materials','id':1})
        denied('/api/import',{'data':{}})
        denied('/api/seed',{})
        denied('/api/bind',{'remove':True})
        denied('/api/auth/users',{'username':'evil','password':'test-password-123','role':'admin'})
        req('/api/auth/logout',{})
        denied('/api/save',{'table':'materials','record':{'name':'logout'}})
        req('/api/auth/login',{'username':'admin','password':'test-admin-password'})
        disposable=req('/api/save',{'table':'materials','record':{'name':'待删除'}})['id']
        req('/api/delete',{'table':'materials','id':disposable})
        before=req('/api/state')['data']
        try:req('/api/import' ,{'data':{'materials':[{'name':'新材质'}],'image_defects':[{'image_id':999,'defect_type_id':1}]}});assert False
        except urllib.error.HTTPError:pass
        assert req('/api/state')['data']==before,'Failed import must roll back'
        try:req('/api/delete',{'table':'projects','id':1});assert False
        except urllib.error.HTTPError:pass
        try:req('/api/save',{'table':'product_categories','id':1,'record':{'name':'螺栓','parent_id':2}});assert False
        except urllib.error.HTTPError:pass
        z=io.BytesIO()
        with zipfile.ZipFile(z,'w') as a:a.writestr('Src/test.bmp',b'fake-image');a.writestr('readme.txt','test')
        result=req('/api/upload?name=test.zip&project_id=1&product_id=1',raw=z.getvalue());assert result['members']==2
        s=req('/api/state');assert len(s['data']['images'])==4
        newa=next(x for x in s['data']['assets'] if x['file_name']=='test.bmp')
        assert any(x['asset_id']==newa['id'] for x in s['data']['project_assets'])
        # A malformed upload must leave both files and DB unchanged.
        old=req('/api/state')['data'];files=list(Path(tmp,'uploads').iterdir())
        try:req('/api/upload?name=bad.zip',raw=b'not zip');assert False
        except urllib.error.HTTPError:pass
        assert req('/api/state')['data']==old and list(Path(tmp,'uploads').iterdir())==files
        # Real local image decode, thumbnail, full-resolution preview and exact engineering binding.
        from PIL import Image
        png=io.BytesIO();Image.new('RGB',(640,480),(10,80,150)).save(png,format='PNG')
        imageupload=req('/api/upload?name=real.png&image_only=1&project_id=1',raw=png.getvalue())
        estate=req('/api/upload?name=precise.proj&kind=engineering&version=v2',raw=b'engineering version 2')
        current=req('/api/state')['data']
        im=next(x for x in current['images'] if x['asset_id']==imageupload['asset_id'])
        before_asset=next(a for a in current['assets'] if a['id']==im['asset_id'])
        oldpath=Path(tmp,'uploads',before_asset['relative_path']);original_bytes=oldpath.read_bytes()
        req('/api/rename-image',{'image_id':im['id'],'stem':'renamed-image'})
        after_asset=next(a for a in req('/api/state')['data']['assets'] if a['id']==im['asset_id'])
        assert after_asset['file_name']=='renamed-image.png' and not oldpath.exists()
        assert Path(tmp,'uploads',after_asset['relative_path']).read_bytes()==original_bytes
        for badname in ('../escape.png','bad.jpg','CON.png'):
            try:req('/api/rename-image',{'image_id':im['id'],'name':badname});assert False
            except urllib.error.HTTPError:pass
        req('/api/auth/logout',{})
        denied('/api/rename-image',{'image_id':im['id'],'name':'blocked.png'})
        req('/api/auth/login',{'username':'admin','password':'test-admin-password'})
        en=next(x for x in current['engineering_projects'] if x['asset_id']==estate['asset_id'])
        bind_payload={'image_ids':[im['id']],'defect_ids':[1,2,3],'remark':'多缺陷确认'}
        assert req('/api/image-defects',bind_payload)['count']==3
        assert req('/api/image-defects',bind_payload)['count']==0
        multi={'image_ids':[1,im['id']],'defect_ids':[2,3]}
        req('/api/image-defects',multi)
        assert req('/api/image-defects',multi)['count']==0
        bindings=req('/api/state')['data']['image_defects']
        assert all(any(r['image_id']==iid and r['defect_type_id']==did for r in bindings) for iid in multi['image_ids'] for did in multi['defect_ids'])
        before_bind=req('/api/state')['data']['image_defects']
        try:req('/api/image-defects',{'image_ids':[im['id'],999999],'defect_ids':[1]});assert False
        except urllib.error.HTTPError:pass
        assert req('/api/state')['data']['image_defects']==before_bind
        req('/api/auth/logout',{})
        denied('/api/image-defects',bind_payload)
        req('/api/auth/login',{'username':'admin','password':'test-admin-password'})
        assert im['width']==640 and im['height']==480 and im['channels']==3
        req('/api/bind',{'image_id':im['id'],'engineering_id':en['id']})
        req('/api/bind',{'image_id':im['id'],'engineering_id':en['id']})
        rr=req('/api/state')['data']['asset_relations']
        assert sum(x['source_asset_id']==en['asset_id'] and x['target_asset_id']==im['asset_id'] for x in rr)==1
        for mode in ('thumb','view'):
            data=opener.open('http://127.0.0.1:18765/api/media?id='+str(im['asset_id'])+'&mode='+mode).read()
            with Image.open(io.BytesIO(data)) as decoded:
                assert decoded.size==((480,360) if mode=='thumb' else (640,480))
        assert opener.open('http://127.0.0.1:18765/api/media?id='+str(en['asset_id'])+'&mode=original').read()==b'engineering version 2'
        req('/api/bind',{'image_id':im['id'],'engineering_id':en['id'],'remove':True})
        beforebad=req('/api/state')['data']
        try:req('/api/upload?name=bad.png&image_only=1',raw=b'not an image');assert False
        except urllib.error.HTTPError:pass
        assert beforebad==req('/api/state')['data']
        # Products do not need a user-entered code; reusable dictionaries.
        cat=req('/api/save',{'table':'product_categories','record':{'name':'自定义大类'}})['id']
        sub=req('/api/save',{'table':'product_categories','record':{'name':'自定义细类','parent_id':cat}})['id']
        mat=req('/api/save',{'table':'materials','record':{'name':'自定义材质'}})['id']
        product=req('/api/save',{'table':'products','record':{'name':'无编号产品','category_id':sub,'material_id':mat}})['id']
        req('/api/save',{'table':'products','id':product,'record':{'name':'更新无编号产品','category_id':sub,'material_id':mat}})
        local=req('/api/local-engineering',{'name':'本地工程','local_path':r'D:\AOI\客户\project.proj'})['id']
        req('/api/bind',{'image_id':im['id'],'engineering_id':local})
        localrow=next(e for e in req('/api/state')['data']['engineering_projects'] if e['id']==local)
        assert localrow['local_path']==r'D:\AOI\客户\project.proj'
        req('/api/bag-defects',{'asset_id':result['asset_id'],'defect_ids':[1,2,3]})
        req('/api/bag-defects',{'asset_id':result['asset_id'],'defect_ids':[1,2,3]})
        assert len([r for r in req('/api/state')['data']['asset_defects'] if r['asset_id']==result['asset_id']])==3
        video=b'video-transport-test-fixture'
        vid=req('/api/upload?name=sample.mp4&kind=video&image_id='+str(im['id']),raw=video)['id']
        url='http://127.0.0.1:18765/api/video?id='+str(vid)
        assert opener.open(url).read()==video
        response=opener.open(urllib.request.Request(url,headers={'Range':'bytes=2-8'}))
        assert response.status==206 and response.read()==video[2:9]
        response=opener.open(urllib.request.Request(url,headers={'Range':'bytes=-5'}))
        assert response.read()==video[-5:]
        before=req('/api/state')['data'];files=list(Path(tmp,'uploads').iterdir())
        try:req('/api/upload?name=bad.mp4&kind=video&image_id=999999',raw=video);assert False
        except urllib.error.HTTPError:pass
        assert before==req('/api/state')['data'] and files==list(Path(tmp,'uploads').iterdir())
        old=req('/api/state')['data']
        # Full JSON round trip on existing records.
        assert req('/api/import',{'data':old})['count']==sum(map(len,old.values()))
        sql=opener.open('http://127.0.0.1:18765/api/sql?data=1').read().decode()
        assert sql.count('CREATE TABLE IF NOT EXISTS')==23 and 'START TRANSACTION;' in sql
        assert 'CONVERT(X\'' in sql and 'FOREIGN KEY' in sql
        accounts=req('/api/auth/users')
        editor_id=next(u['id'] for u in accounts if u['username']=='editor')
        req('/api/auth/reset-password',{'id':editor_id,'password':'new-editor-password'})
        assert 'password_hash' not in json.dumps(req('/api/state'))
        # Restart uses the same persisted data without reseeding.
        p.terminate();p.wait();p=subprocess.Popen([sys.executable,str(ROOT/'app.py'),'--no-browser'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:after=req('/api/state')['data'];break
            except Exception:time.sleep(.05)
        assert after==old
        db=sqlite3.connect(Path(tmp)/'aoi.db');assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert not db.execute('PRAGMA foreign_key_check').fetchall()
        print('PASS: authentication, guest/editor/admin permissions, agreements, after-sales, 23 tables, seed, CRUD, FK protection, category cycle, transaction rollback, ZIP registration, upload rollback, JSON round trip, SQL export, restart persistence, DB integrity, real image upload, thumbnail, full-resolution preview, engineering binding/download/unbind, invalid-image rollback.')
    finally:p.terminate();p.wait()
