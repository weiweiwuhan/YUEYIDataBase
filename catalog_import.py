"""Reviewed public fastener catalog import; separate from concrete product specs.

Only rows marked 是 are selected. Previews do not write; commits must match a
server-signed preview of both the workbook and the current catalog state.
"""
from __future__ import annotations
import hashlib,hmac,io,json,re,secrets,time,unicodedata,zipfile
from datetime import date,datetime
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

MAX_UPLOAD_BYTES=20*1024*1024
MAX_ROWS=50000
MAX_COLUMNS=80
MAX_UNCOMPRESSED=100*1024*1024
_SECRET=secrets.token_bytes(32)
TABLES=('catalog_categories','catalog_products','catalog_product_categories')
PRODUCT_SHEETS=('产品审核','产品','Products','products','Product Review')
CATEGORY_SHEETS=('分类','分类体系','Categories','categories')
PRODUCT_FIELDS=('bn','record_scope','name','head_type','drive_type','thread_type','material','material_type','manufacturing_material','property_class','surface_treatment','color','standards','category_path','source_url','fetched_at','remark','raw_attributes_json')
METADATA_FIELDS={'fetched_at','raw_attributes_json'}
ALIASES={
 'selected':('是否导入','导入选择','审核选择','selected','import'),
 'source_system':('来源系统','来源网站','数据来源','source_system'),
 'source_product_id':('来源产品编号','来源产品ID','产品来源编号','source_product_id'),
 'bn':('BN编号','BN','bn'),
 'record_scope':('记录层级','产品层级','record_scope'),
 'name':('产品名称','名称','name'),
 'category_ids':('分类编号','所属分类编号','category_ids'),
 'category_path':('分类路径','完整分类路径','category_path'),
 'head_type':('头型','头形','head_type'),
 'drive_type':('驱动槽型','驱动方式','驱动','drive_type'),
 'thread_type':('螺纹','螺纹类型','thread_type'),
 'material':('材质','material'),
 'material_type':('材料类型','material_type'),
 'manufacturing_material':('制造材料','manufacturing_material'),
 'property_class':('性能等级','强度等级','property_class'),
 'surface_treatment':('表面处理','surface_treatment'),
 'color':('颜色','color'),
 'standards':('标准','标准编号','standards'),
 'source_url':('来源URL','来源网址','产品网址','source_url'),
 'fetched_at':('抓取时间','采集时间','fetched_at'),
 'remark':('备注','审核备注','remark'),
 'raw_attributes_json':('原始属性JSON','原始属性','raw_attributes_json'),
 'source_category_id':('分类编号','来源分类编号','分类ID','source_category_id'),
 'parent_source_id':('父分类编号','父级分类编号','父分类ID','parent_source_id'),
 'category_name':('分类名称','名称','category_name'),
}

def _text(value):
    if value is None:return ''
    if isinstance(value,(date,datetime)):return value.isoformat()
    if isinstance(value,float) and value.is_integer():return str(int(value))
    return str(value).replace('\r\n','\n').replace('\r','\n').strip()

def _header(value):return re.sub(r'\s+','',unicodedata.normalize('NFKC',_text(value))).casefold()

def _mapping(category=False):
    keys=set(ALIASES)-({'category_ids','name'} if category else {'source_category_id','parent_source_id','category_name'})
    return {_header(alias):key for key in keys for alias in ALIASES[key]}

def _selection(row):
    value=row.get('selected','').strip()
    if value in ('','待审核','否'):return False
    if value=='是':return True
    raise ValueError('是否导入只能填写“是”“否”或“待审核”；空白按待审核处理')

