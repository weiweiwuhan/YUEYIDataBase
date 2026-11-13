"""Validated record-level relationships; storage stays in the business database."""
import json
from collections import defaultdict, deque
from knowledge_contract import ENTITY_TABLES,RELATIONS,STATUS,normalize_term,contains_term
def entity(c,execute,table,rid):
    if table not in ENTITY_TABLES:raise ValueError('不支持的知识对象类型')
    row=execute(c,f'SELECT * FROM `{table}` WHERE id=?',(int(rid),)).fetchone()
    if not row:raise ValueError('关联对象不存在或已删除')
    return dict(row)

def validate_evidence_scope(c,execute,link,test):
    """Reject explicit scope conflicts; unknown evidence is not silently verified."""
    table,rid=link['target_table'],int(link['target_id'])
    if link['relation']=='测试依据':return
    if test.get('test_count')==0:raise ValueError('零样本测试不能作为已验证依据')
    if link['relation']=='使用设备':
        found=execute(c,"SELECT id FROM knowledge_links WHERE source_table='model_tests' AND source_id=? AND relation='使用设备' AND target_table='technical_objects' AND target_id=?",(test['id'],rid)).fetchone()
        if not found:raise ValueError('测试依据未登记该设备，不能确认此关联已验证')
    if link['relation']!='适用于':return
    if table=='defect_types':
        found=execute(c,"SELECT id FROM knowledge_links WHERE source_table='model_tests' AND source_id=? AND relation='测试缺陷' AND target_table='defect_types' AND target_id=?",(test['id'],rid)).fetchone()
        if not found:raise ValueError('测试依据未覆盖该缺陷，请补充测试范围或改为待验证')
    elif table in ('products','product_categories','materials','process_types'):
        product_id=test.get('product_id')
        if not product_id:raise ValueError('测试依据未指定产品，不能确认该适用范围已验证')
        product=entity(c,execute,'products',product_id)
        valid=False
        if table=='products':valid=product_id==rid
        elif table=='materials':valid=product.get('material_id')==rid
        elif table=='process_types':valid=bool(execute(c,'SELECT id FROM product_processes WHERE product_id=? AND process_id=?',(product_id,rid)).fetchone())
        else:
            category=product.get('category_id');seen=set()
            while category and category not in seen:
                seen.add(category)
                if category==rid:valid=True;break
                category=entity(c,execute,'product_categories',category).get('parent_id')
        if not valid:raise ValueError('测试依据与适用产品、分类、材质或工艺不匹配')

def validate_experience(c,execute,rid):
    record=entity(c,execute,'technical_experiences',rid)
    links=[dict(r) for r in execute(c,"SELECT * FROM knowledge_links WHERE source_table='technical_experiences' AND source_id=?",(rid,)).fetchall()]
    if record.get('confirmation_status')=='已验证' and not any(r['relation']=='测试依据' for r in links):raise ValueError('已验证的经验请提供测试依据')
    for link in links:
        if not link.get('confirmation_status'):link['confirmation_status']=record.get('confirmation_status')
        validate_relation(c,execute,link)

def validate_relation(c,execute,r):
    source=entity(c,execute,r['source_table'],r['source_id']);target=entity(c,execute,r['target_table'],r['target_id'])
    allowed=RELATIONS.get(r['relation'])
    if not allowed or r['source_table'] not in allowed[0] or r['target_table'] not in allowed[1]:raise ValueError('关系与对象类型不匹配')
    if (r['source_table'],r['source_id'])==(r['target_table'],r['target_id']):raise ValueError('不能关联对象自身')
    if r.get('evidence_document_id'):entity(c,execute,'technical_agreements',r['evidence_document_id'])
    if r['relation']=='测试依据' and r.get('confirmation_status')=='已验证' and target.get('test_count')==0:raise ValueError('零样本测试不能作为已验证依据')
    if r.get('evidence_test_id'):
        test=entity(c,execute,'model_tests',r['evidence_test_id'])
        if r.get('confirmation_status')=='已验证':validate_evidence_scope(c,execute,r,test)
    if r.get('confirmation_status')=='已验证' and not (r.get('evidence_test_id') or r['relation']=='测试依据' or r['source_table']=='model_tests'):raise ValueError('已验证的关联请提供测试依据')

