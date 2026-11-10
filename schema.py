"""Single source for UI, SQLite and MySQL DDL. No destructive initialization."""
from knowledge_contract import RELATIONS,STATUS

def col(name,label,kind='text',required=False,ref=None,choices=None):
    field=dict(name=name,label=label,kind=kind,required=required,ref=ref,choices=choices)
    if kind in ('int','real','id'):
        field['minimum']=1 if kind=='id' else 0
    else:
        field['maxLength']=1024 if name in ('product_spec','prompt','requirements','symptom','cause','resolution','experience','remark','relative_path','member_path','root_path','thumbnail_path','local_path','evidence_locator') else 191
        if name in ('conditions','parameter_snapshot','acceptance_criteria','specification'):field['maxLength']=20000
        if name=='extracted_text':field['maxLength']=100000
    if name.endswith('_mm'):field['unit']='mm'
    if name in ('detection_rate','miss_rate','yield_rate'):field.update(maximum=100,unit='%')
    return field
def table(name,label,group,description,fields,unique=None):
    for field in fields:
        if (name=='technical_experiences' and field['name'] in ('content','remark')) or (name=='model_tests' and field['name'] in ('test_method','expected_result','actual_result')) or (name=='after_sales' and field['name'] in ('symptom','cause','resolution','experience','remark')):field['maxLength']=20000
    return dict(name=name,label=label,group=group,description=description,fields=[col('id','编号','id')]+fields,unique=unique or [])
