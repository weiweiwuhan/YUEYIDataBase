import json
from pathlib import Path
from schema import T,ddl
s={t['name']:[] for t in T}
def put(t,**r):s[t].append(dict(id=len(s[t])+1,**r))
put('storage_locations',name='NAS 示例（请修改）',root_path='\\\\NAS\\工业资料')
put('product_categories',name='螺栓');put('product_categories',name='外六角螺栓',parent_id=1)
put('materials',name='不锈钢',remark='字典示例，不代表本项目材质')
put('process_types',name='镀锌');put('process_types',name='滚丝')
for name in ['裂纹','牙伤','牙底积液']:put('defect_types',name=name)
put('projects',code='DEMO-JJ-001',name='J吉螺栓项目 · 示例',customer_name='J吉',remark='演示数据，不对应真实 NAS 文件；界面统计按已登记记录计算。')
put('products',code='DEMO-BOLT-RANGE',name='外六角螺栓 · 规格待细分',category_id=2,spec_text='M4～M12',remark='材质未知，不填写材质；来自原始资料的规格范围。')
put('assets',asset_type='archive',file_name='缺陷样本.zip',storage_location_id=1,relative_path='J吉/缺陷样本.zip',storage_mode='file',status='unverified',remark='演示：包级包含裂纹、牙伤、牙底积液')
for i in range(1,4):
    put('assets',asset_type='image',file_name=f'{i:03}.bmp',storage_mode='archive_member',status='unverified')
    put('images',asset_id=i+1,width=2048,height=2048,channels=1,quality_label='NG' if i==1 else 'unknown',inspection_surface='侧面',station_name='CCD-2',annotation_status='reviewed' if i==1 else 'unlabeled')
    put('asset_relations',source_asset_id=1,target_asset_id=i+1,relation_type='contains',member_path=f'Src/{i:03}.bmp')
put('assets',asset_type='engineering',file_name='侧面检测工程.proj',storage_location_id=1,relative_path='J吉/工程/侧面检测工程.proj',storage_mode='file',status='unverified')
put('engineering_projects',asset_id=5,name='外六角螺栓侧面检测',software_name='AOI 检测软件',engineering_version='v1.0',remark='示例工程记录')
put('project_products',project_id=1,product_id=1)
for i in range(1,6):put('project_assets',project_id=1,asset_id=i);put('asset_products',asset_id=i,product_id=1)
put('product_processes',product_id=1,process_id=1)
put('image_defects',image_id=1,defect_type_id=1,remark='演示：仅 001.bmp 确认裂纹')
for i in range(1,4):put('asset_defects',asset_id=1,defect_type_id=i)
put('asset_relations',source_asset_id=5,target_asset_id=2,relation_type='paired')
Path(__file__).with_name('sample.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
Path(__file__).with_name('schema.mysql.sql').write_text(ddl(True),encoding='utf-8')
