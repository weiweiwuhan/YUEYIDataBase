"""Durable, owner-scoped local inference queue; model execution runs outside the web process."""
import copy,json,math,os,queue,re,shutil,subprocess,sys,threading,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image,ImageDraw

TERMINAL={'completed','completed_with_errors','failed','cancelled','interrupted'}
MAX_FILES=200
MAX_FILE=32*1024*1024

def stamp():return datetime.now(timezone.utc).isoformat()
def atomic_json(path,value):
    tmp=path.with_name(uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(path)
def parameters(value):
    if not isinstance(value,dict):raise ValueError('阈值参数格式不正确')
    result={'seg_threshold':.06,'image_threshold':None,'min_area':8,'alpha':.5,'smooth_sigma':1.2}
    if set(value)-set(result):raise ValueError('未知分割参数')
    result.update(value)
    for key in ('seg_threshold','image_threshold','alpha','smooth_sigma'):
        if key=='image_threshold' and result[key] is None:continue
        if isinstance(result[key],bool):raise ValueError('阈值必须是有限数值')
        result[key]=float(result[key])
        if not math.isfinite(result[key]) or result[key]<0:raise ValueError('阈值必须是非负有限数值')
    if not 0<=result['alpha']<=1 or result['smooth_sigma']>10:raise ValueError('透明度须为 0–1，平滑参数须为 0–10')
    if isinstance(result['min_area'],bool) or int(result['min_area'])!=float(result['min_area']) or not 1<=int(result['min_area'])<=20000000:raise ValueError('最小缺陷面积须为正整数')
    result['min_area']=int(result['min_area']);return result

class Runner:
    def __init__(self,model,runner_path,folder,on_start=None):
        config=folder/'runner-model.json';atomic_json(config,model)
        self.close_lock=threading.Lock();self.log=(folder/'runner.log').open('ab');self.messages=queue.Queue()
        self.process=subprocess.Popen([model['python'],str(runner_path),'--model-json',str(config),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,encoding='utf-8',bufsize=1,cwd=model.get('project_dir') if model.get('backend')=='dinov3' else None,env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1'})
        def read():
            try:
                for line in self.process.stdout:
                    try:self.messages.put(json.loads(line))
                    except (ValueError,TypeError):continue
            finally:self.messages.put({'ok':False,'error':'模型进程已退出，请检查本机模型环境及 runner.log'})
        threading.Thread(target=read,daemon=True).start()
        if on_start:on_start(self)
        try:
            value=self.messages.get(timeout=float(model.get('load_timeout',180)))
            if not value.get('ready'):raise ValueError(value.get('error','模型加载失败'))
        except Exception:self.close();raise
    def predict(self,image,output):
        if self.process.poll() is not None:raise ValueError('模型进程已退出')
        self.process.stdin.write(json.dumps({'input':str(image),'output':str(output)},ensure_ascii=False)+'\n');self.process.stdin.flush()
        try:result=self.messages.get(timeout=180)
        except queue.Empty:self.close();raise ValueError('单图预测超过 180 秒，已停止模型进程')
        if not result.get('ok'):raise ValueError(result.get('error','模型预测失败'))
        score=float(result['image_score'])
        if not math.isfinite(score):raise ValueError('模型返回了无效的图像分数')
        return score
    def close(self):
        with self.close_lock:
            if getattr(self,'process',None):
                if self.process.poll() is None:
                    self.process.terminate()
                    try:self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
                for stream in (self.process.stdin,self.process.stdout):
                    if stream:stream.close()
            if getattr(self,'log',None):self.log.close()

def render(image_path,map_path,folder,params,score):
    import numpy as np
    from scipy.ndimage import gaussian_filter,label,find_objects
    if map_path.stat().st_size>64*1024*1024:raise ValueError('模型分割图过大')
    raw=np.load(map_path,allow_pickle=False)
    if raw.ndim!=2 or not raw.size or raw.size>16000000 or not np.isfinite(raw).all():raise ValueError('模型必须返回有限数值的二维分割分数图')
    scores=raw.astype('float32')
    if params['smooth_sigma']:scores=gaussian_filter(scores,params['smooth_sigma'])
    with Image.open(image_path) as image:original=image.convert('RGB')
    up=np.asarray(Image.fromarray(scores).resize(original.size,Image.Resampling.BILINEAR))
    mask=up>params['seg_threshold']
    if params['image_threshold'] is not None and score<params['image_threshold']:mask[:]=False
    labels,count=label(mask);sizes=np.bincount(labels.ravel());keep=sizes>=params['min_area'];keep[0]=False;mask=keep[labels]
    # Bound preview metadata for pathological noisy maps; the full mask is retained.
    labels,regions=label(mask);boxes=[]
    for region in find_objects(labels,max_label=min(regions,2000)):
        if region is not None:
            ys,xs=region;boxes.append([xs.start,ys.start,xs.stop,ys.stop])
    rgb=np.array(original);blend=rgb.copy();alpha=params['alpha']
    blend[mask]=((1-alpha)*rgb[mask]+alpha*np.array([255,0,0])).astype('uint8')
    overlay=Image.fromarray(blend);draw=ImageDraw.Draw(overlay)
    for box in boxes:draw.rectangle([box[0],box[1],max(box[0],box[2]-1),max(box[1],box[3]-1)],outline='red',width=max(1,min(original.size)//250))
    # Versioned output names keep old previews valid while a new threshold is being applied.
    revision=uuid.uuid4().hex
    overlay_name='overlay-'+revision+'.png';mask_name='mask-'+revision+'.png'
    overlay.save(folder/overlay_name);Image.fromarray(mask.astype('uint8')*255).save(folder/mask_name)
    return {'image_score':score,'is_anomaly':bool(mask.any()),'defect_pixels':int(mask.sum()),'regions':int(regions),'bboxes':boxes,'bboxes_truncated':regions>2000,'width':original.width,'height':original.height,'params':params,'overlay_file':overlay_name,'mask_file':mask_name}

class OfflineQueue:
    def __init__(self,data_dir,registry_path=None,runner_path=None):
        self.root=Path(data_dir).resolve()/'offline_tests';self.root.mkdir(parents=True,exist_ok=True)
        self.registry=Path(registry_path or os.environ.get('AOI_OFFLINE_MODELS',str(Path(data_dir)/'offline_models.json'))).resolve()
        self.runner_path=Path(runner_path or Path(__file__).with_name('offline_runner.py')).resolve()
        self.lock=threading.RLock();self.condition=threading.Condition(self.lock);self.jobs={};self.uploading={};self.closed=False;self.active_runner=None
        for file in self.root.glob('*/job.json'):
            try:
                value=json.loads(file.read_text('utf-8'))
                if value['id']!=file.parent.name or not re.fullmatch(r'[0-9a-f]{32}',value['id']):continue
                if value['status']=='running':
                    value['status']='interrupted';value['error']='服务重启中断了预测，请重新提交图片'
                    for item in value['items']:
                        if item['status'] in ('running','uploaded'):item['status']='failed';item['error']='服务重启中断了预测'
                    atomic_json(file,value)
                self.jobs[value['id']]=value
            except (ValueError,KeyError,OSError,TypeError):continue
        self.thread=threading.Thread(target=self._work,name='offline-inference',daemon=True);self.thread.start()
    def _models(self):
        if not self.registry.is_file():return []
        content=json.loads(self.registry.read_text('utf-8-sig'))
        if not isinstance(content,dict) or not isinstance(content.get('defaults',{}),dict) or not isinstance(content.get('models',[]),list):raise ValueError('模型配置须包含 defaults 对象和 models 数组')
        defaults=content.get('defaults',{});entries=content.get('models',[])
        if content.get('checkpoint_dir'):
            directory=Path(content['checkpoint_dir']).expanduser()
            if not directory.is_absolute():directory=self.registry.parent/directory
            if directory.is_dir():
                for checkpoint in sorted(directory.iterdir()):
                    if checkpoint.is_file() and checkpoint.suffix.lower() in ('.pt','.pth'):
                        entries.append({'id':'model-'+uuid.uuid5(uuid.NAMESPACE_URL,str(checkpoint)).hex[:20],'name':checkpoint.stem,'checkpoint':str(checkpoint)})
        results=[];ids=set()
        for entry in entries:
            if not isinstance(entry,dict):raise ValueError('模型条目必须为对象')
            model={**defaults,**entry};model.setdefault('backend','dinov3');model.setdefault('python',sys.executable)
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',str(model.get('id',''))) or model['id'] in ids:raise ValueError('本地模型配置包含非法或重复编号')
            ids.add(model['id']);model.setdefault('name',model['id'])
            for key in ('project_dir','checkpoint','backbone_weights','python'):
                if model.get(key):
                    path=Path(model[key]).expanduser()
                    if key=='python' and not path.is_absolute():
                        found=shutil.which(str(path));path=Path(found) if found else self.registry.parent/path
                    elif not path.is_absolute():path=self.registry.parent/path
                    model[key]=str(path.absolute() if key=='python' else path.resolve())
            required=['python','checkpoint']+(['project_dir','backbone_weights'] if model['backend']=='dinov3' else [])
            missing=[key for key in required if not model.get(key) or not Path(model[key]).exists()]
            model['available']=not missing and model['backend'] in ('dinov3','torchscript')
            model['reason']='本机缺少：'+', '.join(missing) if missing else ''
            results.append(model)
        return results
    def models(self):
        try:return {'models':[{k:m[k] for k in ('id','name','available','reason')} for m in self._models()],'configured':self.registry.is_file()}
        except (OSError,ValueError,TypeError) as e:return {'models':[],'configured':False,'error':'本地模型配置读取失败：'+str(e)}
    def _save(self,job):atomic_json(self.root/job['id']/'job.json',job)
    def _owned(self,user,job_id):
        job=self.jobs.get(str(job_id))
        if not job:raise ValueError('测试任务不存在')
        if user.get('role')!='admin' and job['created_user_id']!=user['id']:raise PermissionError('只能访问自己的离线测试任务')
        return job
    def _public(self,job):
        result=copy.deepcopy(job);waiting=[j['id'] for j in self.jobs.values() if j['status']=='queued']
        result['queue_position']=waiting.index(job['id'])+1 if job['id'] in waiting else 0
        result.pop('model_config',None)
        for item in result['items']:
            for key in ('original_file','map_file'):item.pop(key,None)
            if item.get('result'):
                for key in ('overlay_file','mask_file'):item['result'].pop(key,None)
        return result
    def create(self,user,model_id,params):
        params=parameters(params)
        model=next((m for m in self._models() if m['id']==model_id),None)
        if not model or not model['available']:raise ValueError('所选模型在本机不可用，请检查模型目录及 Python 环境配置')
        with self.condition:
            active=[j for j in self.jobs.values() if j['status'] not in TERMINAL]
            if len(active)>=100 or sum(j['created_user_id']==user['id'] for j in active)>=10:raise ValueError('等待任务过多，请等待现有任务完成或取消后再提交')
            key=uuid.uuid4().hex;folder=self.root/key;folder.mkdir()
            job={'id':key,'model_id':model_id,'model_name':model['name'],'model_config':model,'params':params,'status':'uploading','created_user_id':user['id'],'created_by':user['username'],'created_at':stamp(),'items':[]}
            self._save(job);self.jobs[key]=job;return self._public(job)
    def upload(self,user,job_id,name,stream,size):
        if not isinstance(name,str) or not name or len(name)>191 or any(ord(c)<32 or c in '/\\<>:"|?*' for c in name) or name in ('.','..'):raise ValueError('图片文件名无效')
        if not 0<size<=MAX_FILE:raise ValueError('单张图片大小须为 1 字节至 32 MB')
        with self.lock:
            job=self._owned(user,job_id)
            if job['status']!='uploading':raise ValueError('任务已进入队列，不能继续添加图片')
            reserved=self.uploading.setdefault(job_id,{})
            if len(job['items'])+len(reserved)>=MAX_FILES or sum(i['size'] for i in job['items'])+sum(reserved.values())+size>512*1024*1024:raise ValueError('每批最多 200 张、512 MB')
            item_id=uuid.uuid4().hex;reserved[item_id]=size
        folder=self.root/job_id/item_id;folder.mkdir();path=folder/'original'
        try:
            remain=size
            with path.open('wb') as target:
                while remain:
                    block=stream.read(min(remain,1024*1024))
                    if not block:raise ValueError('图片上传不完整')
                    target.write(block);remain-=len(block)
            with Image.open(path) as image:
                if image.width*image.height>20000000:raise ValueError('单张图片最多 2000 万像素')
                if image.format not in ('PNG','JPEG','BMP','TIFF','WEBP'):raise ValueError('不支持的图片格式')
                image.verify()
            item={'id':item_id,'name':name,'size':size,'status':'uploaded','original_file':'original','created_by':user['username']}
            with self.lock:
                if job['status']!='uploading':raise ValueError('任务已取消或已提交，本张图片未加入任务')
                job['items'].append(item);self._save(job)
            return copy.deepcopy(item)
        except Exception:shutil.rmtree(folder,ignore_errors=True);raise
        finally:
            with self.lock:self.uploading[job_id].pop(item_id,None)
    def submit(self,user,job_id):
        with self.condition:
            job=self._owned(user,job_id)
            if self.uploading.get(job_id):raise ValueError('请等待图片上传完成后再提交')
            if job['status']!='uploading' or not job['items']:raise ValueError('请先上传图片，或任务已经提交')
            job['status']='queued';self._save(job);self.condition.notify();return self._public(job)
    def get(self,user,job_id):
        with self.lock:return self._public(self._owned(user,job_id))
    def list(self,user):
        with self.lock:return [self._public(j) for j in sorted(self.jobs.values(),key=lambda j:j['created_at'],reverse=True) if user.get('role')=='admin' or j['created_user_id']==user['id']][:30]
    def cancel(self,user,job_id):
        with self.condition:
            job=self._owned(user,job_id)
            if job['status'] not in TERMINAL:
                job['status']='cancelled'
                for item in job['items']:
                    if item['status']=='uploaded':item['status']='cancelled'
                self._save(job);self.condition.notify()
            return self._public(job)
    def file(self,user,job_id,item_id,kind):
        with self.lock:
            job=self._owned(user,job_id);item=next((i for i in job['items'] if i['id']==item_id),None)
            if not item:raise ValueError('图片不存在')
            name=item['original_file'] if kind=='original' else item.get('result',{}).get(kind+'_file') if kind in ('overlay','mask') else None
            if not name:raise ValueError('结果尚未生成')
            path=self.root/job_id/item_id/name
            if not path.is_file():raise ValueError('图片文件不存在')
            return path
    def resegment(self,user,job_id,item_id,params):
        params=parameters(params)
        with self.lock:
            job=self._owned(user,job_id);item=next((i for i in job['items'] if i['id']==item_id),None)
            if not item or item['status']!='completed':raise ValueError('请先等待该图片预测完成')
            folder=self.root/job_id/item_id
            result=render(folder/'original',folder/'scores.npy',folder,params,item['result']['image_score']);result['inference_ms']=item['result']['inference_ms']
            item['result']=result;self._save(job);return self._public(job)['items'][job['items'].index(item)]
    def _register_runner(self,runner):
        with self.lock:self.active_runner=runner;closed=self.closed
        if closed:runner.close()
    def _work(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.closed or any(j['status']=='queued' for j in self.jobs.values()))
                if self.closed:return
                job=next(j for j in self.jobs.values() if j['status']=='queued');job['status']='running';self._save(job)
            runner=None
            try:
                runner=Runner(job['model_config'],self.runner_path,self.root/job['id'],on_start=self._register_runner)
                for item in job['items']:
                    with self.lock:
                        if self.closed:break
                        if job['status']=='cancelled':break
                        item['status']='running';self._save(job)
                    folder=self.root/job['id']/item['id'];start=time.perf_counter()
                    try:
                        score=runner.predict(folder/'original',folder/'scores.npy')
                        result=render(folder/'original',folder/'scores.npy',folder,job['params'],score);result['inference_ms']=round((time.perf_counter()-start)*1000,2)
                        with self.lock:item.update(status='completed',result=result)
                    except Exception as e:
                        with self.lock:item.update(status='failed',error=str(e))
                    with self.lock:self._save(job)
                with self.lock:
                    if self.closed:
                        job['status']='interrupted';job['error']='服务停止中断了任务'
                        for item in job['items']:
                            if item['status'] in ('uploaded','running'):item.update(status='failed',error='服务停止中断了任务')
                    elif job['status']!='cancelled':job['status']='completed_with_errors' if any(i['status']=='failed' for i in job['items']) else 'completed'
                    self._save(job)
            except Exception as e:
                with self.lock:
                    if job['status']!='cancelled':job['status']='interrupted' if self.closed else 'failed';job['error']=str(e)
                    for item in job['items']:
                        if item['status'] in ('uploaded','running'):item.update(status='failed',error=str(e))
                    self._save(job)
            finally:
                if runner:runner.close()
                self.active_runner=None
    def close(self):
        with self.condition:self.closed=True;self.condition.notify_all()
        if self.active_runner:self.active_runner.close()
        self.thread.join(timeout=10)