def graph(c,execute):
    nodes={};edges=[];known=set()
    for table in sorted(ENTITY_TABLES):
        for raw in execute(c,f'SELECT * FROM `{table}` ORDER BY id').fetchall():
            r=dict(raw);key=f'{table}:{r["id"]}'
            label=r.get('name') or r.get('file_name') or r.get('code') or f'记录 #{r["id"]}'
            if table=='images':label=f'图片 #{r["id"]}'
            nodes[key]={'key':key,'table':table,'id':r['id'],'label':label,'record':r,'aliases':[]}
    for r in execute(c,'SELECT * FROM entity_aliases ORDER BY id').fetchall():
        key=f'{r["entity_table"]}:{r["entity_id"]}'
        if key in nodes:nodes[key]['aliases'].append(r['name'])
    def edge(st,si,rel,tt,ti,**extra):
        a=f'{st}:{si}';b=f'{tt}:{ti}';key=(a,rel,b)
        if a not in nodes or b not in nodes or key in known:return
        known.add(key);edges.append({'source':a,'target':b,'relation':rel,**extra})
    for raw in execute(c,'SELECT * FROM knowledge_links ORDER BY id').fetchall():
        r=dict(raw);edge(r['source_table'],r['source_id'],r['relation'],r['target_table'],r['target_id'],link_id=r['id'],updated_at=r.get('updated_at'),conditions=r.get('conditions'),confirmation_status=r.get('confirmation_status') or '待补充',evidence_test_id=r.get('evidence_test_id'),evidence_document_id=r.get('evidence_document_id'),evidence_locator=r.get('evidence_locator'),created_by=r.get('created_by'))
    mappings=[('project_products','projects','project_id','关联产品','products','product_id'),('image_defects','images','image_id','展示缺陷','defect_types','defect_type_id'),('project_assets','projects','project_id','关联资料','assets','asset_id'),('asset_products','assets','asset_id','相关产品','products','product_id'),('agreement_products','technical_agreements','agreement_id','相关产品','products','product_id'),('agreement_files','technical_agreements','agreement_id','附带文件','assets','asset_id'),('model_test_files','model_tests','test_id','附带测试图片','assets','asset_id'),('product_processes','products','product_id','采用工艺','process_types','process_id'),('presales_product_photos','presales_plans','plan_id','产品原始照片','assets','asset_id')]
    for table,st,sf,rel,tt,tf in mappings:
        for r in execute(c,f'SELECT * FROM `{table}`').fetchall():
            extra={'binding':{'kind':'product_process','id':r['id'],'target_id':r[tf],'updated_at':r['updated_at']}} if table=='product_processes' else {}
            edge(st,r[sf],rel,tt,r[tf],origin='已有绑定',**extra)
    for node in list(nodes.values()):
        r=node['record'];t=node['table']
        for fk,target,rel in [('product_id','products','测试对象' if t=='model_tests' else '关联产品'),('project_id','projects','所属项目'),('category_id','product_categories','所属分类'),('asset_id','assets','文件资源'),('material_id','materials','产品材质'),('parent_id','product_categories','上级分类')]:
            if r.get(fk):
                extra={'binding':{'kind':'product_material','id':r['id'],'target_id':r[fk],'updated_at':r.get('updated_at')}} if t=='products' and fk=='material_id' else {}
                edge(t,r['id'],rel,target,r[fk],origin='已有绑定',**extra)
    for r in execute(c,'SELECT * FROM presales_stations WHERE image_asset_id IS NOT NULL').fetchall():
        edge('presales_plans',r['plan_id'],'实验室效果图','assets',r['image_asset_id'],origin='已有绑定',conditions='相机/工位'+str(r['station_no'])+' · '+r['name'])
    for r in execute(c,'SELECT * FROM technical_experience_files').fetchall():
        edge('technical_experiences',r['experience_id'],'附带资料','assets' if r['asset_id'] else 'videos',r['asset_id'] or r['video_id'],origin='已有绑定')
    for r in execute(c,"SELECT * FROM asset_relations WHERE relation_type='paired'").fetchall():edge('assets',r['source_asset_id'],'工程关联图片','assets',r['target_asset_id'],origin='已有绑定')
    return {'nodes':list(nodes.values()),'edges':edges}

