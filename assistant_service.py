"""Bridge approved business experiences and imported local Q&A into the RAG index."""
import hashlib,json,os,threading,uuid
from pathlib import Path
from rag_assistant import RagAssistant,MAX_DOCUMENTS,MAX_INDEX_CHARS
from experience_import import prepare_import,knowledge_documents

class AssistantService:
    def __init__(self,data_dir,connect,execute):
        self.root=Path(data_dir)/'rag';self.root.mkdir(parents=True,exist_ok=True)
        self.connect=connect;self.execute=execute;self.lock=threading.RLock();self.rag=RagAssistant(data_dir)
        self.knowledge_file=self.root/'knowledge_sources.json';self.sync_file=self.root/'source_sync.json'
        self.sync_hash=None
        try:self.sync_hash=json.loads(self.sync_file.read_text('utf-8'))['hash']
        except (OSError,ValueError,KeyError):pass
    def _write(self,path,value):
        temp=path.with_name(uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(path)
    def _knowledge(self):
        if not self.knowledge_file.exists():return []
        docs=json.loads(self.knowledge_file.read_text('utf-8'))
        if not isinstance(docs,list):raise ValueError('本地知识源文件格式不正确')
        return docs
    @staticmethod
    def _chunks(documents):
        result=[]
        for doc in documents:
            text=doc['text']
            if len(text)<=6000:result.append(doc);continue
            for part,start in enumerate(range(0,len(text),5800),1):
                result.append({**doc,'id':str(doc['id'])+':part'+str(part),'text':text[start:start+6000]})
        return result
    def _sources(self,knowledge_override=None):
        c=self.connect()
        try:
            projects={r['id']:r['name'] for r in self.execute(c,'SELECT id,name FROM projects').fetchall()}
            products={r['id']:r['name'] for r in self.execute(c,'SELECT id,name FROM products').fetchall()}
            experiences=[dict(r) for r in self.execute(c,'SELECT * FROM after_sales ORDER BY id').fetchall()]
            technical=[dict(r) for r in self.execute(c,'SELECT * FROM technical_experiences ORDER BY id').fetchall()]
            attachments=[dict(r) for r in self.execute(c,"SELECT f.experience_id,a.file_name AS name FROM technical_experience_files f JOIN assets a ON a.id=f.asset_id UNION ALL SELECT f.experience_id,v.name FROM technical_experience_files f JOIN videos v ON v.id=f.video_id ORDER BY experience_id,name").fetchall()]
        finally:c.close()
        docs=self._knowledge() if knowledge_override is None else list(knowledge_override);knowledge_count=len(docs);solved=0
        for r in experiences:
            if r['status']!='已解决' or not (r.get('resolution') or r.get('experience')):continue
            parts=[('项目',projects.get(r['project_id'],'')),('产品',products.get(r['product_id'],'')),('问题',r['name']),('现象',r.get('symptom')),('原因',r.get('cause')),('处理方案',r.get('resolution')),('经验与预防',r.get('experience')),('备注',r.get('remark'))]
            docs.append({'id':'after_sales:'+str(r['id']),'source_type':'after_sales','source_id':r['id'],'title':r['name'],'text':'\n'.join(f'{k}：{v}' for k,v in parts if v),'category':'售后经验','created_by':r.get('created_by') or ''})
            solved+=1
        files_by_experience={}
        for attachment in attachments:files_by_experience.setdefault(attachment['experience_id'],[]).append(attachment['name'])
        for r in technical:
            parts=[('分类',r.get('category')),('关键词',r.get('tags')),('规范与经验',r.get('content')),('备注',r.get('remark')),('关联资料','、'.join(files_by_experience.get(r['id'],[])))]
            docs.append({'id':'technical_experiences:'+str(r['id']),'source_type':'technical_experiences','source_id':r['id'],'title':r['name'],'text':'\n'.join(f'{k}：{v}' for k,v in parts if v),'category':r.get('category') or '技术经验','created_by':r.get('created_by') or ''})
        docs=self._chunks(docs)
        if len(docs)>MAX_DOCUMENTS or sum(len(d['text'])+len(d['title']) for d in docs)>MAX_INDEX_CHARS:raise ValueError('知识库超过当前索引容量，请分库维护或清理不再使用的资料')
        fingerprint=hashlib.sha256(json.dumps(docs,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        return docs,fingerprint,{'after_sales_count':solved,'knowledge_count':knowledge_count,'technical_experience_count':len(technical)}
    def status(self):
        with self.lock:
            docs,fingerprint,counts=self._sources();status=self.rag.status()
            return {**status,'index_version':status.get('version'),**counts,'dirty':fingerprint!=self.sync_hash,'source_documents':len(docs)}
    def rebuild(self):
        with self.lock:
            docs,fingerprint,counts=self._sources();self.rag.rebuild(docs)
            self._write(self.sync_file,{'hash':fingerprint});self.sync_hash=fingerprint
            return {**self.rag.status(),'index_version':self.rag.status().get('version'),**counts,'dirty':False}
    def ensure_current(self):
        # Refreshes from authoritative sources, including edits and deletions; no stale append-only index.
        with self.lock:
            docs,fingerprint,counts=self._sources()
            if fingerprint!=self.sync_hash or not self.rag.status().get('documents') and docs:
                self.rag.rebuild(docs);self._write(self.sync_file,{'hash':fingerprint});self.sync_hash=fingerprint
    def chat(self,user,question,conversation_id=None):
        self.ensure_current();return self.rag.chat(user,question,conversation_id)
    def import_knowledge(self,user,content,filename):
        incoming=knowledge_documents(content,filename)
        with self.lock:
            existing=self._knowledge();known={str(d['id']) for d in existing};added=[];duplicates=0
            for doc in incoming:
                if str(doc['id']) in known:duplicates+=1;continue
                added.append({**doc,'created_by':user['username'],'source_filename':filename});known.add(str(doc['id']))
            documents,_,_=self._sources(existing+added)
            self.rag._normalize_documents(documents)  # Validate every field before publishing source changes.
            self._write(self.knowledge_file,existing+added)
            try:status=self.rebuild();updated=True
            except (OSError,ValueError):status=self.status();status['warning']='知识源已保存，但索引更新失败，请点击更新知识索引重试';updated=False
            return {'imported':len(added),'duplicates':duplicates,'index_updated':updated,'status':status}

def import_plan(connect,execute,content,filename,defaults):
    c=connect()
    try:
        projects=[dict(r) for r in execute(c,'SELECT id,name,code FROM projects').fetchall()]
        products=[dict(r) for r in execute(c,'SELECT id,name,code FROM products').fetchall()]
        existing=[dict(r) for r in execute(c,'SELECT * FROM after_sales').fetchall()]
        return prepare_import(content,filename,projects,products,existing,defaults)
    finally:c.close()