T=[]
def add(*a,**k): T.append(table(*a,**k))
add('storage_locations','存储位置','配置','定义 NAS 根目录；资源只保存相对路径。',[col('name','位置名称',required=True),col('root_path','NAS 根目录',required=True)],unique=[['name']])
add('product_categories','产品分类','配置','parent_id 支持大类 → 细分的树形分类。',[col('name','分类名称',required=True),col('parent_id','上级分类','int',ref='product_categories')],unique=[['name']])
add('materials','材质字典','配置','未知材质留空，后期补录。',[col('name','材质名称',required=True),col('remark','备注')],unique=[['name']])
add('process_types','工艺字典','配置','先建立选项，再在产品工艺表中关联产品。',[col('name','工艺名称',required=True),col('remark','备注')],unique=[['name']])
add('defect_types','缺陷字典','配置','统一缺陷名称；登记选项不代表图片已有该缺陷。',[col('name','缺陷名称',required=True),col('remark','备注')],unique=[['name']])
add('projects','项目','主表','一个客户可有多个项目。',[col('code','项目编号',required=True),col('name','项目名称',required=True),col('customer_name','客户简称'),col('remark','备注')],unique=[['code']])
add('products','产品','主表','每条记录代表一种产品规格；未知规格可先写原始描述。',[col('code','内部兼容键'),col('name','产品名称',required=True),col('category_id','产品分类','int',ref='product_categories'),col('material_id','材质','int',ref='materials'),col('spec_text','规格描述'),col('diameter_mm','直径 mm','real'),col('length_mm','长度 mm','real'),col('remark','备注')],unique=[['code']])
add('assets','文件资源','主表','每个文件或压缩包成员是一个资源。NAS 文件登记路径，本地上传文件另存 data/uploads。',[col('asset_type','资源类型',required=True,choices=['image','archive','engineering','annotation','document','other']),col('preview_asset_id','封面图片','int',ref='assets'),col('file_name','文件名',required=True),col('storage_location_id','存储位置','int',ref='storage_locations'),col('relative_path','相对路径'),col('storage_mode','存储形式',required=True,choices=['file','archive_member']),col('file_size','大小 bytes','int'),col('sha256','SHA-256'),col('status','状态',required=True,choices=['available','unverified','missing','pending','failed']),col('remark','备注')])
add('images','图片','主表','通过 asset_id 一对一关联文件资源；未确认与 OK/NG 分开。',[col('asset_id','图片资源','int',True,'assets'),col('width','宽 px','int'),col('height','高 px','int'),col('channels','通道数','int'),col('quality_label','图片判定',required=True,choices=['unknown','OK','NG']),col('inspection_surface','检测面'),col('station_name','CCD 工位'),col('annotation_status','标注状态',required=True,choices=['unlabeled','labeled','reviewed']),col('thumbnail_path','缩略图路径')],unique=[['asset_id']])
add('engineering_projects','检测工程','主表','每次工程版本单独登记，并保留旧文件。',[col('asset_id','工程资源','int',True,'assets'),col('local_path','本地工程路径'),col('name','工程名称',required=True),col('image_count','工程图片数量','int'),col('software_name','软件名称'),col('software_version','软件版本'),col('engineering_version','工程版本'),col('remark','备注')],unique=[['asset_id']])
add('project_products','项目—产品','关系','项目和产品的多对多关系。',[col('project_id','项目','int',True,'projects'),col('product_id','产品','int',True,'products')],unique=[['project_id','product_id']])
add('project_assets','项目—资源','关系','每张需按项目检索的图片也应显式关联项目。',[col('project_id','项目','int',True,'projects'),col('asset_id','资源','int',True,'assets')],unique=[['project_id','asset_id']])
add('asset_products','资源—产品','关系','资源可关联多个产品；图片也应显式关联。',[col('asset_id','资源','int',True,'assets'),col('product_id','产品','int',True,'products')],unique=[['asset_id','product_id']])
add('product_processes','产品—工艺','关系','一个产品支持镀锌、滚丝等多个工艺。',[col('product_id','产品','int',True,'products'),col('process_id','工艺','int',True,'process_types')],unique=[['product_id','process_id']])
add('image_defects','图片—缺陷','关系','仅登记已确认的逐图缺陷。',[col('image_id','图片','int',True,'images'),col('defect_type_id','缺陷','int',True,'defect_types'),col('remark','确认说明')],unique=[['image_id','defect_type_id']])
add('asset_defects','资料包—缺陷','关系','表示包级包含这些缺陷，不会自动标为每张图片的缺陷。',[col('asset_id','资料资源','int',True,'assets'),col('defect_type_id','缺陷','int',True,'defect_types'),col('remark','说明')],unique=[['asset_id','defect_type_id']])
add('asset_relations','资源关联','关系','contains: 压缩包→成员；paired: 工程→图片；annotation: 图片→标注；version: 旧→新。',[col('source_asset_id','来源资源','int',True,'assets'),col('target_asset_id','目标资源','int',True,'assets'),col('relation_type','关系类型',required=True,choices=['contains','paired','annotation','version']),col('member_path','压缩包内路径')],unique=[['source_asset_id','target_asset_id','relation_type']])
add('image_embeddings','图像特征登记','扩展','预留向量索引登记；本版本不生成特征、不提供以图搜图。',[col('image_id','图片','int',True,'images'),col('model_name','模型',required=True),col('model_version','模型版本',required=True),col('dimension','特征维度','int',True),col('vector_key','向量索引键',required=True)],unique=[['image_id','model_name','model_version'],['vector_key']])
add('videos','视频资料','主表','项目视频可绑定项目，通用经验视频独立保存并复用文件资源。旧图片关联保留兼容。',[col('image_id','历史图片关联','int',False,'images'),col('project_id','绑定项目','int',False,'projects'),col('asset_id','视频资源','int',ref='assets'),col('preview_asset_id','封面图片','int',ref='assets'),col('name','视频名称',required=True),col('file_name','原文件名',required=True),col('relative_path','视频存储路径',required=True),col('file_size','大小 bytes','int'),col('remark','备注')])
add('technical_agreements','文档类型资料','主表','上传技术协议、操作说明、测试报告等技术文档，可独立保存或关联项目，并可关联多个产品。',[col('project_id','项目','int',False,'projects'),col('document_type','文档类型'),col('code','文档编号',required=True),col('name','文档名称',required=True),col('signed_date','文档日期'),col('requirements','文档说明'),col('extracted_text','文档信息读取'),col('remark','备注')],unique=[['code']])
add('agreement_products','文档—产品','关系','同一份文档可以对应多个产品。',[col('agreement_id','文档资料','int',True,'technical_agreements'),col('product_id','产品','int',True,'products')],unique=[['agreement_id','product_id']])
add('after_sales','售后经验','主表','绑定项目与产品，积累故障原因、处理过程及预防经验。',[col('project_id','项目','int',True,'projects'),col('product_id','产品','int',True,'products'),col('name','问题标题',required=True),col('service_date','售后日期'),col('status','处理状态',required=True,choices=['待处理','处理中','已解决']),col('symptom','问题现象'),col('cause','原因分析'),col('resolution','处理方案'),col('experience','经验与预防措施'),col('remark','备注')])
add('agreement_files','文档附件','关系','文档原文件保存在工程数据目录，可下载。',[col('agreement_id','文档资料','int',True,'technical_agreements'),col('asset_id','附件资源','int',True,'assets')],unique=[['asset_id']])
add('model_tests','软件测试记录','主表','按模块记录大模型、AI 检测稳定性、运行时间、算法重复误差等人工测试。',[col('name','测试名称',required=True),col('test_module','测试模块'),col('inspection_surface','检测面与测试范围'),col('acceptance_criteria','判定标准'),col('parameter_snapshot','设备与模型参数快照'),col('confirmation_status','确认状态',choices=STATUS),col('test_method','测试方法与步骤'),col('expected_result','预期结果'),col('actual_result','实际结果与测量数据'),col('project_id','关联项目','int',ref='projects'),col('model_name','模型 / 软件 / 算法名称',required=True),col('model_version','模型版本'),col('test_date','测试日期'),col('result','效果评价',choices=['待评价','效果好','一般','效果差']),col('prompt','测试环境备注'),col('product_id','关联产品','int',ref='products'),col('test_count','测试产品总数','int'),col('detection_rate','检出率 %','real'),col('miss_rate','历史漏检率 %','real'),col('yield_rate','良率 %','real'),col('light_source','光源类型'),col('camera','相机型号'),col('lens','镜头型号'),col('working_distance_mm','工作距离 mm','real'),col('product_spec','产品规格'),col('remark','效果说明')])
add('model_test_files','模型测试图片','关系','每次测试可保存多张原图和效果图。',[col('test_id','测试记录','int',True,'model_tests'),col('asset_id','图片文件','int',True,'assets'),col('role','图片用途',required=True,choices=['input','result'])],unique=[['asset_id']])
add('technical_experiences','操作规范与技术经验','主表','不绑定项目的通用技能、标注规范、AI 原理和工具操作说明；正文自动进入 AI 问答检索。',[col('name','经验标题',required=True),col('experience_type','经验类型',choices=['标注规范','调试经验','原理解释','工具操作','其他']),col('conditions','适用条件与限制'),col('confirmation_status','确认状态',choices=STATUS),col('category','分类'),col('tags','关键词'),col('content','规范与经验正文',required=True),col('remark','备注')])
add('technical_experience_files','技术经验—资料','关系','为通用经验关联文档或视频；每条关联选择一种资料。',[col('experience_id','技术经验','int',True,'technical_experiences'),col('asset_id','文档或上传视频','int',ref='assets'),col('video_id','已有视频','int',ref='videos')],unique=[['experience_id','asset_id'],['experience_id','video_id']])
add('document_types','文档类别','配置','维护可复用的文档分类；新增类别会出现在后续上传下拉选项中。',[col('name','类别名称',required=True)],unique=[['name']])
add('technical_objects','设备与软件字典','配置','统一相机、镜头、光源、工具、软件与模型的身份；历史测试另存参数快照。',[col('name','名称',required=True),col('object_kind','类型',required=True,choices=['相机','镜头','光源','工具','软件','模型','其他']),col('version','型号 / 版本'),col('specification','规格与参数'),col('remark','备注')],unique=[['name','object_kind','version']])
add('entity_aliases','对象别名','配置','别名经人工确认后指向已有对象，不按相似名称自动合并。',[col('entity_table','对象类型',required=True),col('entity_id','对象编号','int',True),col('name','别名',required=True)],unique=[['entity_table','entity_id','name']])
add('knowledge_links','知识关联','关系','明确登记适用、测试、使用与依据，保留条件、证据和确认状态。',[col('source_table','来源类型',required=True),col('source_id','来源编号','int',True),col('relation','关系',required=True,choices=list(RELATIONS)),col('target_table','目标类型',required=True),col('target_id','目标编号','int',True),col('conditions','适用条件与限制'),col('confirmation_status','确认状态',choices=STATUS),col('evidence_test_id','测试依据','int',ref='model_tests'),col('evidence_document_id','依据文档','int',ref='technical_agreements'),col('evidence_locator','证据页码 / 表格 / 时间点')],unique=[['source_table','source_id','relation','target_table','target_id']])
for item in T:
    item['fields'] += [col('created_by','录入作者'),col('created_at','录入时间'),col('updated_by','最后修改人'),col('updated_at','最后修改时间')]
    for field in item['fields']:
        if field['name'] in ('created_by','created_at','updated_by','updated_at'):field['readonly']=True
