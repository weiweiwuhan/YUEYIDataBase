"""Readable, collision-free on-disk catalog paths; legacy paths remain readable."""
import re
from pathlib import Path
VIDEO_EXT={'.mp4','.webm','.mov','.avi','.mkv','.m4v'}
IMAGE_EXT={'.png','.bmp','.jpg','.jpeg','.tif','.tiff','.webp','.gif'}
def filename(title,suffix=''):
    title=str(title or '未命名').strip()
    if suffix and not title.lower().endswith(suffix.lower()):title+=suffix
    title=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',title).rstrip('. ') or '未命名'
    ext=Path(title).suffix;stem=Path(title).stem[:150]
    if stem.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:stem='_'+stem
    return stem+ext

def sync_files(c,execute,root,renamed):
    """Called under the write lock; caller rolls DB and file moves back together."""
    root=Path(root).resolve()
    assets={r['id']:dict(r) for r in execute(c,'SELECT * FROM assets').fetchall()}
    videos=[dict(r) for r in execute(c,'SELECT * FROM videos').fetchall()]
    docs={r['id']:dict(r) for r in execute(c,'SELECT * FROM technical_agreements').fetchall()}
    doc_names={}
    for r in execute(c,'SELECT * FROM agreement_files').fetchall():
        if r['agreement_id'] in docs:doc_names[r['asset_id']]=docs[r['agreement_id']]['name']
    video_assets={r['asset_id']:r for r in videos if r.get('asset_id')}
    def move(oldrel,newrel):
        if not oldrel:return False
        old=(root/oldrel).resolve();new=(root/newrel).resolve()
        if not old.is_relative_to(root) or not new.is_relative_to(root):raise ValueError('文件路径无效')
        if old==new:return old.is_file()
        if not old.is_file():return False
        new.parent.mkdir(parents=True,exist_ok=True)
        if new.exists():raise ValueError('归档目标已有文件，请检查数据目录')
        old.rename(new);renamed.append((old,new));return True
    for aid,a in assets.items():
        if a['storage_mode']!='file' or not a.get('relative_path'):continue
        oldrel=a['relative_path'];ext=Path(oldrel).suffix
        title=video_assets[aid]['name'] if aid in video_assets else doc_names.get(aid,a['file_name'])
        name=filename(title,ext)
        kind='videos' if ext.lower() in VIDEO_EXT else 'images' if a['asset_type']=='image' else 'documents' if a['asset_type']=='document' else 'engineering' if a['asset_type']=='engineering' else 'archives' if a['asset_type']=='archive' else 'other'
        rel=f'{kind}/{aid}/{name}'
        if move(oldrel,rel):
            execute(c,'UPDATE assets SET file_name=?,relative_path=? WHERE id=?',(name,rel,aid));a.update(file_name=name,relative_path=rel)
    for v in videos:
        if v.get('asset_id') and v['asset_id'] in assets:
            a=assets[v['asset_id']]
            execute(c,'UPDATE videos SET file_name=?,relative_path=? WHERE id=?',(a['file_name'],a['relative_path'],v['id']))
        elif v.get('relative_path'):
            name=filename(v['name'],Path(v['relative_path']).suffix);rel=f'videos/legacy-{v["id"]}/{name}'
            if move(v['relative_path'],rel):execute(c,'UPDATE videos SET file_name=?,relative_path=? WHERE id=?',(name,rel,v['id']))
