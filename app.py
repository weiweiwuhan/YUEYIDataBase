import os,json,sqlite3,csv,io,sys,webbrowser,hashlib,uuid,zipfile,shutil
from pathlib import Path,PurePosixPath
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
from schema import T,TABLES,ddl
ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('AOI_DATA',str(ROOT/'data'))).resolve();DATA.mkdir(parents=True,exist_ok=True)
UPLOADS=DATA/'uploads';UPLOADS.mkdir(exist_ok=True)
THUMBS=DATA/'thumbnails';THUMBS.mkdir(exist_ok=True)
MYSQL=os.environ.get('DB_ENGINE','sqlite')=='mysql'
PORT=int(os.environ.get('PORT','8765'))
def connect():
    if MYSQL:
        import pymysql
        return pymysql.connect(host=os.environ.get('DB_HOST','127.0.0.1'),port=int(os.environ.get('DB_PORT','3306')),user=os.environ.get('DB_USER','aoi'),password=os.environ['DB_PASSWORD'],database=os.environ.get('DB_NAME','aoi_catalog'),charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    c=sqlite3.connect(DATA/'aoi.db',timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
def execute(c,sql,args=()):
    cur=c.cursor();cur.execute(sql.replace('?', '%s') if MYSQL else sql,args);return cur
def rows(c,t):return [dict(x) for x in execute(c,f'SELECT * FROM `{t}` ORDER BY id').fetchall()]
def validate(c,t,r,exclude=None):
    r=dict(r)
    if t=='products' and not r.get('code'):
        old=execute(c,'SELECT code FROM products WHERE id=?',(exclude or r.get('id'),)).fetchone()
        r['code']=old['code'] if old else 'AUTO-'+uuid.uuid4().hex
    meta=TABLES[t];names={x['name'] for x in meta['fields']}
    if set(r)-names:raise ValueError('未知字段: '+','.join(set(r)-names))
    out={}
    for f in meta['fields']:
        n=f['name'];v=r.get(n)
        if n=='id' and v in (None,''):continue
        if v=='':v=None
        if f['required'] and v is None:raise ValueError(f['label']+'不能为空')
        if v is not None:
            if f['kind'] in ('id','int'):
                if isinstance(v,bool) or str(v).strip()!=str(int(v)):raise ValueError(f['label']+'必须是整数')
                v=int(v)
                if v<0 or (n=='id' and v==0):raise ValueError(f['label']+'数值不合法')
            elif f['kind']=='real':
                import math
                v=float(v)
                if not math.isfinite(v) or v<0:raise ValueError(f['label']+'须为非负有限数值')
            else:
                v=str(v);maxlen=1024 if n in ('remark','relative_path','member_path','root_path','thumbnail_path','local_path') else 191
                if len(v)>maxlen:raise ValueError(f['label']+'内容过长')
            if f['choices'] and v not in f['choices']:raise ValueError(f['label']+'选项不合法')
        out[n]=v
    rid=exclude or out.get('id')
    if t=='product_categories' and out.get('parent_id'):
        seen={rid} if rid else set();p=out['parent_id']
        while p:
            if p in seen:raise ValueError('分类不能形成循环')
            seen.add(p);q=execute(c,'SELECT parent_id FROM product_categories WHERE id=?',(p,)).fetchone();p=q['parent_id'] if q else None
    if t=='assets':
        if out.get('relative_path'):
            p=out['relative_path'].replace('\\','/')
            if p.startswith('/') or ':' in p or '..' in PurePosixPath(p).parts:raise ValueError('相对路径不能是绝对路径或包含 ..')
            out['relative_path']=p
    if t in ('images','engineering_projects'):
        q=execute(c,'SELECT asset_type FROM assets WHERE id=?',(out.get('asset_id'),)).fetchone()
        allowed=['image'] if t=='images' else ['engineering','archive']
        if q and q['asset_type'] not in allowed:raise ValueError('资源类型不匹配')
    if t=='asset_relations':
        if out.get('source_asset_id')==out.get('target_asset_id'):raise ValueError('不能关联资源自身')
        if out.get('relation_type')=='contains':
            q=execute(c,'SELECT asset_type FROM assets WHERE id=?',(out['source_asset_id'],)).fetchone()
            if not q or q['asset_type']!='archive':raise ValueError('contains 来源必须是压缩包')
            if not out.get('member_path'):raise ValueError('请填写包内路径')
    return out
def save(c,t,r,rid=None):
    r=validate(c,t,r,rid)
    if rid:
        r.pop('id',None)
        q=execute(c,f'UPDATE `{t}` SET '+','.join('`'+k+'`=?' for k in r)+' WHERE id=?',list(r.values())+[rid])
        if q.rowcount==0 and not execute(c,f'SELECT id FROM `{t}` WHERE id=?',(rid,)).fetchone():raise ValueError('记录不存在')
        return rid
    keys=list(r);q=execute(c,f'INSERT INTO `{t}` ('+','.join('`'+k+'`' for k in keys)+') VALUES ('+','.join('?' for _ in keys)+')',list(r.values()));return r.get('id',q.lastrowid)
def snapshot(c):return {t['name']:rows(c,t['name']) for t in T}
def seed(c):
    if any(execute(c,f'SELECT COUNT(*) AS n FROM `{t["name"]}`').fetchone()['n'] for t in T):raise ValueError('示例仅能写入空库；现有数据未改变。')
    sample=json.loads((ROOT/'sample.json').read_text('utf-8'))
    for t in T:
        for r in sample.get(t['name'],[]):save(c,t['name'],r)
def initialize():
    c=connect()
    try:
        for s in ddl(MYSQL).split(';'):
            if not s.strip() or 'CREATE DATABASE' in s or s.strip().startswith('USE '):continue
            execute(c,s)
        fields=[x['Field'] for x in execute(c,'SHOW COLUMNS FROM engineering_projects').fetchall()] if MYSQL else [x['name'] for x in execute(c,'PRAGMA table_info(engineering_projects)').fetchall()]
        if 'local_path' not in fields:execute(c,'ALTER TABLE engineering_projects ADD COLUMN local_path '+('VARCHAR(1024)' if MYSQL else 'TEXT'))
        c.commit()
    finally:c.close()
def mysql_data(c):
    def lit(v):
        if v is None:return 'NULL'
        if isinstance(v,(int,float)):return str(v)
        # Hex literal avoids quoting and SQL mode ambiguities.
        return "CONVERT(X'"+str(v).encode('utf-8').hex()+"' USING utf8mb4)"
    out=[ddl(True),'-- Data for a fresh, empty database. Back up before importing.','START TRANSACTION;']
    for t in T:
        for r in rows(c,t['name']):out.append('INSERT INTO `'+t['name']+'` ('+','.join('`'+k+'`' for k in r)+') VALUES ('+','.join(lit(v) for v in r.values())+');')
    out+=['COMMIT;'];return '\n'.join(out)
def local_asset(c,aid):
    a=execute(c,'SELECT * FROM assets WHERE id=?',(aid,)).fetchone()
    if not a or a['storage_mode']!='file':raise ValueError('仅支持已上传到本地的文件；请重新上传旧 NAS / 包内图片')
    rel=a['relative_path'] or ''
    path=(UPLOADS/rel).resolve()
    if not path.is_relative_to(UPLOADS.resolve()) or not path.is_file():raise ValueError('本地文件不存在，请重新上传')
    return dict(a),path

def image_info(path):
    from PIL import Image
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        return dict(width=im.width,height=im.height,channels=len(im.getbands()))

class Handler(BaseHTTPRequestHandler):
    def reply(self,obj,status=200,ctype='application/json; charset=utf-8'):
        b=obj if isinstance(obj,bytes) else (json.dumps(obj,ensure_ascii=False).encode() if ctype.startswith('application/json') else obj.encode())
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(b)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b)
    def do_GET(self):
        p=urlparse(self.path);c=None
        try:
            if p.path=='/api/video':
                import mimetypes,re
                c=connect();vid=int(parse_qs(p.query).get('id',['0'])[0])
                row=execute(c,'SELECT * FROM videos WHERE id=?',(vid,)).fetchone()
                if not row:raise ValueError('视频不存在')
                path=(UPLOADS/row['relative_path']).resolve()
                if not path.is_relative_to(UPLOADS) or not path.is_file():raise ValueError('视频文件不存在')
                size=path.stat().st_size;start=0;end=size-1;partial=False
                rng=self.headers.get('Range')
                if rng:
                    m=re.fullmatch(r'bytes=(\d*)-(\d*)',rng)
                    if not m or not any(m.groups()):self.reply({'error':'无效范围'},416);return
                    if m[1]:start=int(m[1]);end=min(int(m[2]),end) if m[2] else end
                    else:start=max(0,size-int(m[2]))
                    if start>end:self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
                    partial=True
                self.send_response(206 if partial else 200);self.send_header('Content-Type',mimetypes.guess_type(row['file_name'])[0] or 'application/octet-stream');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
                if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                self.end_headers()
                with path.open('rb') as f:
                    f.seek(start);remaining=end-start+1
                    while remaining:
                        b=f.read(min(1024*1024,remaining))
                        if not b:break
                        self.wfile.write(b);remaining-=len(b)
                return
            if p.path=='/api/media':
                from PIL import Image,ImageOps
                import mimetypes
                c=connect();q=parse_qs(p.query);aid=int(q.get('id',['0'])[0]);mode=q.get('mode',['thumb'])[0]
                a,path=local_asset(c,aid)
                if mode=='original':
                    from urllib.parse import quote
                    self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(path.stat().st_size));self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(a['file_name']));self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
                    with path.open('rb') as f:shutil.copyfileobj(f,self.wfile)
                    return
                if a['asset_type']!='image' or mode not in ('thumb','view'):raise ValueError('资源不是可预览图片')
                cache=THUMBS/(str(aid)+'-'+str(path.stat().st_mtime_ns)+'.jpg')
                if mode=='thumb' and cache.exists():self.reply(cache.read_bytes(),ctype='image/jpeg');return
                with Image.open(path) as im:
                    # Keep pixel orientation and size consistent with the actual industrial source image.
                    im.seek(0)
                    if mode=='thumb':
                        im.thumbnail((480,360));im=im.convert('RGB');out=io.BytesIO();im.save(out,format='JPEG',quality=85);cache.write_bytes(out.getvalue());self.reply(out.getvalue(),ctype='image/jpeg')
                    else:
                        out=io.BytesIO()
                        if im.mode not in ('1','L','LA','RGB','RGBA','I;16','I'):im=im.convert('RGB')
                        im.save(out,format='PNG');self.reply(out.getvalue(),ctype='image/png')
                return
            if p.path=='/api/state':
                c=connect();self.reply(dict(schema=T,data=snapshot(c),engine='MySQL' if MYSQL else 'SQLite',version='1.2.1'));return
            if p.path=='/api/sql':
                c=connect();self.reply(mysql_data(c) if parse_qs(p.query).get('data')==['1'] else ddl(True),ctype='text/plain; charset=utf-8');return
            if p.path in ('/','/app.js','/style.css'):
                f=ROOT/'static'/({'/':'index.html'}.get(p.path,p.path[1:]));self.reply(f.read_bytes(),ctype={'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[p.path]);return
            self.reply({'error':'Not found'},404)
        except Exception as e:self.reply({'error':str(e)},400)
        finally:
            if c:c.close()
    def do_POST(self):
        # Same-origin writes only, including multipart-free binary uploads.
        origin=self.headers.get('Origin')
        if origin and origin!='http://'+self.headers.get('Host',''):
            self.reply({'error':'跨来源写入已拒绝'},403);return
        if self.headers.get('X-AOI-Client')!='local-v1':self.reply({'error':'缺少本地客户端标识'},403);return
        c=None;created=[]
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n>1024*1024*1024:raise ValueError('单次上传上限 1 GB')
            p=urlparse(self.path);c=connect()
            if p.path=='/api/upload':
                q=parse_qs(p.query);name=q.get('name',['upload.bin'])[0].replace('\\','/').split('/')[-1]
                if not name or len(name)>191:raise ValueError('文件名不合法')
                dest=UPLOADS/(uuid.uuid4().hex+'_'+name);h=hashlib.sha256();remain=n
                with dest.open('wb') as out:
                    created.append(dest)
                    while remain:
                        b=self.rfile.read(min(remain,1024*1024))
                        if not b:raise ValueError('上传不完整')
                        out.write(b);h.update(b);remain-=len(b)
                if q.get('kind')==['video']:
                    if dest.suffix.lower() not in ('.mp4','.webm','.mov','.avi','.mkv','.m4v'):raise ValueError('请选择视频文件')
                    if n==0:raise ValueError('视频文件为空')
                    vid=save(c,'videos',dict(image_id=int(q.get('image_id',['0'])[0]),name=q.get('title',[Path(name).stem])[0],file_name=name,relative_path=dest.name,file_size=n))
                    c.commit();self.reply(dict(ok=True,id=vid));return
                loc=execute(c,'SELECT id FROM storage_locations WHERE name=?',('本地上传',)).fetchone()
                lid=loc['id'] if loc else save(c,'storage_locations',dict(name='本地上传',root_path=str(UPLOADS)))
                ext=dest.suffix.lower();kind='image' if ext in ('.png','.bmp','.jpg','.jpeg','.tif','.tiff','.webp') else 'archive' if ext=='.zip' else 'other'
                engineering=q.get('kind',[''])[0]=='engineering'
                if engineering:kind='engineering'
                if q.get('image_only')==['1'] and kind!='image':raise ValueError('请选择图片文件')
                info=image_info(dest) if kind=='image' else {}
                aid=save(c,'assets',dict(asset_type=kind,file_name=name,storage_location_id=lid,relative_path=dest.name,storage_mode='file',file_size=n,sha256=h.hexdigest(),status='available'))
                pid=int(q.get('project_id',['0'])[0]);prod=int(q.get('product_id',['0'])[0])
                def links(a):
                    if pid:save(c,'project_assets',dict(project_id=pid,asset_id=a))
                    if prod:save(c,'asset_products',dict(asset_id=a,product_id=prod))
                links(aid);count=0
                if kind=='image':
                    iid=save(c,'images',dict(asset_id=aid,quality_label='unknown',annotation_status='unlabeled',**info))
                    eid=int(q.get('engineering_id',['0'])[0])
                    if eid:
                        en=execute(c,'SELECT asset_id FROM engineering_projects WHERE id=?',(eid,)).fetchone()
                        if not en:raise ValueError('工程不存在')
                        save(c,'asset_relations',dict(source_asset_id=en['asset_id'],target_asset_id=aid,relation_type='paired'))
                if engineering:save(c,'engineering_projects',dict(asset_id=aid,name=Path(name).stem,engineering_version=q.get('version',['v1'])[0]))
                if kind=='archive':
                    with zipfile.ZipFile(dest) as z:
                        members=z.infolist()
                        if len(members)>20000:raise ValueError('ZIP 成员超过 20000，请改为登记 NAS 路径')
                        for m in members:
                            if m.is_dir():continue
                            mp=m.filename.replace('\\','/')
                            if mp.startswith('/') or '..' in PurePosixPath(mp).parts or ':' in mp:raise ValueError('ZIP 存在不安全路径')
                            if len(mp)>1024:raise ValueError('ZIP 包内路径过长')
                            fn=PurePosixPath(mp).name;ex=PurePosixPath(mp).suffix.lower();mk='image' if ex in ('.png','.bmp','.jpg','.jpeg','.tif','.tiff','.webp') else 'other'
                            mid=save(c,'assets',dict(asset_type=mk,file_name=fn,storage_mode='archive_member',file_size=m.file_size,status='unverified'))
                            save(c,'asset_relations',dict(source_asset_id=aid,target_asset_id=mid,relation_type='contains',member_path=mp));links(mid)
                            if mk=='image':save(c,'images',dict(asset_id=mid,quality_label='unknown',annotation_status='unlabeled'))
                            count+=1
                c.commit();self.reply(dict(ok=True,asset_id=aid,members=count));return
            payload=json.loads(self.rfile.read(n) or b'{}')
            if p.path=='/api/local-engineering':
                path=str(payload.get('local_path','')).strip().strip('"')
                import ntpath
                if not (ntpath.isabs(path) or Path(path).is_absolute()) or len(path)>1024:raise ValueError('请填写完整本地路径，例如 D:\\AOI\\项目工程')
                aid=save(c,'assets',dict(asset_type='engineering',file_name=ntpath.basename(path.rstrip('\\/')) or '本地工程',storage_mode='file',status='unverified'))
                eid=save(c,'engineering_projects',dict(asset_id=aid,name=payload.get('name') or ntpath.basename(path),local_path=path,engineering_version=payload.get('engineering_version') or 'v1'))
                result=dict(ok=True,id=eid)
            elif p.path=='/api/open-engineering':
                import ipaddress,subprocess
                if not ipaddress.ip_address(self.client_address[0]).is_loopback:raise ValueError('请在运行服务的电脑上打开工程目录')
                row=execute(c,'SELECT local_path FROM engineering_projects WHERE id=?',(int(payload['id']),)).fetchone()
                if not row or not row['local_path']:raise ValueError('该工程尚未登记本地路径')
                path=Path(row['local_path'])
                if not path.exists():raise ValueError('本地路径不存在，请检查磁盘和路径')
                if sys.platform!='win32':raise ValueError('一键定位仅支持 Windows 本机运行；请复制路径打开')
                if path.is_dir():os.startfile(str(path))
                else:subprocess.Popen(['explorer.exe','/select,',str(path)])
                result=dict(ok=True)
            elif p.path=='/api/bag-defects':
                aid=int(payload['asset_id']);ids=set(map(int,payload['defect_ids']))
                if not ids:raise ValueError('请至少选择一个缺陷')
                for did in ids:
                    if not execute(c,'SELECT id FROM asset_defects WHERE asset_id=? AND defect_type_id=?',(aid,did)).fetchone():save(c,'asset_defects',dict(asset_id=aid,defect_type_id=did,remark=payload.get('remark')))
                result=dict(ok=True)
            elif p.path=='/api/bind':
                image=execute(c,'SELECT asset_id FROM images WHERE id=?',(int(payload['image_id']),)).fetchone()
                en=execute(c,'SELECT asset_id FROM engineering_projects WHERE id=?',(int(payload['engineering_id']),)).fetchone()
                if not image or not en:raise ValueError('图片或工程不存在')
                args=(en['asset_id'],image['asset_id'],'paired')
                old=execute(c,'SELECT id FROM asset_relations WHERE source_asset_id=? AND target_asset_id=? AND relation_type=?',args).fetchone()
                if payload.get('remove'):
                    if old:execute(c,'DELETE FROM asset_relations WHERE id=?',(old['id'],))
                elif not old:save(c,'asset_relations',dict(source_asset_id=en['asset_id'],target_asset_id=image['asset_id'],relation_type='paired'))
                result=dict(ok=True)
            elif p.path=='/api/save':
                t=payload['table']
                if t not in TABLES:raise ValueError('未知表')
                rid=save(c,t,payload['record'],payload.get('id'));result=dict(ok=True,id=rid)
            elif p.path=='/api/delete':
                t=payload['table']
                if t not in TABLES:raise ValueError('未知表')
                execute(c,f'DELETE FROM `{t}` WHERE id=?',(int(payload['id']),));result=dict(ok=True)
            elif p.path=='/api/seed':seed(c);result=dict(ok=True)
            elif p.path=='/api/import':
                data=payload['data'];total=0
                if not isinstance(data,dict) or set(data)-set(TABLES):raise ValueError('JSON 应是以表名为键的对象')
                for t in T:
                    records=data.get(t['name'],[])
                    if not isinstance(records,list):raise ValueError('表数据必须为数组')
                    for record in records:
                        rid=record.get('id');exists=rid and execute(c,f'SELECT id FROM `{t["name"]}` WHERE id=?',(rid,)).fetchone()
                        save(c,t['name'],record,rid if exists else None);total+=1
                result=dict(ok=True,count=total)
            else:raise ValueError('未知接口')
            c.commit();self.reply(result)
        except Exception as e:
            if c:c.rollback()
            for f in created:f.unlink(missing_ok=True)
            self.reply({'error':str(e)},400)
        finally:
            if c:c.close()
def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default=os.environ.get('HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=PORT)
    parser.add_argument('--no-browser',action='store_true')
    args,_=parser.parse_known_args()
    initialize();host=args.host;port=args.port
    server=ThreadingHTTPServer((host,port),Handler)
    print(f'AOI Catalog: http://127.0.0.1:{port} | {"MySQL" if MYSQL else "SQLite"}',flush=True)
    if not args.no_browser:webbrowser.open(f'http://127.0.0.1:{port}')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
