"""Validated record-level relationships; storage stays in the business database."""
import json
from collections import defaultdict, deque
ENTITY_TABLES={'projects','products','product_categories','defect_types','technical_objects','model_tests','technical_experiences','technical_agreements','videos','images','engineering_projects','assets','after_sales'}
RELATIONS={
 '适用于':({'technical_experiences'},{'products','product_categories','defect_types'}),
 '测试对象':({'model_tests'},{'products'}),
 '测试缺陷':({'model_tests'},{'defect_types'}),
 '使用设备':({'model_tests','technical_experiences'},{'technical_objects'}),
 '参考规范':({'model_tests'},{'technical_experiences'}),
 '测试依据':({'technical_experiences'},{'model_tests'}),
 '相关资料':(ENTITY_TABLES,{'technical_agreements','videos','images','engineering_projects','assets'}),
}
STATUS={'待验证','经验建议','已验证','待补充'}
def entity(c,execute,table,rid):
    if table not in ENTITY_TABLES:raise ValueError('不支持的知识对象类型')
    row=execute(c,f'SELECT * FROM `{table}` WHERE id=?',(int(rid),)).fetchone()
    if not row:raise ValueError('关联对象不存在或已删除')
    return dict(row)
def validate_relation(c,execute,r):
    source=entity(c,execute,r['source_table'],r['source_id']);target=entity(c,execute,r['target_table'],r['target_id'])
    allowed=RELATIONS.get(r['relation'])
    if not allowed or r['source_table'] not in allowed[0] or r['target_table'] not in allowed[1]:raise ValueError('关系与对象类型不匹配')
    if (r['source_table'],r['source_id'])==(r['target_table'],r['target_id']):raise ValueError('不能关联对象自身')
    if r.get('evidence_test_id'):entity(c,execute,'model_tests',r['evidence_test_id'])
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
        r=dict(raw);edge(r['source_table'],r['source_id'],r['relation'],r['target_table'],r['target_id'],link_id=r['id'],conditions=r.get('conditions'),confirmation_status=r.get('confirmation_status') or '待补充',evidence_test_id=r.get('evidence_test_id'),created_by=r.get('created_by'))
    mappings=[('project_products','projects','project_id','关联产品','products','product_id'),('image_defects','images','image_id','展示缺陷','defect_types','defect_type_id'),('project_assets','projects','project_id','关联资料','assets','asset_id'),('asset_products','assets','asset_id','相关产品','products','product_id'),('agreement_products','technical_agreements','agreement_id','相关产品','products','product_id'),('agreement_files','technical_agreements','agreement_id','附带文件','assets','asset_id'),('model_test_files','model_tests','test_id','附带测试图片','assets','asset_id')]
    for table,st,sf,rel,tt,tf in mappings:
        for r in execute(c,f'SELECT * FROM `{table}`').fetchall():edge(st,r[sf],rel,tt,r[tf],origin='已有绑定')
    for node in list(nodes.values()):
        r=node['record'];t=node['table']
        for fk,target,rel in [('product_id','products','测试对象' if t=='model_tests' else '关联产品'),('project_id','projects','所属项目'),('category_id','product_categories','所属分类'),('asset_id','assets','文件资源')]:
            if r.get(fk):edge(t,r['id'],rel,target,r[fk],origin='已有绑定')
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
        if node['table'] not in {'technical_experiences','model_tests','defect_types','products','technical_objects'}:continue
        lines=[]
        for e in links:
            a=nodes[e['source']];b=nodes[e['target']]
            text=f'{a["label"]}（{a["key"]}） — {e["relation"]} → {b["label"]}（{b["key"]}）'
            for name,label in [('conditions','条件'),('confirmation_status','确认状态'),('evidence_test_id','测试依据编号')]:
                if e.get(name):text+=f'；{label}：{e[name]}'
            if b['table']=='model_tests' or a['table']=='model_tests':
                r=b['record'] if b['table']=='model_tests' else a['record']
                text+='；测试记录条件及结果：'+json.dumps({k:r.get(k) for k in ('test_date','model_name','model_version','test_count','detection_rate','yield_rate','prompt','parameter_snapshot','actual_result','acceptance_criteria')},ensure_ascii=False)
            lines.append(text)
        # Each node is a relational query result. No inferred applicability or causal claims.
        docs.append({'id':'graph:'+key,'source_type':'knowledge_graph','source_id':key,'title':node['label']+' · 关联资料','text':'名称与别名：'+'、'.join([node['label']]+node['aliases'])+'\n以下为数据库明确登记的双向关联，保留条件及状态：\n'+'\n'.join(lines),'category':'知识关联'})
    return docs
