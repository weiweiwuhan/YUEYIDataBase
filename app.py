import threading,time,gzip
from datetime import datetime,timezone
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
ASSISTANT_ENGINE=None
ASSISTANT_ENGINE_LOCK=threading.Lock()
def get_assistant_engine():
    global ASSISTANT_ENGINE
    with ASSISTANT_ENGINE_LOCK:
        if ASSISTANT_ENGINE is None:
            from assistant_service import AssistantService
            ASSISTANT_ENGINE=AssistantService(DATA,connect,execute)
        return ASSISTANT_ENGINE
OFFLINE_ENGINE=None
OFFLINE_ENGINE_LOCK=threading.Lock()
def get_offline_engine():
    global OFFLINE_ENGINE
    with OFFLINE_ENGINE_LOCK:
        if OFFLINE_ENGINE is None:
            from offline_queue import OfflineQueue
            OFFLINE_ENGINE=OfflineQueue(DATA)
        return OFFLINE_ENGINE
ACTOR=threading.local()
STATE_LOCK=threading.RLock()
WRITE_LOCK=threading.Lock()
MEDIA_LOCKS=[threading.Lock() for _ in range(64)]
STATE_CACHE={'data':None,'expires':0}
def invalidate_state():
    with STATE_LOCK:STATE_CACHE.update(data=None,expires=0)
def cached_snapshot():
    with STATE_LOCK:
        if STATE_CACHE['data'] is None or time.monotonic()>STATE_CACHE['expires']:
            c=connect()
            try:
                if not MYSQL:c.execute('BEGIN')
                STATE_CACHE.update(data=snapshot(c),expires=time.monotonic()+2)
            finally:c.close()
        return STATE_CACHE['data']
def commit_write(c,handler):
    from knowledge_graph import validate_experience
    checks=getattr(ACTOR,'knowledge_checks',set())
    for table,rid in checks:
        if table=='technical_experiences':
            if execute(c,'SELECT id FROM technical_experiences WHERE id=?',(rid,)).fetchone():validate_experience(c,execute,rid)
        elif table=='model_tests':
            for raw in execute(c,"SELECT * FROM knowledge_links WHERE evidence_test_id=? OR (relation='测试依据' AND target_table='model_tests' AND target_id=?)",(rid,rid)).fetchall():
                link=dict(raw)
                if link['source_table']=='technical_experiences':validate_experience(c,execute,link['source_id'])
    if getattr(ACTOR,'promote_media',False):
        from catalog_migrations import promote
        promote(c,execute,save);ACTOR.promote_media=False
    if getattr(ACTOR,'storage_dirty',False):
        from catalog_storage import sync_files
        sync_files(c,execute,UPLOADS,handler._renamed)
        ACTOR.storage_dirty=False
    actor=getattr(ACTOR,'username',None) or 'system'
    execute(c,'INSERT INTO audit_events (actor,action,created_at) VALUES (?,?,?)',(actor,urlparse(handler.path).path,datetime.now(timezone.utc).isoformat(timespec='microseconds')))
    c.commit();invalidate_state()
class ConflictError(ValueError):pass
class CatalogServer(ThreadingHTTPServer):
    request_queue_size=256
    daemon_threads=True