TABLES={t['name']:t for t in T}
for field in TABLES['videos']['fields']:
    if field['name'] in ('image_id','asset_id','preview_asset_id'):field['hidden']=True
for field in TABLES['assets']['fields']:
    if field['name']=='preview_asset_id':field['hidden']=True
for field in TABLES['model_tests']['fields']:
    if field['name'] in ('project_id','result','miss_rate'):field['hidden']=True
    if field['name']=='parameter_snapshot':field['readonly']=True
def ddl(mysql=False):
    out=[f'-- AOI Industrial Asset Catalog | {len(T)} tables', '-- Non-destructive DDL: existing tables are preserved.']
    if mysql: out+=['CREATE DATABASE IF NOT EXISTS aoi_catalog CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;','USE aoi_catalog;']
    for t in T:
        lines=[];constraints=[]
        for c in t['fields']:
            n=c['name'];k=c['kind']
            if k=='id': s='BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY' if mysql else 'INTEGER PRIMARY KEY AUTOINCREMENT'
            else:
                if k in ('int','real'):s=({'int':'BIGINT','real':'DOUBLE'}[k] if mysql else {'int':'INTEGER','real':'REAL'}[k])
                elif not mysql:s='TEXT'
                elif c.get('maxLength',191)>20000:s='LONGTEXT'
                elif c.get('maxLength',191)>1024:s='MEDIUMTEXT'
                else:s='VARCHAR('+str(c.get('maxLength',191))+')'
                if c['required']:s+=' NOT NULL'
            if 'maximum' in c:constraints.append(f"  CHECK (`{n}` IS NULL OR `{n}` <= {c['maximum']})")
            lines.append(f'  `{n}` {s}')
            if c['choices']:constraints.append('  CHECK (`'+n+'` IN ('+', '.join("'"+x+"'" for x in c['choices'])+'))')
            if c['ref']:constraints.append(f'  FOREIGN KEY (`{n}`) REFERENCES `{c["ref"]}` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT')
            if 'minimum' in c and k!='id':constraints.append(f"  CHECK (`{n}` IS NULL OR `{n}` >= {c['minimum']})")
        lines+=constraints
        for u in t['unique']:lines.append('  UNIQUE ('+', '.join('`'+x+'`' for x in u)+')')
        out.append(f'CREATE TABLE IF NOT EXISTS `{t["name"]}` (\n'+',\n'.join(lines)+'\n)'+(' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;' if mysql else ';'))
    for t in T:
        for c in t['fields']:
            if c['ref']:
                # MySQL creates indexes for foreign keys itself.
                if not mysql:out.append(f'CREATE INDEX IF NOT EXISTS `idx_{t["name"]}_{c["name"]}` ON `{t["name"]}` (`{c["name"]}`);')
    return '\n\n'.join(out)+'\n'


def json_schema(table_name):
    """Portable exchange contract generated from the same definitions as forms/DDL."""
    table=TABLES[table_name];properties={};required=[]
    for field in table['fields']:
        spec={'type':[{'int':'integer','id':'integer','real':'number'}.get(field['kind'],'string'),'null']}
        for key in ('minimum','maximum','maxLength'):
            if key in field:spec[key]=field[key]
        if field['choices']:spec['enum']=list(field['choices'])+[None]
        if field['required']:
            spec['type']=spec['type'][0];required.append(field['name'])
            if field['kind']=='text':spec['minLength']=1
            if field['choices']:spec['enum']=list(field['choices'])
        if field.get('unit'):spec['description']='单位：'+field['unit']
        properties[field['name']]=spec
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','title':table_name,'type':'object','additionalProperties':False,'properties':properties,'required':required}
