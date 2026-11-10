"""Cached document first pages and video frames; original files stay untouched."""
from pathlib import Path
import hashlib, io, json, os, shutil, subprocess, tempfile, threading, time, uuid
from catalog_storage import VIDEO_EXT

OFFICE_EXT={'.doc','.docx','.docm','.odt','.rtf','.ppt','.pptx','.pptm','.odp','.xls','.xlsx','.ods'}
DOCUMENT_EXT=OFFICE_EXT|{'.pdf'}
_LOCKS=[threading.Lock() for _ in range(32)]
_OFFICE_SLOTS=threading.BoundedSemaphore(2)

def office_binary():
    configured=os.environ.get('AOI_SOFFICE')
    if configured:return shutil.which(configured) or (configured if Path(configured).is_file() else None)
    for name in ('soffice','libreoffice','soffice.com','soffice.exe'):
        found=shutil.which(name)
        if found:return found
    for base in (os.environ.get('PROGRAMFILES'),os.environ.get('PROGRAMFILES(X86)'),'/Applications'):
        if base:
            for suffix in ('LibreOffice/program/soffice.exe','LibreOffice.app/Contents/MacOS/soffice'):
                candidate=Path(base)/suffix
                if candidate.is_file():return str(candidate)
    return None

def _pdf_image(path):
    from PIL import Image
    try:
        import pymupdf
    except ImportError:
        if not shutil.which('pdftoppm'):raise ValueError('请安装 requirements.txt 中的 PyMuPDF 以生成 PDF 首页封面')
        with tempfile.TemporaryDirectory(prefix='aoi-pdf-') as folder:
            target=Path(folder)/'first'
            subprocess.run(['pdftoppm','-f','1','-l','1','-singlefile','-scale-to','1000','-png',str(path),str(target)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30,check=True)
            with Image.open(target.with_suffix('.png')) as image:return image.convert('RGB')
    with pymupdf.open(path) as document:
        if document.needs_pass or not len(document):raise ValueError('文档加密或没有可显示的页面')
        page=document[0];scale=min(1000/max(page.rect.width,page.rect.height),2)
        pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
        return Image.frombytes('RGB',(pix.width,pix.height),pix.samples)

def _office_image(path):
    binary=office_binary()
    if not binary:raise ValueError('服务器未安装 LibreOffice；安装后将自动生成 Word / PPT 首页封面')
    with tempfile.TemporaryDirectory(prefix='aoi-office-') as folder:
        root=Path(folder);profile=(root/'profile').as_uri()
        with _OFFICE_SLOTS:
            subprocess.run([binary,'-env:UserInstallation='+profile,'--headless','--nologo','--nodefault','--norestore','--convert-to','pdf','--outdir',str(root),str(path)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=90,check=True)
        pdf=root/(path.stem+'.pdf')
        if not pdf.is_file():raise ValueError('Office 文档无法转换，请检查文件是否损坏或加密')
        return _pdf_image(pdf)

def _placeholder(path,title):
    from PIL import Image,ImageDraw,ImageFont
    image=Image.new('RGB',(640,360),'#14243a');draw=ImageDraw.Draw(image)
    fontpath=next((p for p in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','C:/Windows/Fonts/msyh.ttc','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf') if Path(p).is_file()),None)
    font=ImageFont.truetype(fontpath,24) if fontpath else ImageFont.load_default()
    draw.text((36,38),path.suffix.upper().lstrip('.')+(' VIDEO' if path.suffix.lower() in VIDEO_EXT else ' DOCUMENT'),fill='#53d7cd',font=font)
    for number,start in enumerate(range(0,min(len(title),60),20)):draw.text((36,110+number*36),title[start:start+20],fill='#e4edf9',font=font)
    draw.text((36,290),'首页预览暂不可用，可上传自定义封面',fill='#a4b8d0',font=font)
    return image

def render_preview(path,thumbs,title):
    from PIL import Image,ImageOps
    stat=path.stat();key=hashlib.sha256(('first-page-v2:'+str(path)+':'+str(stat.st_mtime_ns)+':'+str(stat.st_size)+':'+title).encode()).hexdigest()
    cache=Path(thumbs)/('preview-'+key+'.jpg');metadata=cache.with_suffix('.json')
    with _LOCKS[int(key[:8],16)%len(_LOCKS)]:
        if cache.is_file() and metadata.is_file():
            try:
                info=json.loads(metadata.read_text('utf-8'))
                if info['kind']!='placeholder' or time.time()-cache.stat().st_mtime<60:return cache.read_bytes(),info
            except (OSError,ValueError,KeyError):pass
        kind,reason,image='image','',None
        try:
            suffix=path.suffix.lower()
            if suffix=='.pdf':image,kind=_pdf_image(path),'pdf_first_page'
            elif suffix in OFFICE_EXT:image,kind=_office_image(path),'office_first_page'
            elif suffix in VIDEO_EXT:
                with tempfile.TemporaryDirectory(prefix='aoi-video-') as folder:
                    target=Path(folder)/'first.png'
                    subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(path),'-frames:v','1','-vf','scale=640:400:force_original_aspect_ratio=decrease','-y',str(target)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20,check=True)
                    with Image.open(target) as original:image=original.convert('RGB')
                kind='video_first_frame'
            else:
                with Image.open(path) as original:original.seek(0);image=ImageOps.exif_transpose(original).convert('RGB')
        except Exception as error:
            reason=str(error) if isinstance(error,ValueError) else '原文件暂时无法生成首页预览'
        if image is None:image,kind=_placeholder(path,title),'placeholder'
        image.thumbnail((640,640));out=io.BytesIO();image.save(out,format='JPEG',quality=87)
        info={'kind':kind,'reason':reason};Path(thumbs).mkdir(parents=True,exist_ok=True)
        for destination,content in ((cache,out.getvalue()),(metadata,json.dumps(info,ensure_ascii=False).encode())):
            temporary=destination.with_name(uuid.uuid4().hex+'.tmp')
            try:temporary.write_bytes(content);temporary.replace(destination)
            finally:temporary.unlink(missing_ok=True)
        return out.getvalue(),info

def preview_bytes(c,execute,uploads,thumbs,table,rid):
    if table not in ('assets','videos'):raise ValueError('预览对象无效')
    row=execute(c,f'SELECT * FROM `{table}` WHERE id=?',(rid,)).fetchone()
    if not row:raise ValueError('资料不存在')
    record=dict(row)
    if record.get('preview_asset_id'):
        cover=execute(c,'SELECT * FROM assets WHERE id=?',(record['preview_asset_id'],)).fetchone()
        if cover:record=dict(cover)
    root=Path(uploads).resolve();path=(root/(record.get('relative_path') or '')).resolve()
    if not path.is_relative_to(root) or not path.is_file() or record.get('storage_mode','file')!='file':raise ValueError('预览原文件不存在')
    content,_=render_preview(path,thumbs,record.get('name') or record.get('file_name') or '资料封面')
    return content,'image/jpeg'

def backfill_previews(connect,execute,uploads,thumbs,stop=None):
    """Generate existing covers without changing record IDs or user covers."""
    connection=connect()
    try:records=[dict(r) for r in execute(connection,"SELECT * FROM assets WHERE asset_type='document' AND preview_asset_id IS NULL ORDER BY id").fetchall()]
    finally:connection.close()
    report={'generated':0,'unavailable':0,'skipped':0,'items':[]};root=Path(uploads).resolve()
    for record in records:
        if stop and stop.is_set():break
        path=(root/(record.get('relative_path') or '')).resolve()
        if record['storage_mode']!='file' or not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in DOCUMENT_EXT:report['skipped']+=1;continue
        try:
            _,info=render_preview(path,thumbs,record.get('file_name') or path.name)
            report['generated' if info['kind']!='placeholder' else 'unavailable']+=1;report['items'].append({'asset_id':record['id'],**info})
        except OSError:
            report['unavailable']+=1;report['items'].append({'asset_id':record['id'],'kind':'unavailable','reason':'文件在生成期间被移动或删除'})
    return report