def connect():
    if MYSQL:
        import pymysql
        return pymysql.connect(host=os.environ.get('DB_HOST','127.0.0.1'),port=int(os.environ.get('DB_PORT','3306')),user=os.environ.get('DB_USER','aoi'),password=os.environ['DB_PASSWORD'],database=os.environ.get('DB_NAME','aoi_catalog'),charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    c=sqlite3.connect(DATA/'aoi.db',timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=30000');c.execute('PRAGMA synchronous=FULL');return c
def execute(c,sql,args=()):
    cur=c.cursor();cur.execute(sql.replace('?', '%s') if MYSQL else sql,args);return cur
def rows(c,t):return [dict(x) for x in execute(c,f'SELECT * FROM `{t}` ORDER BY id').fetchall()]
def validate(c,t,r,exclude=None):
    r=dict(r)
    if t=='products' and not r.get('code'):
        old=execute(c,'SELECT code FROM products WHERE id=?',(exclude or r.get('id'),)).fetchone()
        r['code']=old['code'] if old else 'AUTO-'+uuid.uuid4().hex
    if t=='model_tests' and not r.get('test_module'):r['test_module']='大模型测试'
    if t=='technical_agreements' and not r.get('document_type'):r['document_type']='技术协议'
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
                if v<f.get('minimum',0):raise ValueError(f['label']+'数值不合法')
            elif f['kind']=='real':
                import math
                if isinstance(v,bool):raise ValueError(f['label']+'必须是数值')
                v=float(v)
                if not math.isfinite(v) or v<0:raise ValueError(f['label']+'须为非负有限数值')
            else:
                v=str(v);maxlen=f.get('maxLength',191)
                if f['required'] and not v.strip():raise ValueError(f['label']+'不能为空')
                if len(v)>maxlen:raise ValueError(f['label']+'内容过长')
            if 'maximum' in f and v>f['maximum']:raise ValueError(f['label']+'不得超过 '+str(f['maximum']))
            if f['choices'] and v not in f['choices']:raise ValueError(f['label']+'选项不合法')
        out[n]=v
    rid=exclude or out.get('id')
    if t in ('product_categories','catalog_categories') and out.get('parent_id'):
        seen={rid} if rid else set();p=out['parent_id']
        while p:
            if p in seen:raise ValueError('分类不能形成循环')
            seen.add(p);q=execute(c,f'SELECT parent_id FROM `{t}` WHERE id=?',(p,)).fetchone();p=q['parent_id'] if q else None
    if t=='catalog_categories' and out.get('parent_id'):
        parent=execute(c,'SELECT source_system FROM catalog_categories WHERE id=?',(out['parent_id'],)).fetchone()
        if not parent or parent['source_system']!=out['source_system']:raise ValueError('目录父分类必须属于同一来源系统')
    if t=='catalog_product_categories':
        product=execute(c,'SELECT source_system FROM catalog_products WHERE id=?',(out.get('catalog_product_id'),)).fetchone()
        category=execute(c,'SELECT source_system FROM catalog_categories WHERE id=?',(out.get('catalog_category_id'),)).fetchone()
        if not product or not category or product['source_system']!=category['source_system']:raise ValueError('目录产品与分类必须存在且属于同一来源系统')
    if t in ('catalog_products','catalog_categories'):
        from catalog_import import _valid_url
        _valid_url(out.get('source_url'))
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
    if t=='videos' and not out.get('project_id') and not out.get('image_id') and not out.get('asset_id'):raise ValueError('请选择绑定项目或已登记视频资源')
    if t=='knowledge_links':
        from knowledge_graph import validate_relation
        validate_relation(c,execute,out)
    if t=='entity_aliases':
        from knowledge_graph import entity
        entity(c,execute,out['entity_table'],out['entity_id'])
    if t in ('assets','videos') and out.get('preview_asset_id'):
        preview=execute(c,'SELECT asset_type FROM assets WHERE id=?',(out['preview_asset_id'],)).fetchone()
        if not preview or preview['asset_type']!='image':raise ValueError('封面必须是图片资源')
    if t=='technical_experience_files':
        if bool(out.get('asset_id'))==bool(out.get('video_id')):raise ValueError('请选择一种文档或视频资料')
        if out.get('asset_id'):
            asset=execute(c,'SELECT asset_type,file_name FROM assets WHERE id=?',(out['asset_id'],)).fetchone()
            if not asset or (asset['asset_type']!='document' and Path(asset['file_name']).suffix.lower() not in ('.mp4','.webm','.mov','.avi','.mkv','.m4v')):raise ValueError('请选择文档或视频文件')
    return out
def save(c,t,r,rid=None):
    r=dict(r)
    existing=execute(c,f'SELECT * FROM `{t}` WHERE id=?',(rid or r.get('id'),)).fetchone() if rid or r.get('id') else None
    stamps=('created_by','created_at','updated_by','updated_at')
    for key in stamps:r.pop(key,None)
    now=datetime.now(timezone.utc).isoformat(timespec='microseconds');actor=getattr(ACTOR,'username',None) or 'system'

    if t=='videos' and rid:
        old=execute(c,'SELECT image_id,asset_id,preview_asset_id FROM videos WHERE id=?',(rid,)).fetchone()
        if old:r={**dict(old),**r}
    if t=='model_tests' and rid:
        old=execute(c,'SELECT project_id,result,miss_rate FROM model_tests WHERE id=?',(rid,)).fetchone()
        if old:r={**dict(old),**r}
    if existing:
        if t=='assets' and 'preview_asset_id' not in r:r['preview_asset_id']=existing['preview_asset_id']
        if t=='model_tests' and not getattr(ACTOR,'recapture_snapshot',False) and existing['parameter_snapshot']:r['parameter_snapshot']=existing['parameter_snapshot']
    r=validate(c,t,r,rid)
    if t=='technical_experience_files':ACTOR.promote_media=True
    if t in ('assets','videos','technical_agreements','agreement_files'):ACTOR.storage_dirty=True
    if t=='technical_agreements' and r.get('document_type') and not execute(c,'SELECT id FROM document_types WHERE name=?',(r['document_type'],)).fetchone():save(c,'document_types',{'name':r['document_type']})
    unchanged=existing and all(existing[k]==v for k,v in r.items() if k not in stamps)
    r.update(created_by=existing['created_by'] if existing else actor,created_at=existing['created_at'] if existing else now,updated_by=existing['updated_by'] if unchanged else actor,updated_at=existing['updated_at'] if unchanged else now)
    if rid:
        r.pop('id',None)
        q=execute(c,f'UPDATE `{t}` SET '+','.join('`'+k+'`=?' for k in r)+' WHERE id=?',list(r.values())+[rid])
        if q.rowcount==0 and not execute(c,f'SELECT id FROM `{t}` WHERE id=?',(rid,)).fetchone():raise ValueError('记录不存在')
        saved_id=rid
    else:
        keys=list(r);q=execute(c,f'INSERT INTO `{t}` ('+','.join('`'+k+'`' for k in keys)+') VALUES ('+','.join('?' for _ in keys)+')',list(r.values()));saved_id=r.get('id',q.lastrowid)
    checks=getattr(ACTOR,'knowledge_checks',set())
    if t in ('technical_experiences','model_tests'):checks.add((t,saved_id))
    if t=='knowledge_links' and r['source_table'] in ('technical_experiences','model_tests'):checks.add((r['source_table'],r['source_id']))
    ACTOR.knowledge_checks=checks
    return saved_id
def snapshot(c):return {t['name']:rows(c,t['name']) for t in T}
def seed(c):
    if any(execute(c,f'SELECT COUNT(*) AS n FROM `{t["name"]}`').fetchone()['n'] for t in T):raise ValueError('示例仅能写入空库；现有数据未改变。')
    sample=json.loads((ROOT/'sample.json').read_text('utf-8'))
    for t in T:
        for r in sample.get(t['name'],[]):save(c,t['name'],r)
def initialize():
    c=connect()
    try:
        if not MYSQL:execute(c,'PRAGMA journal_mode=WAL')
        pending_indexes=[]
        for s in ddl(MYSQL).split(';'):
            if not s.strip() or 'CREATE DATABASE' in s or s.strip().startswith('USE '):continue
            if s.strip().startswith('CREATE INDEX'):
                pending_indexes.append(s);continue
            execute(c,s)
        from catalog_migrations import extend
        extend(c,execute,MYSQL)
        fields=[x['Field'] for x in execute(c,'SHOW COLUMNS FROM engineering_projects').fetchall()] if MYSQL else [x['name'] for x in execute(c,'PRAGMA table_info(engineering_projects)').fetchall()]
        if 'image_count' not in fields:execute(c,'ALTER TABLE engineering_projects ADD COLUMN image_count '+('BIGINT' if MYSQL else 'INTEGER'))
        if 'local_path' not in fields:execute(c,'ALTER TABLE engineering_projects ADD COLUMN local_path '+('VARCHAR(1024)' if MYSQL else 'TEXT'))
        agreement_fields=[x['Field'] for x in execute(c,'SHOW COLUMNS FROM technical_agreements').fetchall()] if MYSQL else [x['name'] for x in execute(c,'PRAGMA table_info(technical_agreements)').fetchall()]
        if 'extracted_text' not in agreement_fields:execute(c,'ALTER TABLE technical_agreements ADD COLUMN extracted_text '+('LONGTEXT' if MYSQL else 'TEXT'))
        if 'document_type' not in agreement_fields:execute(c,'ALTER TABLE technical_agreements ADD COLUMN document_type '+('VARCHAR(191)' if MYSQL else 'TEXT'))
        execute(c,"UPDATE technical_agreements SET document_type='技术协议' WHERE document_type IS NULL OR document_type=''")
        model_fields=[x['Field'] for x in execute(c,'SHOW COLUMNS FROM model_tests').fetchall()] if MYSQL else [x['name'] for x in execute(c,'PRAGMA table_info(model_tests)').fetchall()]
        for field,kind in [('test_module','VARCHAR(191)' if MYSQL else 'TEXT'),('test_method','MEDIUMTEXT' if MYSQL else 'TEXT'),('expected_result','MEDIUMTEXT' if MYSQL else 'TEXT'),('actual_result','MEDIUMTEXT' if MYSQL else 'TEXT'),('product_id','BIGINT' if MYSQL else 'INTEGER'),('test_count','BIGINT' if MYSQL else 'INTEGER'),('detection_rate','DOUBLE' if MYSQL else 'REAL'),('miss_rate','DOUBLE' if MYSQL else 'REAL'),('yield_rate','DOUBLE' if MYSQL else 'REAL'),('light_source','VARCHAR(191)' if MYSQL else 'TEXT'),('camera','VARCHAR(191)' if MYSQL else 'TEXT'),('lens','VARCHAR(191)' if MYSQL else 'TEXT'),('working_distance_mm','DOUBLE' if MYSQL else 'REAL'),('product_spec','VARCHAR(1024)' if MYSQL else 'TEXT')]:
            if field not in model_fields:
                suffix=(' NULL, ADD CONSTRAINT fk_model_tests_product FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT ON UPDATE RESTRICT' if MYSQL else ' REFERENCES products(id) ON DELETE RESTRICT ON UPDATE RESTRICT') if field=='product_id' else ''
                execute(c,f'ALTER TABLE model_tests ADD COLUMN {field} {kind}{suffix}')
        execute(c,"UPDATE model_tests SET test_module='大模型测试' WHERE test_module IS NULL OR test_module=''")
        video_fields=[x['Field'] for x in execute(c,'SHOW COLUMNS FROM videos').fetchall()] if MYSQL else [x['name'] for x in execute(c,'PRAGMA table_info(videos)').fetchall()]
        if 'project_id' not in video_fields:
            execute(c,'ALTER TABLE videos ADD COLUMN project_id '+('BIGINT NULL, ADD CONSTRAINT fk_videos_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE RESTRICT' if MYSQL else 'INTEGER REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE RESTRICT'))
        if MYSQL:
            image_field=next(x for x in execute(c,'SHOW COLUMNS FROM videos').fetchall() if x['Field']=='image_id')
            if image_field['Null']=='NO':execute(c,'ALTER TABLE videos MODIFY COLUMN image_id BIGINT NULL')
        elif any(x['name']=='image_id' and x['notnull'] for x in execute(c,'PRAGMA table_info(videos)').fetchall()):
            statement=next(s for s in ddl(False).split(';') if 'CREATE TABLE IF NOT EXISTS `videos`' in s)
            execute(c,statement.replace('`videos`','`videos_updated`',1))
            cols=','.join('`'+x['name']+'`' for x in execute(c,'PRAGMA table_info(videos)').fetchall())
            execute(c,f'INSERT INTO videos_updated ({cols}) SELECT {cols} FROM videos')
            execute(c,'DROP TABLE videos');execute(c,'ALTER TABLE videos_updated RENAME TO videos')
        # Infer only unique project associations; ambiguous legacy videos need manual assignment.
        execute(c,'UPDATE videos SET project_id=(SELECT MIN(pa.project_id) FROM images i JOIN project_assets pa ON pa.asset_id=i.asset_id WHERE i.id=videos.image_id HAVING COUNT(DISTINCT pa.project_id)=1) WHERE project_id IS NULL AND image_id IS NOT NULL')
        for item in T:
            columns=[x['Field'] for x in execute(c,'SHOW COLUMNS FROM `'+item['name']+'`').fetchall()] if MYSQL else [x['name'] for x in execute(c,'PRAGMA table_info(`'+item['name']+'`)').fetchall()]
            for field in ('created_by','created_at','updated_by','updated_at'):
                if field not in columns:execute(c,'ALTER TABLE `'+item['name']+'` ADD COLUMN '+field+(' VARCHAR(191)' if MYSQL else ' TEXT'))
        if MYSQL:
            for field in execute(c,'SHOW COLUMNS FROM after_sales').fetchall():
                if field['Field'] in ('symptom','cause','resolution','experience','remark') and field['Type'].lower() not in ('mediumtext','longtext'):
                    execute(c,'ALTER TABLE after_sales MODIFY COLUMN `'+field['Field']+'` MEDIUMTEXT NULL')
        audit_pk='BIGINT PRIMARY KEY AUTO_INCREMENT' if MYSQL else 'INTEGER PRIMARY KEY AUTOINCREMENT'
        execute(c,f'CREATE TABLE IF NOT EXISTS audit_events (id {audit_pk},actor VARCHAR(191) NOT NULL,action VARCHAR(191) NOT NULL,created_at VARCHAR(191) NOT NULL)')
        for statement in pending_indexes:execute(c,statement)
        import auth
        auth.initialize(c,execute,MYSQL)
        from catalog_migrations import promote
        promote(c,execute,save)
        moved=[]
        try:
            from catalog_storage import sync_files
            sync_files(c,execute,UPLOADS,moved);c.commit()
        except Exception:
            c.rollback()
            for old,new in reversed(moved):
                if new.exists():old.parent.mkdir(parents=True,exist_ok=True);new.rename(old)
            raise
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

def safe_filename(name):
    name=str(name).strip()
    if not name or len(name)>191 or name in ('.','..') or name.endswith(('.', ' ')) or any(ord(ch)<32 or ch in '<>:"/\\|?*' for ch in name):
        raise ValueError('文件名不合法，请勿包含路径或特殊字符')
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:raise ValueError('文件名为系统保留名称')
    return name

def image_info(path):
    from PIL import Image
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        return dict(width=im.width,height=im.height,channels=len(im.getbands()))

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup();self.connection.settimeout(120)
    def identity(self,c):
        import auth
        return auth.identity(c,execute,self.headers.get('Cookie',''))
    def require(self,c,admin=False):
        user=self.identity(c)
        if user:ACTOR.username=user['username']
        if not user:raise PermissionError('请先登录后再录入')
        if admin and user['role']!='admin':raise PermissionError('仅管理员可以执行此操作')
        return user
    def reply(self,obj,status=200,ctype='application/json; charset=utf-8'):
        b=obj if isinstance(obj,bytes) else (json.dumps(obj,ensure_ascii=False).encode() if ctype.startswith('application/json') else obj.encode())
        if len(b)>1024 and 'gzip' in self.headers.get('Accept-Encoding',''):
            b=gzip.compress(b,compresslevel=3);encoded=True
        else:encoded=False
        self.send_response(status)
        if encoded:self.send_header('Content-Encoding','gzip')
        self.send_header('Vary','Accept-Encoding');self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(b)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b)
    def stream_chat(self,engine,user,payload):
        from rag_assistant import StreamCancelled
        question=engine.rag.validate_chat_request(user,payload.get('question',''),payload.get('conversation_id'))
        self.send_response(200)
        for name,value in [('Content-Type','text/event-stream; charset=utf-8'),('Cache-Control','no-cache, no-transform'),('X-Accel-Buffering','no'),('Connection','close'),('X-Content-Type-Options','nosniff')]:self.send_header(name,value)
        self.end_headers();self.close_connection=True
        def emit(kind,data):
            try:
                self.wfile.write(('event: '+kind+'\ndata: '+json.dumps(data,ensure_ascii=False)+'\n\n').encode('utf-8'));self.wfile.flush()
            except (BrokenPipeError,ConnectionError,OSError):raise StreamCancelled()
        try:
            emit('status',{'message':'正在检索知识与适用条件…'})
            result=engine.chat(user,question,payload.get('conversation_id'),emit=emit)
            emit('done',result)
        except StreamCancelled:pass
        except Exception as error:
            try:emit('error',{'error':str(error) if isinstance(error,(ValueError,PermissionError)) else '回答暂时无法完成，请重试。'})
            except StreamCancelled:pass
    def do_GET(self):
        p=urlparse(self.path);c=None
        try:
            if p.path.startswith('/api/assistant/'):
                c=connect();user=self.require(c);c.close();c=None;engine=get_assistant_engine();q=parse_qs(p.query)
                if p.path=='/api/assistant/status':self.reply(engine.status());return
                if p.path=='/api/assistant/history':self.reply(engine.rag.history(user,q.get('id',[None])[0]));return
                raise ValueError('未知问答接口')
            if p.path.startswith('/api/offline/'):
                c=connect();user=self.require(c);c.close();c=None
                engine=get_offline_engine();q=parse_qs(p.query)
                if p.path=='/api/offline/models':self.reply(engine.models());return
                if p.path=='/api/offline/jobs':self.reply({'job':engine.get(user,q['id'][0])} if q.get('id') else {'jobs':engine.list(user)});return
                if p.path=='/api/offline/file':
                    path=engine.file(user,q.get('job_id',[''])[0],q.get('item_id',[''])[0],q.get('kind',['overlay'])[0])
                    from PIL import Image
                    with Image.open(path) as im:fmt=im.format;ctype=Image.MIME.get(fmt,'image/png')
                    if fmt in ('BMP','TIFF'):
                        with MEDIA_LOCKS[hash(str(path))%len(MEDIA_LOCKS)]:
                            preview=path.with_name('original-preview.png')
                            if not preview.exists():
                                temp=preview.with_name(uuid.uuid4().hex+'.tmp')
                                with Image.open(path) as source:source.seek(0);source.convert('RGB').save(temp,format='PNG')
                                temp.replace(preview)
                            path=preview;ctype='image/png'
                    self.send_response(200);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(path.stat().st_size));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
                    with path.open('rb') as source:shutil.copyfileobj(source,self.wfile)
                    return
                raise ValueError('未知离线测试接口')
            if p.path=='/api/knowledge/graph':
                from knowledge_graph import graph,neighborhood
                c=connect();q=parse_qs(p.query);data=graph(c,execute)
                if q.get('table'):data=neighborhood(data,q['table'][0],int(q.get('id',['0'])[0]),min(2,max(1,int(q.get('depth',['1'])[0]))))
                self.reply(data);return
            if p.path=='/api/preview':
                from media_preview import preview_bytes
                c=connect();q=parse_qs(p.query);data,ctype=preview_bytes(c,execute,UPLOADS,THUMBS,q.get('table',['assets'])[0],int(q.get('id',['0'])[0]))
                self.reply(data,ctype=ctype);return
            if p.path=='/api/document-view':
                c=connect();q=parse_qs(p.query);a,path=local_asset(c,int(q.get('id',['0'])[0]))
                suffix=path.suffix.lower()
                if suffix not in ('.pdf','.txt','.md','.csv'):raise ValueError('此格式请下载或上传封面预览')
                ctype='application/pdf' if suffix=='.pdf' else 'text/plain; charset=utf-8'
                self.send_response(200);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(path.stat().st_size));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"sandbox; default-src 'none'");self.end_headers()
                with path.open('rb') as f:shutil.copyfileobj(f,self.wfile)
                return
            if p.path=='/api/video':
                import mimetypes,re
                c=connect();vid=int(parse_qs(p.query).get('id',['0'])[0])
                row=execute(c,'SELECT * FROM videos WHERE id=?',(vid,)).fetchone()
                if parse_qs(p.query).get('asset_id'):
                    aid=int(parse_qs(p.query)['asset_id'][0]);asset,path=local_asset(c,aid)
                    if not execute(c,'SELECT id FROM technical_experience_files WHERE asset_id=?',(aid,)).fetchone() or path.suffix.lower() not in ('.mp4','.webm','.mov','.avi','.mkv','.m4v'):raise ValueError('视频不存在')
                    row={'file_name':asset['file_name'],'relative_path':asset['relative_path']}
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
                c.close();c=None
                with MEDIA_LOCKS[aid%len(MEDIA_LOCKS)]:
                    cache=THUMBS/(str(aid)+'-'+str(path.stat().st_mtime_ns)+'.jpg')
                    if mode=='thumb' and cache.exists():self.reply(cache.read_bytes(),ctype='image/jpeg');return
                    with Image.open(path) as im:
                        # Keep pixel orientation and size consistent with the actual industrial source image.
                        im.seek(0)
                        if mode=='thumb':
                            im.thumbnail((480,360));im=im.convert('RGB');out=io.BytesIO();im.save(out,format='JPEG',quality=85);temp=cache.with_name(uuid.uuid4().hex+'.tmp');temp.write_bytes(out.getvalue());temp.replace(cache);self.reply(out.getvalue(),ctype='image/jpeg')
                        else:
                            out=io.BytesIO()
                            if im.mode not in ('1','L','LA','RGB','RGBA','I;16','I'):im=im.convert('RGB')
                            im.save(out,format='PNG');self.reply(out.getvalue(),ctype='image/png')
                    return
            if p.path=='/api/auth/users':
                c=connect();self.require(c,True);self.reply([dict(x) for x in execute(c,'SELECT id,username,role FROM app_users ORDER BY id').fetchall()]);return
            if p.path=='/api/records':
                q=parse_qs(p.query);table=q.get('table',['images'])[0]
                if table not in TABLES:raise ValueError('未知表')
                page=max(1,int(q.get('page',['1'])[0]));size=min(200,max(1,int(q.get('page_size',['50'])[0])))
                c=connect();total=execute(c,f'SELECT COUNT(*) AS n FROM `{table}`').fetchone()['n']
                data=[dict(r) for r in execute(c,f'SELECT * FROM `{table}` ORDER BY id DESC LIMIT ? OFFSET ?',(size,(page-1)*size)).fetchall()]
                self.reply(dict(data=data,total=total,page=page,page_size=size));return
            if p.path=='/api/audit':
                c=connect();self.require(c,True);limit=min(100,max(1,int(parse_qs(p.query).get('limit',['50'])[0])));self.reply([dict(r) for r in execute(c,'SELECT * FROM audit_events ORDER BY id DESC LIMIT ?',(limit,)).fetchall()]);return
            if p.path=='/api/version':
                self.reply(json.loads((ROOT/'version.json').read_text('utf-8')));return
            if p.path=='/api/state':
                c=connect();self.reply(dict(schema=T,data=cached_snapshot(),engine='MySQL' if MYSQL else 'SQLite',version=json.loads((ROOT/'version.json').read_text('utf-8'))['version'],release=json.loads((ROOT/'version.json').read_text('utf-8')),auth=self.identity(c)));return
            if p.path=='/api/sql':
                c=connect();self.require(c,True);self.reply(mysql_data(c) if parse_qs(p.query).get('data')==['1'] else ddl(True),ctype='text/plain; charset=utf-8');return
            if p.path in ('/','/app.js','/style.css','/offline.js','/offline.css'):
                f=ROOT/'static'/({'/':'index.html'}.get(p.path,p.path[1:]));self.reply(f.read_bytes(),ctype={'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8','/offline.css':'text/css; charset=utf-8','/offline.js':'text/javascript; charset=utf-8'}[p.path]);return
            self.reply({'error':'Not found'},404)
        except Exception as e:self.reply({'error':str(e)},403 if isinstance(e,PermissionError) else 409 if isinstance(e,ConflictError) else 400)
        finally:
            if c:c.close()
    def do_POST(self):
        # Same-origin writes only, including multipart-free binary uploads.
        origin=self.headers.get('Origin')
        if origin and origin not in ('http://'+self.headers.get('Host',''),'https://'+self.headers.get('Host','')):
            self.reply({'error':'跨来源写入已拒绝'},403);return
        if self.headers.get('X-AOI-Client')!='local-v1':self.reply({'error':'缺少本地客户端标识'},403);return
        ACTOR.username=None
        c=None;created=[];renamed=[];write_locked=False;self._renamed=renamed;ACTOR.storage_dirty=False;ACTOR.recapture_snapshot=False;ACTOR.promote_media=False;ACTOR.knowledge_checks=set()
        try:
            self.connection.settimeout(120)
            n=int(self.headers.get('Content-Length','0'))
            if n>1024*1024*1024:raise ValueError('单次上传上限 1 GB')
            p=urlparse(self.path);c=connect()
            if p.path in ('/api/catalog/import-preview','/api/catalog/import'):
                user=self.require(c,True);q=parse_qs(p.query)
                from catalog_import import MAX_UPLOAD_BYTES,prepare_import,public_plan,validate_preview_token,apply_import
                if not 0<n<=MAX_UPLOAD_BYTES:raise ValueError('目录文件须为 1 字节至 20 MB')
                content=self.rfile.read(n)
                if len(content)!=n:raise ValueError('目录文件上传不完整')
                filename=q.get('name',[''])[0].replace('\\','/').split('/')[-1]
                mode=q.get('mode',['fill_missing'])[0];owner=str(user['id'])
                if p.path.endswith('import-preview'):
                    if not MYSQL:c.execute('BEGIN')
                    plan=prepare_import(c,execute,content,filename,mode,owner);self.reply(public_plan(plan));return
                WRITE_LOCK.acquire();write_locked=True;c.rollback()
                if not MYSQL:c.execute('BEGIN IMMEDIATE')
                plan=prepare_import(c,execute,content,filename,mode,owner)
                validate_preview_token(q.get('preview_token',[''])[0],plan,owner)
                if not plan['selected_count'] and not plan['category_add_count'] and not plan['category_update_count']:raise ValueError('没有选择“是”的待导入记录')
                result=apply_import(c,execute,save,plan);commit_write(c,self)
                self.reply({'ok':True,**result,'errors':[]});return
            if p.path.startswith('/api/assistant/') or p.path.startswith('/api/after-sales/import'):
                admin=p.path in ('/api/assistant/rebuild','/api/assistant/knowledge-import','/api/after-sales/import','/api/after-sales/import-preview')
                user=self.require(c,admin);c.close();c=None;engine=get_assistant_engine();q=parse_qs(p.query)
                if p.path in ('/api/assistant/knowledge-import','/api/after-sales/import','/api/after-sales/import-preview'):
                    if not 0<n<=5*1024*1024:raise ValueError('导入文件须为 1 字节至 5 MB')
                    content=self.rfile.read(n)
                    if len(content)!=n:raise ValueError('文件上传不完整')
                    filename=q.get('name',[''])[0].replace('\\','/').split('/')[-1]
                    if p.path=='/api/assistant/knowledge-import':self.reply(engine.import_knowledge(user,content,filename));return
                    from assistant_service import import_plan
                    defaults={k:q[k][0] for k in ('project_id','product_id','status') if q.get(k)}
                    if p.path.endswith('import-preview'):
                        plan=import_plan(connect,execute,content,filename,defaults);self.reply({k:v for k,v in plan.items() if k!='rows'});return
                    with WRITE_LOCK:
                        plan=import_plan(connect,execute,content,filename,defaults)
                        if plan['errors']:raise ValueError('导入未执行，请先修正预览错误：'+str(plan['errors'][:5]))
                        db=connect()
                        try:
                            for row in plan['rows']:save(db,'after_sales',row['record'])
                            commit_write(db,self)
                        except Exception:db.rollback();raise
                        finally:db.close()
                    try:status=engine.rebuild();updated=True
                    except Exception:status={'warning':'售后数据已导入，知识索引更新失败，请点击更新知识库重试'};updated=False
                    self.reply({'imported':len(plan['rows']),'duplicates':plan['duplicate_count'],'index_updated':updated,'status':status});return
                if n>65536:raise ValueError('问答请求过大')
                payload=json.loads(self.rfile.read(n) or b'{}')
                if not isinstance(payload,dict):raise ValueError('问答请求必须是对象')
                if p.path=='/api/assistant/rebuild':self.reply(engine.rebuild());return
                if p.path=='/api/assistant/chat-stream':self.stream_chat(engine,user,payload);return
                if p.path=='/api/assistant/chat':self.reply(engine.chat(user,payload.get('question',''),payload.get('conversation_id')));return
                if p.path=='/api/assistant/feedback':self.reply(engine.rag.feedback(user,payload.get('question_id'),payload.get('rating'),payload.get('comment','')));return
                raise ValueError('未知问答接口')
            if p.path.startswith('/api/offline/'):
                user=self.require(c);c.close();c=None
                engine=get_offline_engine();q=parse_qs(p.query)
                if p.path=='/api/offline/upload':
                    self.reply({'item':engine.upload(user,q.get('job_id',[''])[0],q.get('name',[''])[0],self.rfile,n)});return
                if n>65536:raise ValueError('离线任务参数最多 64 KB')
                payload=json.loads(self.rfile.read(n) or b'{}')
                if p.path=='/api/offline/jobs':self.reply({'job':engine.create(user,payload.get('model_id'),payload.get('params',{}))});return
                if p.path=='/api/offline/submit':self.reply({'job':engine.submit(user,payload.get('job_id'))});return
                if p.path=='/api/offline/cancel':self.reply({'job':engine.cancel(user,payload.get('job_id'))});return
                if p.path=='/api/offline/resegment':self.reply({'item':engine.resegment(user,payload.get('job_id'),payload.get('item_id'),payload.get('params',{}))});return
                raise ValueError('未知离线测试接口')
            if p.path.startswith('/api/auth/'):
                import auth
                payload=json.loads(self.rfile.read(n) or b'{}')
                WRITE_LOCK.acquire();write_locked=True;c.rollback()
                result,cookie=auth.handle(c,execute,self,p.path,payload)
                commit_write(c,self)
                body=json.dumps(result,ensure_ascii=False).encode()
                self.send_response(200)
                if cookie:self.send_header('Set-Cookie',cookie)
                self.send_header('Cache-Control','no-store');self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
            self.require(c,p.path in ('/api/delete','/api/import','/api/seed','/api/model-test-delete','/api/model-test-file-delete'))
            if p.path=='/api/upload':
                q=parse_qs(p.query);name=safe_filename(q.get('name',['upload.bin'])[0])
                if q.get('kind')==['agreement_new'] and n>256*1024*1024:raise ValueError('文档附件单文件最多 256 MB')
                if q.get('kind')==['agreement']:
                    if n>256*1024*1024:raise ValueError('文档附件单文件最多 256 MB')
                    if not execute(c,'SELECT id FROM technical_agreements WHERE id=?',(int(q.get('agreement_id',['0'])[0]),)).fetchone():raise ValueError('请先保存并选择文档资料，再上传附件')
                if q.get('kind')==['modeltest']:
                    if n>256*1024*1024:raise ValueError('测试图片单文件最多 256 MB')
                    if not execute(c,'SELECT id FROM model_tests WHERE id=?',(int(q.get('test_id',['0'])[0]),)).fetchone():raise ValueError('请先保存测试记录')
                    if q.get('role',[''])[0] not in ('input','result'):raise ValueError('请选择原图或效果图')
                if q.get('kind')==['preview']:
                    owner=q.get('owner_table',[''])[0]
                    if owner not in ('assets','videos'):raise ValueError('封面对象类型无效')
                    if n>32*1024*1024:raise ValueError('封面图片最多 32 MB')
                    if not execute(c,f'SELECT id FROM `{owner}` WHERE id=?',(int(q.get('owner_id',['0'])[0]),)).fetchone():raise ValueError('封面对象不存在')
                if q.get('kind')==['technical_experience']:
                    video=Path(name).suffix.lower() in ('.mp4','.webm','.mov','.avi','.mkv','.m4v')
                    if n>(1024*1024*1024 if video else 256*1024*1024):raise ValueError('文档最多 256 MB，视频最多 1 GB')
                    if not execute(c,'SELECT id FROM technical_experiences WHERE id=?',(int(q.get('experience_id',['0'])[0]),)).fetchone():raise ValueError('请先保存技术经验')
                    if n==0:raise ValueError('附件文件为空')
                dest=UPLOADS/(uuid.uuid4().hex+'_'+name);h=hashlib.sha256();remain=n
                with dest.open('wb') as out:
                    created.append(dest)
                    while remain:
                        b=self.rfile.read(min(remain,1024*1024))
                        if not b:raise ValueError('上传不完整')
                        out.write(b);h.update(b);remain-=len(b)
                WRITE_LOCK.acquire();write_locked=True;c.rollback()
                if q.get('kind')==['agreement_new']:
                    agreement_id=save(c,'technical_agreements',json.loads(q.get('record',['{}'])[0]))
                    q['kind']=['agreement'];q['agreement_id']=[str(agreement_id)]
                if q.get('kind')==['video']:
                    if dest.suffix.lower() not in ('.mp4','.webm','.mov','.avi','.mkv','.m4v'):raise ValueError('请选择视频文件')
                    if n==0:raise ValueError('视频文件为空')
                    project_id=int(q.get('project_id',['0'])[0])
                    if not execute(c,'SELECT id FROM projects WHERE id=?',(project_id,)).fetchone():raise ValueError('请选择有效的绑定项目')
                    vid=save(c,'videos',dict(project_id=project_id,name=q.get('title',[Path(name).stem])[0],file_name=name,relative_path=dest.name,file_size=n))
                    commit_write(c,self);self.reply(dict(ok=True,id=vid));return
                loc=execute(c,'SELECT id FROM storage_locations WHERE name=?',('本地上传',)).fetchone()
                lid=loc['id'] if loc else save(c,'storage_locations',dict(name='本地上传',root_path=str(UPLOADS)))
                ext=dest.suffix.lower();kind='image' if ext in ('.png','.bmp','.jpg','.jpeg','.tif','.tiff','.webp') else 'archive' if ext=='.zip' else 'other'
                experience=q.get('kind')==['technical_experience']
                modeltest=q.get('kind')==['modeltest']
                if modeltest and kind!='image':raise ValueError('请上传图片格式的测试原图或效果图')
                engineering=q.get('kind',[''])[0]=='engineering'
                agreement=q.get('kind')==['agreement']
                if agreement or experience:kind='document'
                if q.get('kind')==['preview']:
                    image_info(dest);kind='image'
                if engineering:kind='engineering'
                if q.get('image_only')==['1'] and kind!='image':raise ValueError('请选择图片文件')
                info=image_info(dest) if kind=='image' else {}
                aid=save(c,'assets',dict(asset_type=kind,file_name=name,storage_location_id=lid,relative_path=dest.name,storage_mode='file',file_size=n,sha256=h.hexdigest(),status='available'))
                if experience:
                    from catalog_migrations import promote
                    save(c,'technical_experience_files',dict(experience_id=int(q['experience_id'][0]),asset_id=aid));promote(c,execute,save)
                if q.get('kind')==['preview']:
                    owner=q['owner_table'][0];owner_id=int(q['owner_id'][0]);record=dict(execute(c,f'SELECT * FROM `{owner}` WHERE id=?',(owner_id,)).fetchone());record['preview_asset_id']=aid;save(c,owner,record,owner_id)
                if modeltest:save(c,'model_test_files',dict(test_id=int(q['test_id'][0]),asset_id=aid,role=q['role'][0]))
                if agreement:
                    save(c,'agreement_files',dict(agreement_id=int(q.get('agreement_id',['0'])[0]),asset_id=aid))
                pid=int(q.get('project_id',['0'])[0]);prod=int(q.get('product_id',['0'])[0])
                def links(a):
                    if pid:save(c,'project_assets',dict(project_id=pid,asset_id=a))
                    if prod:save(c,'asset_products',dict(asset_id=a,product_id=prod))
                links(aid);count=0
                if kind=='image' and not modeltest and q.get('kind')!=['preview']:
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
                commit_write(c,self);self.reply(dict(ok=True,asset_id=aid,members=count,agreement_id=int(q['agreement_id'][0]) if agreement else None));return
            payload=json.loads(self.rfile.read(n) or b'{}')
            if not isinstance(payload,dict):raise ValueError('请求必须是对象')
            if p.path=='/api/save' and payload.get('table') in ('catalog_categories','catalog_products','catalog_product_categories'):self.require(c,True)
            WRITE_LOCK.acquire();write_locked=True;c.rollback()
            if p.path=='/api/bind' and payload.get('remove'):self.require(c,True)
            if p.path in ('/api/model-test-file-rename','/api/model-test-file-delete'):
                item=execute(c,'SELECT asset_id FROM model_test_files WHERE id=?',(int(payload['file_id']),)).fetchone()
                if not item:raise ValueError('测试图片不存在或已移除')
                a=execute(c,'SELECT * FROM assets WHERE id=?',(item['asset_id'],)).fetchone()
                if not a or a['asset_type']!='image':raise ValueError('测试图片资源无效')
                if p.path=='/api/model-test-file-rename':
                    _,path=local_asset(c,a['id'])
                    name=safe_filename(safe_filename(payload['stem'])+path.suffix)
                    dest=UPLOADS/(uuid.uuid4().hex+'_'+name)
                    path.rename(dest);renamed.append((path,dest))
                    execute(c,'UPDATE assets SET file_name=?,relative_path=?,updated_by=?,updated_at=? WHERE id=?',(name,dest.name,getattr(ACTOR,'username',None) or 'system',datetime.now(timezone.utc).isoformat(timespec='microseconds'),a['id']))
                    ACTOR.storage_dirty=True
                    result=dict(ok=True,name=name)
                else:
                    if execute(c,"SELECT id FROM knowledge_links WHERE target_table='assets' AND target_id=?",(a['id'],)).fetchone():raise ValueError('该图片被知识关联引用，请先解除关联')
                    execute(c,"DELETE FROM knowledge_links WHERE source_table='assets' AND source_id=?",(a['id'],))
                    execute(c,"DELETE FROM entity_aliases WHERE entity_table='assets' AND entity_id=?",(a['id'],))
                    path=(UPLOADS/(a['relative_path'] or '')).resolve()
                    if not path.is_relative_to(UPLOADS.resolve()):raise ValueError('图片路径无效')
                    if path.is_file():
                        trash=DATA/'trash'/'model_tests';trash.mkdir(parents=True,exist_ok=True)
                        dest=trash/(uuid.uuid4().hex+'_'+path.name)
                        path.rename(dest);renamed.append((path,dest))
                    execute(c,'DELETE FROM model_test_files WHERE id=?',(int(payload['file_id']),))
                    execute(c,'DELETE FROM assets WHERE id=?',(a['id'],))
                    result=dict(ok=True)
            elif p.path=='/api/model-test-delete':
                test_id=int(payload['id'])
                if execute(c,"SELECT id FROM knowledge_links WHERE (target_table='model_tests' AND target_id=?) OR evidence_test_id=?",(test_id,test_id)).fetchone():raise ValueError('该测试被知识关联引用，请先解除关联')
                execute(c,"DELETE FROM knowledge_links WHERE source_table='model_tests' AND source_id=?",(test_id,))
                execute(c,"DELETE FROM entity_aliases WHERE entity_table='model_tests' AND entity_id=?",(test_id,))
                execute(c,'DELETE FROM model_test_files WHERE test_id=?',(test_id,))
                execute(c,'DELETE FROM model_tests WHERE id=?',(test_id,));result=dict(ok=True)
            elif p.path=='/api/image-defects':
                image_ids=set(map(int,payload.get('image_ids',[])));defect_ids=set(map(int,payload.get('defect_ids',[])))
                if not image_ids or not defect_ids:raise ValueError('请至少选择一张图片及一种缺陷')
                if len(image_ids)*len(defect_ids)>10000:raise ValueError('单次最多绑定 10000 条关系')
                # Validate the whole selection before writing; failures roll back every binding.
                for iid in image_ids:
                    if not execute(c,'SELECT id FROM images WHERE id=?',(iid,)).fetchone():raise ValueError('图片不存在')
                for did in defect_ids:
                    if not execute(c,'SELECT id FROM defect_types WHERE id=?',(did,)).fetchone():raise ValueError('缺陷类型不存在')
                count=0
                for iid in image_ids:
                    for did in defect_ids:
                        if not execute(c,'SELECT id FROM image_defects WHERE image_id=? AND defect_type_id=?',(iid,did)).fetchone():
                            save(c,'image_defects',dict(image_id=iid,defect_type_id=did,remark=payload.get('remark')));count+=1
                result=dict(ok=True,count=count)
            elif p.path=='/api/rename-image':
                image=execute(c,'SELECT asset_id FROM images WHERE id=?',(int(payload['image_id']),)).fetchone()
                if not image:raise ValueError('图片不存在')
                a,path=local_asset(c,image['asset_id']);name=safe_filename(payload.get('stem',payload.get('name','')))
                if 'stem' in payload:name=safe_filename(name+path.suffix)
                if Path(name).suffix.lower()!=path.suffix.lower():raise ValueError('重命名时请保留原图片扩展名')
                dest=UPLOADS/(uuid.uuid4().hex+'_'+name)
                path.rename(dest);renamed.append((path,dest))
                execute(c,'UPDATE assets SET file_name=?,relative_path=?,updated_by=?,updated_at=? WHERE id=?',(name,dest.name,getattr(ACTOR,'username',None) or 'system',datetime.now(timezone.utc).isoformat(timespec='microseconds'),a['id']))
                ACTOR.storage_dirty=True
                result=dict(ok=True,name=name)
            elif p.path=='/api/local-engineering':
                path=str(payload.get('local_path','')).strip().strip('"')
                import ntpath
                if not (ntpath.isabs(path) or Path(path).is_absolute()) or len(path)>1024:raise ValueError('请填写完整本地路径，例如 D:\\AOI\\项目工程')
                aid=save(c,'assets',dict(asset_type='engineering',file_name=ntpath.basename(path.rstrip('\\/')) or '本地工程',storage_mode='file',status='unverified'))
                eid=save(c,'engineering_projects',dict(asset_id=aid,name=payload.get('name') or ntpath.basename(path),local_path=path,engineering_version=payload.get('engineering_version') or 'v1',image_count=payload.get('image_count')))
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
                    self.require(c,True)
                    if old:execute(c,'DELETE FROM asset_relations WHERE id=?',(old['id'],))
                elif not old:save(c,'asset_relations',dict(source_asset_id=en['asset_id'],target_asset_id=image['asset_id'],relation_type='paired'))
                result=dict(ok=True)
            elif p.path=='/api/knowledge/save':
                t=payload['table']
                if t not in ('technical_experiences','model_tests'):raise ValueError('不支持的知识录入类型')
                rid=payload.get('id');record=dict(payload['record'])
                if rid:
                    old=execute(c,f'SELECT * FROM `{t}` WHERE id=?',(rid,)).fetchone()
                    if not old:raise ValueError('记录不存在')
                    if 'expected_updated_at' not in payload or old['updated_at']!=payload['expected_updated_at']:raise ConflictError('记录已被修改，请刷新后重新编辑')
                    if t=='model_tests' and not payload.get('recapture_snapshot'):record['parameter_snapshot']=old['parameter_snapshot']
                links=payload.get('links',[])
                if not isinstance(links,list) or len(links)>200:raise ValueError('每条记录最多关联 200 个对象')
                if t=='model_tests' and (not record.get('parameter_snapshot') or payload.get('recapture_snapshot')):
                    from knowledge_graph import entity
                    devices=[entity(c,execute,'technical_objects',link['target_id']) for link in links if link.get('relation')=='使用设备' and link.get('target_table')=='technical_objects']
                    record['parameter_snapshot']=json.dumps({'设备':devices,'记录参数':{k:record.get(k) for k in ('model_name','model_version','light_source','camera','lens','working_distance_mm','prompt')},'保存时间':datetime.now(timezone.utc).isoformat()},ensure_ascii=False)
                ACTOR.recapture_snapshot=bool(payload.get('recapture_snapshot'))
                rid=save(c,t,record,rid)
                execute(c,'DELETE FROM knowledge_links WHERE source_table=? AND source_id=?',(t,rid))
                for link in links:save(c,'knowledge_links',{**link,'source_table':t,'source_id':rid})
                if t=='technical_experiences' and record.get('confirmation_status')=='已验证' and not any(link.get('relation')=='测试依据' for link in links):raise ValueError('已验证的经验请提供测试依据')
                result=dict(ok=True,id=rid)
            elif p.path=='/api/save':
                t=payload['table']
                if t not in TABLES:raise ValueError('未知表')
                if payload.get('id') and 'expected_updated_at' in payload:
                    current=execute(c,f'SELECT updated_at FROM `{t}` WHERE id=?',(payload['id'],)).fetchone()
                    if not current or current['updated_at']!=payload['expected_updated_at']:raise ConflictError('记录已被其他人修改，请刷新后重新编辑，避免覆盖他人的内容')
                rid=save(c,t,payload['record'],payload.get('id'));result=dict(ok=True,id=rid)
            elif p.path=='/api/delete':
                t=payload['table']
                if t not in TABLES:raise ValueError('未知表')
                if t=='knowledge_links':
                    link=execute(c,'SELECT source_table,source_id FROM knowledge_links WHERE id=?',(int(payload['id']),)).fetchone()
                    if link and link['source_table'] in ('technical_experiences','model_tests'):ACTOR.knowledge_checks.add((link['source_table'],link['source_id']))
                if t in ('materials','process_types','model_tests','technical_experiences','technical_objects','products','product_categories','defect_types','projects','technical_agreements','videos','assets','images','engineering_projects','after_sales'):
                    referenced=execute(c,'SELECT id FROM knowledge_links WHERE (target_table=? AND target_id=?) OR evidence_test_id=? OR evidence_document_id=?',(t,int(payload['id']),int(payload['id']) if t=='model_tests' else -1,int(payload['id']) if t=='technical_agreements' else -1)).fetchone()
                    if referenced:raise ValueError('该对象仍被知识关联引用，请先解除关联')
                    execute(c,'DELETE FROM knowledge_links WHERE source_table=? AND source_id=?',(t,int(payload['id'])))
                    execute(c,'DELETE FROM entity_aliases WHERE entity_table=? AND entity_id=?',(t,int(payload['id'])))
                if t=='technical_experiences':execute(c,'DELETE FROM technical_experience_files WHERE experience_id=?',(int(payload['id']),))
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
            commit_write(c,self);self.reply(result)
        except Exception as e:
            if c:c.rollback()
            for old,new in reversed(renamed):
                if new.exists():old.parent.mkdir(parents=True,exist_ok=True);new.rename(old)
            for f in created:f.unlink(missing_ok=True)
            self.reply({'error':str(e)},403 if isinstance(e,PermissionError) else 409 if isinstance(e,ConflictError) else 400)
        finally:
            if c:c.close()
            if write_locked:WRITE_LOCK.release()
def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default=os.environ.get('HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=PORT)
    parser.add_argument('--no-browser',action='store_true')
    args,_=parser.parse_known_args()
    initialize();host=args.host;port=args.port
    server=CatalogServer((host,port),Handler)
    from media_preview import backfill_previews
    preview_stop=threading.Event()
    def fill_covers():
        try:
            result=backfill_previews(connect,execute,UPLOADS,THUMBS,preview_stop)
            print('Document covers: '+json.dumps({k:v for k,v in result.items() if k!='items'},ensure_ascii=False),flush=True)
        except Exception:print('Document cover generation deferred; previews will retry when opened.',flush=True)
    threading.Thread(target=fill_covers,name='document-covers',daemon=True).start()
    print(f'AOI Catalog: http://127.0.0.1:{port} | {"MySQL" if MYSQL else "SQLite"}',flush=True)
    if not args.no_browser:webbrowser.open(f'http://127.0.0.1:{port}')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        preview_stop.set()
        server.server_close()
        if OFFLINE_ENGINE:OFFLINE_ENGINE.close()
if __name__=='__main__':main()