def neighborhood(data,table,rid,depth=2):
    root=f'{table}:{int(rid)}';nodes={n['key']:n for n in data['nodes']}
    if root not in nodes:raise ValueError('对象不存在')
    adjacent=defaultdict(list)
    for e in data['edges']:adjacent[e['source']].append(e);adjacent[e['target']].append(e)
    seen={root};chosen=[];edge_keys=set();queue=deque([(root,0)])
    while queue:
        key,level=queue.popleft()
        if level>=depth:continue
        for e in adjacent[key]:
            sig=(e['source'],e['relation'],e['target'])
            if sig not in edge_keys:edge_keys.add(sig);chosen.append(e)
            other=e['target'] if e['source']==key else e['source']
            if other not in seen:seen.add(other);queue.append((other,level+1))
    return {'root':root,'nodes':[nodes[k] for k in sorted(seen)],'edges':chosen}

def relation_documents(data):
    nodes={n['key']:n for n in data['nodes']};docs=[];adj=defaultdict(list)
    for e in data['edges']:adj[e['source']].append(e);adj[e['target']].append(e)
    for key,links in adj.items():
        node=nodes[key]
        if node['table'] not in {'technical_experiences','model_tests','defect_types','products','technical_objects','product_categories','materials','process_types'}:continue
        lines=[]
        for e in links:
            a=nodes[e['source']];b=nodes[e['target']]
            text=f'{a["label"]}（{a["key"]}） — {e["relation"]} → {b["label"]}（{b["key"]}）'
            for name,label in [('conditions','条件'),('confirmation_status','确认状态'),('evidence_test_id','测试依据编号'),('evidence_document_id','依据文档编号'),('evidence_locator','证据定位')]:
                if e.get(name):text+=f'；{label}：{e[name]}'
            if b['table']=='model_tests' or a['table']=='model_tests':
                r=b['record'] if b['table']=='model_tests' else a['record']
                text+='；测试记录条件及结果：'+json.dumps({k:r.get(k) for k in ('test_date','model_name','model_version','test_count','detection_rate','yield_rate','product_id','inspection_surface','light_source','camera','lens','working_distance_mm','product_spec','prompt','parameter_snapshot','actual_result','acceptance_criteria')},ensure_ascii=False)
            if e.get('evidence_test_id'):
                test=nodes.get('model_tests:'+str(e['evidence_test_id']))
                if test:text+='；依据测试：'+json.dumps(test['record'],ensure_ascii=False)
            if e.get('evidence_document_id'):
                document=nodes.get('technical_agreements:'+str(e['evidence_document_id']))
                if document:text+='；依据文档：'+json.dumps({k:document['record'].get(k) for k in ('id','code','name','signed_date','updated_at')},ensure_ascii=False)
            lines.append(text)
        # Each node is a relational query result. No inferred applicability or causal claims.
        docs.append({'id':'graph:'+key,'source_type':'knowledge_graph','source_id':key,'title':node['label']+' · 关联资料','text':'名称与别名：'+'、'.join([node['label']]+node['aliases'])+'\n以下为数据库明确登记的双向关联，保留条件及状态：\n'+'\n'.join(lines),'category':'知识关联'})
    return docs

def resolve_entities(data,question):
    """Return all unresolved names; an ambiguous name never chooses an arbitrary ID."""
    lookup=defaultdict(list)
    for node in data['nodes']:
        for name in {node['label'],*node['aliases']}:
            if contains_term(question,name):lookup[normalize_term(name)].append(node)
    matches={n['key'] for n in data['nodes'] if contains_term(question,n['key'])};ambiguous=[]
    for term,candidates in lookup.items():
        unique={n['key']:n for n in candidates};candidates=list(unique.values())
        if len(candidates)>1:
            specified=[n for n in candidates if n['key'] in question or any(contains_term(question,n['record'].get(f)) for f in ('spec_text','version','code') if n['record'].get(f))]
            if len(specified)==1:candidates=specified
        if len(candidates)>1:
            ambiguous.append({'term':term,'candidates':[{'key':n['key'],'name':n['label'],'detail':n['record'].get('spec_text') or n['record'].get('version') or n['record'].get('code') or ''} for n in candidates]})
        else:matches.update(n['key'] for n in candidates)
    return matches,ambiguous

