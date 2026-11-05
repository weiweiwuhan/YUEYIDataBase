"""100 simultaneous readers and 20 writers on isolated data; no production files."""
import urllib.error
import concurrent.futures,gzip,hashlib,io,json,os,secrets,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path

def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ.update(AOI_DATA=tmp,DB_ENGINE='sqlite',PYTHONDONTWRITEBYTECODE='1')
        import app,auth
        app.initialize();c=app.connect()
        # Exercise real batch provisioning and its hashes; credentials never enter output.
        accounts=auth.create_accounts(c,app.execute,50,'loaduser');c.commit()
        assert len(accounts)==50 and len({a['password'] for a in accounts})==50
        accounts.clear()
        users=app.execute(c,'SELECT id,username,password_hash FROM app_users ORDER BY id').fetchall();tokens=[]
        for user in users:
            assert len(user['password_hash'].split(':')[1])==64
            token=secrets.token_urlsafe(32);tokens.append(token)
            app.execute(c,'INSERT INTO app_sessions(token_hash,user_id,expires) VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],int(time.time())+3600))
        from PIL import Image
        b=io.BytesIO();Image.new('RGB',(800,600),(25,80,120)).save(b,format='PNG');png=b.getvalue()
        for i in range(1000):
            aid=app.save(c,'assets',{'asset_type':'image','file_name':f'sample-{i}.png','storage_mode':'file','status':'available','relative_path':f'sample-{i}.png'})
            app.save(c,'images',{'asset_id':aid,'quality_label':'unknown','annotation_status':'unlabeled'})
            if i==0:(Path(tmp)/'uploads'/f'sample-{i}.png').write_bytes(png)
        c.commit();c.close()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        with tempfile.TemporaryFile() as log:
            process=subprocess.Popen([sys.executable,'app.py','--no-browser','--port',str(port)],stdout=log,stderr=log)
            base=f'http://127.0.0.1:{port}'
            try:
                for _ in range(100):
                    try:urllib.request.urlopen(base+'/api/records?table=images',timeout=2).close();break
                    except OSError:time.sleep(.05)
                else:raise AssertionError('server startup failed')
                def call(path,token=None,body=None):
                    headers={'Accept-Encoding':'gzip','X-AOI-Client':'local-v1'}
                    if token:headers['Cookie']='aoi_session='+token
                    request=urllib.request.Request(base+path,data=body,headers=headers)
                    start=time.perf_counter()
                    with urllib.request.urlopen(request,timeout=45) as response:
                        raw=response.read()
                        if response.headers.get('Content-Encoding')=='gzip':raw=gzip.decompress(raw)
                    return time.perf_counter()-start,raw
                def readers(i):
                    kind=i%3
                    path='/api/state' if kind==0 else '/api/media?id=1&mode=thumb' if kind==1 else '/api/records?table=images&page=2&page_size=50'
                    latency,raw=call(path,tokens[i%50])
                    if kind==0:
                        value=json.loads(raw);assert len(value['data']['images'])>=1000;assert value['auth']['username']==users[i%50]['username']
                    elif kind==1:assert raw.startswith(b'\xff\xd8')
                    else:assert len(json.loads(raw)['data'])==50
                    return latency
                def writes(i):
                    try:latency,raw=call('/api/upload?name=concurrent-'+str(i)+'.png&image_only=1',tokens[i%50],png)
                    except urllib.error.HTTPError as e:raise AssertionError(e.read().decode()) from e
                    assert json.loads(raw)['ok'];return latency
                def summary(values):
                    values=sorted(values);return {'requests':len(values),'p50_ms':round(values[len(values)//2]*1000,1),'p95_ms':round(values[int((len(values)-1)*.95)]*1000,1),'max_ms':round(values[-1]*1000,1),'errors':0}
                with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:read_values=list(pool.map(readers,range(100)))
                with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:
                    futures=[pool.submit(readers,i) for i in range(80)]+[pool.submit(writes,i) for i in range(20)]
                    mixed_values=[f.result() for f in futures]
                state=json.loads(call('/api/state',tokens[0])[1]);assert len(state['data']['images'])==1020
                uploads=[a for a in state['data']['assets'] if a['file_name'].startswith('concurrent-')]
                assert len(uploads)==20 and all(a['created_by'].startswith('loaduser') for a in uploads)
                c=app.connect();assert app.execute(c,'PRAGMA integrity_check').fetchone()[0]=='ok';assert not app.execute(c,'PRAGMA foreign_key_check').fetchall();c.close()
                report={'accounts':50,'initial_images':1000,'concurrent_readers':summary(read_values),'mixed_80_reads_20_uploads':summary(mixed_values),'author_attribution':'passed','database_integrity':'passed'}
                print(json.dumps(report,ensure_ascii=False,indent=2))
            finally:process.terminate();process.wait(timeout=10)
if __name__=='__main__':main()
