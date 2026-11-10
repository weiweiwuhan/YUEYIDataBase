"""User covers and optional first-page/frame thumbnails, with a readable fallback."""
from pathlib import Path
import hashlib,io,shutil,subprocess,uuid
from catalog_storage import VIDEO_EXT

def preview_bytes(c,execute,uploads,thumbs,table,rid):
    if table not in ('assets','videos'):raise ValueError('预览对象无效')
    row=execute(c,f'SELECT * FROM `{table}` WHERE id=?',(rid,)).fetchone()
    if not row:raise ValueError('资料不存在')
    r=dict(row)
    if r.get('preview_asset_id'):
        cover=execute(c,'SELECT * FROM assets WHERE id=?',(r['preview_asset_id'],)).fetchone()
        if cover:r=dict(cover)
    path=(Path(uploads)/(r.get('relative_path') or '')).resolve();root=Path(uploads).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('预览原文件不存在')
    from PIL import Image,ImageOps,ImageDraw,ImageFont
    key=hashlib.sha256((str(path)+str(path.stat().st_mtime_ns)+str(r.get('file_name'))).encode()).hexdigest();cache=Path(thumbs)/('preview-'+key+'.jpg')
    if cache.is_file():return cache.read_bytes(),'image/jpeg'
    try:
        with Image.open(path) as original:
            original.seek(0);im=ImageOps.exif_transpose(original).convert('RGB');im.thumbnail((640,400))
    except (OSError,ValueError):
        im=None
        temp=Path(thumbs)/('preview-'+key+'-'+uuid.uuid4().hex+'.png')
        cmd=None
        if path.suffix.lower() in VIDEO_EXT and shutil.which('ffmpeg'):
            cmd=['ffmpeg','-v','error','-nostdin','-i',str(path),'-frames:v','1','-vf','scale=640:400:force_original_aspect_ratio=decrease','-y',str(temp)]
        elif path.suffix.lower()=='.pdf' and shutil.which('pdftoppm'):
            cmd=['pdftoppm','-f','1','-singlefile','-scale-to','640','-png',str(path),str(temp.with_suffix(''))]
        if cmd:
            try:
                subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12,check=True)
                with Image.open(temp) as original:im=original.convert('RGB')
            except (OSError,ValueError,subprocess.SubprocessError):pass
            finally:temp.unlink(missing_ok=True)
        if im is None:
            im=Image.new('RGB',(640,360),'#14243a');d=ImageDraw.Draw(im)
            fontpath=next((p for p in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','C:/Windows/Fonts/msyh.ttc','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf') if Path(p).is_file()),None)
            font=ImageFont.truetype(fontpath,24) if fontpath else ImageFont.load_default()
            text=r.get('name') or r.get('file_name') or '资料封面';lines=[text[i:i+20] for i in range(0,min(len(text),60),20)]
            d.text((36,38),path.suffix.upper().lstrip('.')+' DOCUMENT' if path.suffix.lower() not in VIDEO_EXT else 'VIDEO',fill='#53d7cd',font=font)
            for i,line in enumerate(lines):d.text((36,110+i*36),line,fill='#e4edf9',font=font)
            d.text((36,290),'上传封面以补充图片预览',fill='#a4b8d0',font=font)
    out=io.BytesIO();im.save(out,format='JPEG',quality=85)
    temp_cache=cache.with_name(uuid.uuid4().hex+'.tmp')
    try:temp_cache.write_bytes(out.getvalue());temp_cache.replace(cache)
    finally:temp_cache.unlink(missing_ok=True)
    return out.getvalue(),'image/jpeg'