def scoped_source_filter(data,matches,question):
    """Keep explicit product/defect scope conflicts out of recommendation context."""
    nodes={n['key']:n for n in data['nodes']};outgoing=defaultdict(list)
    for edge in data['edges']:outgoing[edge['source']].append(edge)
    constraints={t:{int(k.split(':')[1]) for k in matches if k.startswith(t+':')} for t in ('products','product_categories','defect_types','materials','process_types')}
    def category_path(category):
        result=set()
        while category and category not in result:
            result.add(category);node=nodes.get('product_categories:'+str(category))
            category=node['record'].get('parent_id') if node else None
        return result
    for pid in constraints['products']:
        product=nodes.get('products:'+str(pid))
        if product:constraints['product_categories'].update(category_path(product['record'].get('category_id')))
    condition_values={field:{n['record'].get(field) for n in data['nodes'] if n['table']=='model_tests' and n['record'].get(field) and contains_term(question,n['record'][field])} for field in ('model_version','light_source','camera','lens','inspection_surface')}
    def allowed(key,seen=None):
        node=nodes.get(key)
        if not node:return True
        seen=set() if seen is None else seen
        if key in seen:return True
        seen.add(key);r=node['record'];links=outgoing[key]
        if node['table'] in ('model_tests','after_sales'):
            if constraints['products'] and r.get('product_id') and r['product_id'] not in constraints['products']:return False
            if r.get('product_id'):
                product=nodes.get('products:'+str(r['product_id']))
                if product and constraints['materials'] and product['record'].get('material_id') and product['record']['material_id'] not in constraints['materials']:return False
                if product and constraints['product_categories'] and product['record'].get('category_id') and not (category_path(product['record']['category_id'])&constraints['product_categories']):return False
                if product and constraints['process_types']:
                    processes={int(e['target'].split(':')[1]) for e in outgoing[product['key']] if e['relation']=='采用工艺'}
                    if processes and not (processes&constraints['process_types']):return False
            if node['table']=='model_tests':
                for field in ('model_version','light_source','camera','lens','inspection_surface'):
                    values=condition_values[field]
                    if values and r.get(field) and r[field] not in values:return False
        for table,ids in constraints.items():
            targets={int(e['target'].split(':')[1]) for e in links if e['target'].startswith(table+':') and e['relation'] in ('适用于','测试缺陷','测试对象','采用工艺','产品材质')}
            if ids and targets and not (ids&targets):return False
        if node['table']=='technical_experiences':
            evidence=[e['target'] for e in links if e['relation']=='测试依据']
            # A condition conflict in all recorded tests cannot become an applicable recommendation.
            if evidence and not any(allowed(k,set(seen)) for k in evidence):return False
        return True
    forbidden=[n['key'] for n in data['nodes'] if n['table'] in ('technical_experiences','model_tests') and not allowed(n['key'])]
    def filter_sources(sources):
        result=[]
        for source in sources:
            key=str(source.get('source_id','')) if source.get('source_type')=='knowledge_graph' else source.get('source_type','')+':'+str(source.get('source_id',''))
            if not allowed(key):continue
            # Relationship documents contain both directions: remove incompatible neighbors too.
            if source.get('source_type')=='knowledge_graph':
                source=dict(source)
                lines=[line for line in source['text'].splitlines() if not any('（'+key+'）' in line for key in forbidden)]
                if len(lines)<=2:continue
                source['text']='\n'.join(lines)
            result.append(source)
        return sorted(result,key=lambda d:0 if '已验证' in d.get('text','') else 1)
    return filter_sources
