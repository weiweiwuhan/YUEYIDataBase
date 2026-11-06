"""Integration checks, isolated data directory; never touches the user's data."""
import tempfile,os,sys,subprocess,time,json,urllib.request,urllib.error,io,zipfile,sqlite3,http.cookiejar
import auth
from urllib.parse import urlencode
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
        assert len(s['schema'])==25 and all(not x for x in s['data'].values())
        def denied(path,data=None,raw=None):
            try:req(path,data,raw);assert False,'Expected forbidden '+path
            except urllib.error.HTTPError as e:assert e.code==403
        denied('/api/auth/login',{'username':'admin','password':'wrong-password-123'})
        assert s['auth'] is None and 'app_users' not in s['data']
        denied('/api/save',{'table':'materials','record':{'name':'blocked'}})
        denied('/api/upload?name=blocked.png',raw=b'blocked')
        denied('/api/auth/users')
        denied('/api/sql')
        denied('/api/audit')
        denied('/api/auth/users-batch',{'count':50})
        req('/api/auth/login',{'username':'admin','password':'test-admin-password'})
        req('/api/seed',{});s=req('/api/state');assert len(s['data']['images'])==3
        assert len(s['data']['image_defects'])==1 and len(s['data']['asset_defects'])==3
        req('/api/save',{'table':'process_types','record':{'name':'热处理'}})
        req('/api/save',{'table':'products','id':1,'record':{**s['data']['products'][0],'remark':'后来补充'}})
        assert req('/api/state')['data']['products'][0]['remark']=='后来补充'
        # Creating agreement metadata and its first attachment is atomic.
        agreement_record={'project_id':1,'code':'TA-UPLOAD','name':'新增即上传协议'}
        q=urlencode({'kind':'agreement_new','name':'agreement.pdf','record':json.dumps(agreement_record)})
        combined=req('/api/upload?'+q,raw=b'%PDF-backup-only')
        combined_state=req('/api/state')['data']
        assert any(a['id']==combined['agreement_id'] and a['code']=='TA-UPLOAD' for a in combined_state['technical_agreements'])
        assert any(f['agreement_id']==combined['agreement_id'] and f['asset_id']==combined['asset_id'] for f in combined_state['agreement_files'])
        assert opener.open('http://127.0.0.1:18765/api/media?id='+str(combined['asset_id'])+'&mode=original').read()==b'%PDF-backup-only'
        before_combined=req('/api/state')['data'];before_disk=set(Path(tmp,'uploads').iterdir())
        bad_q=urlencode({'kind':'agreement_new','name':'invalid.pdf','record':json.dumps({**agreement_record,'project_id':999999,'code':'INVALID'})})
        try:req('/api/upload?'+bad_q,raw=b'bad');assert False
        except urllib.error.HTTPError:pass
        assert req('/api/state')['data']==before_combined and set(Path(tmp,'uploads').iterdir())==before_disk
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
        author_row=req('/api/save',{'table':'materials','record':{'name':'录入员新增','created_by':'fake-admin','created_at':'fake-time'}})['id']
        stamped=next(r for r in req('/api/state')['data']['materials'] if r['id']==author_row)
        assert stamped['created_by']=='editor' and stamped['created_at']!='fake-time'
        assert stamped['updated_by']=='editor'
        try:req('/api/save',{'table':'materials','id':author_row,'record':{'name':'would-overwrite'},'expected_updated_at':'outdated'});assert False
        except urllib.error.HTTPError as e:assert e.code==409
        assert next(r for r in req('/api/state')['data']['materials'] if r['id']==author_row)['name']=='录入员新增'
        page=req('/api/records?table=materials&page=1&page_size=1')
        assert len(page['data'])==1 and page['total']>0
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
        assert any(event['actor']=='editor' for event in req('/api/audit'))
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
        # Model test records store original/effect images without inflating production image totals.
        test_id=req('/api/save',{'table':'model_tests','record':{'name':'缺陷识别测试','model_name':'model-A','model_version':'v1','result':'效果好','product_id':1,'test_count':200,'detection_rate':98.5,'yield_rate':96.5,'miss_rate':1.5,'prompt':'Windows + GPU','light_source':'红色环形光','camera':'CCD-5MP','lens':'25mm定焦','working_distance_mm':120.5,'product_spec':'M6×20 / 碳钢','remark':'效果图人工复核'}})['id']
        test_record=next(r for r in req('/api/state')['data']['model_tests'] if r['id']==test_id)
        assert test_record['product_id']==1 and test_record['test_count']==200 and test_record['detection_rate']==98.5
        assert test_record['working_distance_mm']==120.5 and test_record['product_spec']=='M6×20 / 碳钢' and test_record['camera']=='CCD-5MP'
        for changes in ({'working_distance_mm':-1},{'working_distance_mm':'nan'},{'test_count':-1},{'test_count':1.5},{'detection_rate':101},{'yield_rate':-1},{'yield_rate':100.1},{'product_id':999999}):
            try:req('/api/save',{'table':'model_tests','id':test_id,'record':{**test_record,**changes}});assert False
            except urllib.error.HTTPError:pass
        edit_record={k:v for k,v in test_record.items() if k not in ('project_id','result','miss_rate')}
        edit_record.update(test_count=0,detection_rate=0,yield_rate=100,working_distance_mm=0,camera='CCD-12MP')
        req('/api/save',{'table':'model_tests','id':test_id,'record':edit_record})
        updated=next(r for r in req('/api/state')['data']['model_tests'] if r['id']==test_id)
        assert updated['working_distance_mm']==0 and updated['camera']=='CCD-12MP' and updated['light_source']=='红色环形光'
        assert updated['test_count']==0 and updated['detection_rate']==0 and updated['yield_rate']==100 and updated['miss_rate']==1.5 and updated['result']=='效果好'
        from PIL import Image
        test_png=io.BytesIO();Image.new('RGB',(32,24),(25,80,150)).save(test_png,format='PNG')
        production_count=len(req('/api/state')['data']['images'])
        for role in ('input','result'):
            test_asset=req('/api/upload?kind=modeltest&test_id='+str(test_id)+'&role='+role+'&name=test.png',raw=test_png.getvalue())['asset_id']
            assert opener.open('http://127.0.0.1:18765/api/media?id='+str(test_asset)+'&mode=original').read()==test_png.getvalue()
        model_state=req('/api/state')['data']
        assert len(model_state['images'])==production_count
        assert len([f for f in model_state['model_test_files'] if f['test_id']==test_id])==2
        test_file=next(f for f in model_state['model_test_files'] if f['test_id']==test_id)
        old_asset=next(a for a in model_state['assets'] if a['id']==test_file['asset_id'])
        old_test_path=Path(tmp,'uploads',old_asset['relative_path'])
        for badstem in ('../bad','CON','bad/name'):
            try:req('/api/model-test-file-rename',{'file_id':test_file['id'],'stem':badstem});assert False
            except urllib.error.HTTPError:pass
        assert old_test_path.exists()
        before_files=set(Path(tmp,'uploads').iterdir())
        try:req('/api/upload?kind=modeltest&test_id='+str(test_id)+'&role=result&name=invalid.png',raw=b'invalid');assert False
        except urllib.error.HTTPError:pass
        assert before_files==set(Path(tmp,'uploads').iterdir())
        req('/api/auth/logout',{})
        denied('/api/model-test-file-rename',{'file_id':test_file['id'],'stem':'blocked'})
        denied('/api/model-test-file-delete',{'file_id':test_file['id']})
        denied('/api/upload?kind=modeltest&test_id='+str(test_id)+'&role=result&name=blocked.png',raw=test_png.getvalue())
        req('/api/auth/login',{'username':'editor','password':'test-editor-password'})
        denied('/api/model-test-delete',{'id':test_id})
        denied('/api/model-test-file-delete',{'file_id':test_file['id']})
        req('/api/model-test-file-rename',{'file_id':test_file['id'],'stem':'测试重命名'})
        renamed_asset=next(a for a in req('/api/state')['data']['assets'] if a['id']==test_file['asset_id'])
        assert renamed_asset['file_name']=='测试重命名.png' and not old_test_path.exists()
        renamed_test_path=Path(tmp,'uploads',renamed_asset['relative_path'])
        assert renamed_test_path.read_bytes()==test_png.getvalue()
        assert opener.open('http://127.0.0.1:18765/api/media?id='+str(test_file['asset_id'])+'&mode=view').status==200
        req('/api/auth/logout',{})
        req('/api/auth/login',{'username':'admin','password':'test-admin-password'})
        # A referenced file must restore its disk path and association on transaction failure.
        protected_link=req('/api/save',{'table':'asset_products','record':{'asset_id':test_file['asset_id'],'product_id':1}})['id']
        try:req('/api/model-test-file-delete',{'file_id':test_file['id']});assert False
        except urllib.error.HTTPError:pass
        assert renamed_test_path.exists()
        assert any(f['id']==test_file['id'] for f in req('/api/state')['data']['model_test_files'])
        req('/api/delete',{'table':'asset_products','id':protected_link})
        req('/api/model-test-file-delete',{'file_id':test_file['id']})
        after_delete=req('/api/state')['data']
        assert not any(f['id']==test_file['id'] for f in after_delete['model_test_files'])
        assert not any(a['id']==test_file['asset_id'] for a in after_delete['assets'])
        assert any(t['id']==test_id for t in after_delete['model_tests'])
        assert len([f for f in after_delete['model_test_files'] if f['test_id']==test_id])==1
        assert not renamed_test_path.exists()
        assert any(p.read_bytes()==test_png.getvalue() for p in Path(tmp,'trash','model_tests').iterdir())
        req('/api/model-test-delete',{'id':test_id})
        assert not any(f['test_id']==test_id for f in req('/api/state')['data']['model_test_files'])
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
        local=req('/api/local-engineering',{'name':'本地工程','local_path':r'D:\AOI\客户\project.proj','image_count':120})['id']
        req('/api/bind',{'image_id':im['id'],'engineering_id':local})
        localrow=next(e for e in req('/api/state')['data']['engineering_projects'] if e['id']==local)
        assert localrow['image_count']==120
        req('/api/save',{'table':'engineering_projects','id':local,'record':{**localrow,'image_count':180}})
        assert next(e for e in req('/api/state')['data']['engineering_projects'] if e['id']==local)['image_count']==180
        for bad_count in (-1,1.5):
            try:req('/api/save',{'table':'engineering_projects','id':local,'record':{**localrow,'image_count':bad_count}});assert False
            except urllib.error.HTTPError:pass
        assert localrow['local_path']==r'D:\AOI\客户\project.proj'
        req('/api/bag-defects',{'asset_id':result['asset_id'],'defect_ids':[1,2,3]})
        req('/api/bag-defects',{'asset_id':result['asset_id'],'defect_ids':[1,2,3]})
        assert len([r for r in req('/api/state')['data']['asset_defects'] if r['asset_id']==result['asset_id']])==3
        video=b'video-transport-test-fixture'
        vid=req('/api/upload?name=sample.mp4&kind=video&project_id=1',raw=video)['id']
        url='http://127.0.0.1:18765/api/video?id='+str(vid)
        video_record=next(v for v in req('/api/state')['data']['videos'] if v['id']==vid)
        assert video_record['project_id']==1 and video_record['image_id'] is None
        assert opener.open(url).read()==video
        response=opener.open(urllib.request.Request(url,headers={'Range':'bytes=2-8'}))
        assert response.status==206 and response.read()==video[2:9]
        response=opener.open(urllib.request.Request(url,headers={'Range':'bytes=-5'}))
        assert response.read()==video[-5:]
        before=req('/api/state')['data'];files=list(Path(tmp,'uploads').iterdir())
        try:req('/api/upload?name=bad.mp4&kind=video&project_id=999999',raw=video);assert False
        except urllib.error.HTTPError:pass
        assert before==req('/api/state')['data'] and files==list(Path(tmp,'uploads').iterdir())
        old=req('/api/state')['data']
        # Full JSON round trip on existing records.
        assert req('/api/import',{'data':old})['count']==sum(map(len,old.values()))
        sql=opener.open('http://127.0.0.1:18765/api/sql?data=1').read().decode()
        assert sql.count('CREATE TABLE IF NOT EXISTS')==25 and 'START TRANSACTION;' in sql
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
        print('PASS: authentication, guest/editor/admin permissions, agreements, after-sales, 25 tables, seed, CRUD, FK protection, category cycle, transaction rollback, ZIP registration, upload rollback, JSON round trip, SQL export, restart persistence, DB integrity, real image upload, thumbnail, full-resolution preview, engineering binding/download/unbind, invalid-image rollback.')
    finally:p.terminate();p.wait()