def _xlsx(content,filename):
    if not isinstance(content,bytes) or not content:raise ValueError('请选择非空 XLSX 文件')
    if len(content)>MAX_UPLOAD_BYTES:raise ValueError('目录文件最多 20 MB')
    if not str(filename).lower().endswith('.xlsx'):raise ValueError('目录导入只支持 XLSX 文件')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members=archive.infolist()
            if len(members)>2000 or sum(x.file_size for x in members)>MAX_UNCOMPRESSED:raise ValueError('XLSX 解压大小或文件数量超过限制')
            if any(x.flag_bits&1 for x in members):raise ValueError('不支持加密 XLSX')
            for member in members:
                if re.fullmatch(r'xl/worksheets/[^/]+\.xml',member.filename):
                    with archive.open(member) as stream:
                        for event,element in ET.iterparse(stream,events=('start','end')):
                            if event=='start' and element.tag.rsplit('}',1)[-1]=='c':
                                match=re.fullmatch(r'([A-Za-z]+)([0-9]+)',element.attrib.get('r',''))
                                if not match:raise ValueError('XLSX 包含无效单元格坐标')
                                column=0
                                for letter in match[1].upper():column=column*26+ord(letter)-64
                                if column>MAX_COLUMNS or int(match[2])>MAX_ROWS+1000:raise ValueError('工作表超出 80 列或 50000 行限制')
                            if event=='end':element.clear()
    except (zipfile.BadZipFile,OSError,ET.ParseError) as error:raise ValueError('XLSX 格式无效') from error
    try:
        import openpyxl
        workbook=openpyxl.load_workbook(io.BytesIO(content),read_only=True,data_only=False,keep_links=False)
    except Exception as error:raise ValueError('无法读取 XLSX，请重新另存为标准 XLSX 格式') from error
    result={}
    try:
        for kind,names in (('products',PRODUCT_SHEETS),('categories',CATEGORY_SHEETS)):
            matching=[name for name in names if name in workbook.sheetnames]
            if len(matching)>1:raise ValueError('同一文件中有多张'+('产品' if kind=='products' else '分类')+'工作表，请只保留一张')
            if not matching:
                if kind=='products':raise ValueError('缺少“产品审核”工作表')
                result[kind]=[];continue
            sheet=workbook[matching[0]];sheet.reset_dimensions();mapping=_mapping(kind=='categories');headers=None;rows=[]
            for number,cells in enumerate(sheet.iter_rows(max_col=MAX_COLUMNS),1):
                if number>MAX_ROWS+1000:raise ValueError('工作表空行过多')
                if any(c.data_type in ('f','e') for c in cells):raise ValueError(f'{sheet.title}第 {number} 行含公式或错误值，请转换成文本后上传')
                values=[_text(c.value) for c in cells]
                if not any(values):continue
                if headers is None:
                    while values and not values[-1]:values.pop()
                    if not all(values):raise ValueError(sheet.title+'存在空表头')
                    headers=[];known=set()
                    for value in values:
                        key=mapping.get(_header(value))
                        if key and key in known:raise ValueError(sheet.title+'重复字段：'+value)
                        if key:known.add(key)
                        headers.append(key)
                    if 'selected' not in known:raise ValueError(sheet.title+'缺少“是否导入”列')
                    continue
                if any(values[len(headers):]):raise ValueError(f'{sheet.title}第 {number} 行存在无表头数据')
                row={key:values[index] for index,key in enumerate(headers) if key}
                if any(len(value)>20000 for value in row.values()):raise ValueError(f'{sheet.title}第 {number} 行内容过长')
                rows.append({'sheet':sheet.title,'row':number,'values':row})
                if len(rows)>MAX_ROWS:raise ValueError('单表最多 50000 行')
            if headers is None:raise ValueError(sheet.title+'没有表头')
            result[kind]=rows
    finally:workbook.close()
    return result

def _system(row):
    value=row.get('source_system','').strip() or 'Bossard'
    return 'Bossard' if value.casefold()=='bossard' else value

def _valid_url(value):
    if not value:return
    try:
        parsed=urlsplit(value)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:raise ValueError()
    except ValueError:raise ValueError('来源URL必须是无账号信息的 HTTP/HTTPS 网址')

def _clean(record,table):
    from schema import TABLES as SCHEMA
    fields={f['name']:f for f in SCHEMA[table]['fields']}
    for key,value in record.items():
        if value is not None and isinstance(value,str):
            if len(value)>fields[key].get('maxLength',191):raise ValueError(fields[key]['label']+'内容过长')
    _valid_url(record.get('source_url'))
    return record

def _database(connection,execute):
    state={table:[dict(row) for row in execute(connection,'SELECT * FROM `'+table+'` ORDER BY id').fetchall()] for table in TABLES}
    digest=hashlib.sha256()
    for table in TABLES:
        digest.update(table.encode())
        for row in state[table]:digest.update(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
    return state,digest.hexdigest()

def _signature(file_hash,db_hash,mode,owner,expires):
    message='|'.join((file_hash,db_hash,mode,str(owner),str(expires))).encode()
    return hmac.new(_SECRET,message,hashlib.sha256).hexdigest()

def validate_preview_token(token,plan,owner=''):
    try:
        expires,signature=str(token or '').split('.',1);expires=int(expires)
        if expires<int(time.time()) or expires>int(time.time())+1801:raise ValueError()
        expected=_signature(plan['file_sha256'],plan['_database_sha256'],plan['mode'],owner,expires)
        if not hmac.compare_digest(signature,expected):raise ValueError()
    except (ValueError,TypeError):raise ValueError('预览已失效、文件或目录数据已变化，请重新预览后确认导入')

def prepare_import(connection,execute,content,filename,mode='fill_missing',owner=''):
    if mode!='fill_missing':raise ValueError('当前仅支持 fill_missing：补充空值并保留已有内容')
    sheets=_xlsx(content,filename);state,db_hash=_database(connection,execute)
    existing_categories={(r['source_system'],r['source_category_id']):r for r in state['catalog_categories']}
    existing_products={(r['source_system'],r['source_product_id']):r for r in state['catalog_products']}
    category_by_id={r['id']:(r['source_system'],r['source_category_id']) for r in state['catalog_categories']}
    links={(r['catalog_product_id'],r['catalog_category_id']) for r in state['catalog_product_categories']}
    errors=[];categories={};products={};selected_count=0;skip_count=0;preview=[];conflicts_count=0
    def error(row,message):errors.append({'sheet':row.get('sheet','分类'),'row':row.get('row',0),'message':str(message)})
    for item in sheets['categories']:
        row=item['values']
        try:
            selected=_selection(row);sid=row.get('source_category_id','').strip()
            if not sid:
                if selected:raise ValueError('分类编号不能为空')
                continue
            key=(_system(row),sid)
            record=_clean({'source_system':key[0],'source_category_id':sid,'name':row.get('category_name','').strip(),'category_path':row.get('category_path',''),'source_url':row.get('source_url','')},'catalog_categories')
            if not record['name']:raise ValueError('分类名称不能为空')
            candidate={'key':key,'record':record,'parent_key':(key[0],row['parent_source_id'].strip()) if row.get('parent_source_id') else None,'selected':selected,'excluded':row.get('selected')=='否','sheet':item['sheet'],'row':item['row']}
            if key in categories and (categories[key]['record']!=record or categories[key]['parent_key']!=candidate['parent_key']):raise ValueError('同一分类编号有不同内容')
            categories[key]=candidate
        except ValueError as exc:error(item,exc)
    for item in sheets['products']:
        row=item['values']
        try:
            if not _selection(row):skip_count+=1;continue
            selected_count+=1;system=_system(row);bn=row.get('bn','').strip()
            if bn:
                match=re.fullmatch(r'(?:BN\s*)?([0-9]+)',bn,re.I)
                if not match:raise ValueError('BN编号应为 BN 加数字，例如 BN 874')
                bn='BN '+match[1]
            sid=row.get('source_product_id','').strip() or bn.replace(' ','')
            if not sid:raise ValueError('来源产品编号或BN编号至少填写一项')
            scope=row.get('record_scope','').strip() or 'series'
            scope={'系列':'series','BN系列':'series','产品系列':'series','规格':'article','具体规格':'article','SKU':'article'}.get(scope,scope)
            if scope not in ('series','article'):raise ValueError('记录层级只能为 series（系列）或 article（具体目录规格）')
            record={field:row.get(field,'').strip() or None for field in PRODUCT_FIELDS};record.update(source_system=system,source_product_id=sid,bn=bn or None,record_scope=scope)
            if not record['name']:raise ValueError('产品名称不能为空')
            if not record['source_url']:raise ValueError('来源URL不能为空，请保留公开信息出处')
            if record['raw_attributes_json']:
                try:json.loads(record['raw_attributes_json'])
                except ValueError:raise ValueError('原始属性JSON不是有效JSON文本')
            _clean(record,'catalog_products');key=(system,sid)
            category_ids=[x.strip() for x in re.split(r'[|;；\n]',row.get('category_ids','')) if x.strip()]
            candidate={'key':key,'record':record,'category_keys':list(dict.fromkeys((system,x) for x in category_ids)),'sheet':item['sheet'],'row':item['row']}
            if key in products:
                if products[key]['record']!=record:raise ValueError('同一来源产品编号在表内有不同内容，请先合并审核')
                products[key]['category_keys']=list(dict.fromkeys(products[key]['category_keys']+candidate['category_keys']));skip_count+=1
            else:products[key]=candidate
        except ValueError as exc:error(item,exc)
    needed=set(k for k,v in categories.items() if v['selected'])
    for product in products.values():needed.update(product['category_keys'])
    visiting=set();ordered=[];done=set()
    def include(key,origin):
        if key in done:return
        if key in visiting:raise ValueError('分类父级形成循环：'+key[1])
        candidate=categories.get(key);old=existing_categories.get(key)
        if candidate and candidate['excluded']:raise ValueError('所选产品或分类引用了标为“否”的分类：'+key[1])
        if not candidate:
            if not old:raise ValueError('引用的分类或父分类不存在：'+key[1])
            done.add(key);return
        visiting.add(key)
        if candidate['parent_key']:include(candidate['parent_key'],origin)
        visiting.remove(key);done.add(key);ordered.append(candidate)
    for key in sorted(needed):
        try:include(key,categories.get(key) or {})
        except ValueError as exc:error(categories.get(key) or {},exc)
    category_ops=[];category_add_count=0;category_update_count=0;category_conflicts=[]
    for candidate in ordered:
        old=existing_categories.get(candidate['key']);incoming=candidate['record'];changes={};conflicts=[]
        if old:
            for field,value in incoming.items():
                if field in ('source_system','source_category_id') or not value:continue
                if old.get(field) in (None,''):changes[field]=value
                elif old[field]!=value:conflicts.append({'field':field,'old':old[field],'new':value})
            old_parent=category_by_id.get(old.get('parent_id'))
            if old_parent!=candidate['parent_key']:conflicts.append({'field':'parent_id','old':old_parent,'new':candidate['parent_key']})
            if changes:category_update_count+=1
        else:category_add_count+=1
        if conflicts:category_conflicts.append({'source_category_id':candidate['key'][1],'conflicts':conflicts})
        category_ops.append({**candidate,'existing':old,'changes':changes})
    product_ops=[];add_count=0;update_count=0
    for candidate in products.values():
        old=existing_products.get(candidate['key']);changes={};conflicts=[];new_links=[]
        if old:
            for field,value in candidate['record'].items():
                if field in ('source_system','source_product_id') or value in (None,''):continue
                if old.get(field) in (None,''):changes[field]=value
                elif old[field]!=value and field not in METADATA_FIELDS:conflicts.append({'field':field,'old':old[field],'new':value})
            for key in candidate['category_keys']:
                cat=existing_categories.get(key)
                if not cat or (old['id'],cat['id']) not in links:new_links.append(key)
            if changes or new_links:action='update';update_count+=1
            else:action='conflict' if conflicts else 'skip';skip_count+=1
        else:action='add';add_count+=1;new_links=candidate['category_keys']
        if conflicts:conflicts_count+=1
        entry={**candidate,'existing':old,'changes':changes,'new_links':new_links};product_ops.append(entry)
        if len(preview)<50:preview.append({'row':candidate['row'],'source_product_id':candidate['key'][1],'bn':candidate['record'].get('bn'),'name':candidate['record']['name'],'action':action,'changes':{f:{'old':old.get(f) if old else None,'new':value} for f,value in (changes if old else candidate['record']).items() if value not in (None,'')},'conflicts':conflicts,'new_category_links':[k[1] for k in new_links]})
    file_hash=hashlib.sha256(content).hexdigest();expires=int(time.time())+1800
    plan={'total':len(sheets['products']),'selected_count':selected_count,'add_count':add_count,'update_count':update_count,'skip_count':skip_count,'conflict_count':conflicts_count,'category_add_count':category_add_count,'category_update_count':category_update_count,'category_conflict_count':len(category_conflicts),'category_conflicts':category_conflicts[:50],'error_count':len(errors),'errors':errors[:250],'preview':preview,'preview_token':str(expires)+'.'+_signature(file_hash,db_hash,mode,owner,expires),'file_sha256':file_hash,'mode':mode,'_database_sha256':db_hash,'_categories':category_ops,'_products':product_ops}
    return plan

def public_plan(plan):return {key:value for key,value in plan.items() if not key.startswith('_')}

def apply_import(connection,execute,save,plan):
    if plan['error_count']:raise ValueError('目录导入未执行，请先修正预览中的错误')
    if _database(connection,execute)[1]!=plan['_database_sha256']:raise ValueError('目录数据已变化，请重新预览')
    category_ids={(r['source_system'],r['source_category_id']):r['id'] for r in execute(connection,'SELECT id,source_system,source_category_id FROM catalog_categories').fetchall()}
    for operation in plan['_categories']:
        old=operation['existing']
        if old:
            if operation['changes']:save(connection,'catalog_categories',{**old,**operation['changes']},old['id'])
            category_ids[operation['key']]=old['id']
        else:
            parent_id=category_ids.get(operation['parent_key']) if operation['parent_key'] else None
            category_ids[operation['key']]=save(connection,'catalog_categories',{**operation['record'],'parent_id':parent_id})
    for operation in plan['_products']:
        old=operation['existing']
        if old:
            pid=old['id']
            if operation['changes']:save(connection,'catalog_products',{**old,**operation['changes']},pid)
        else:pid=save(connection,'catalog_products',operation['record'])
        for key in operation['new_links']:
            category_id=category_ids.get(key)
            if category_id is None:raise ValueError('分类引用未解析，导入已回滚')
            if not execute(connection,'SELECT id FROM catalog_product_categories WHERE catalog_product_id=? AND catalog_category_id=?',(pid,category_id)).fetchone():save(connection,'catalog_product_categories',{'catalog_product_id':pid,'catalog_category_id':category_id})
    return {key:plan[key] for key in ('selected_count','add_count','update_count','skip_count','conflict_count','category_add_count','category_update_count','category_conflict_count')}
