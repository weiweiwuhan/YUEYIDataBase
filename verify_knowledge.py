"""Read-only audit of legacy knowledge; report conflicts without changing facts."""
import json
import app
from knowledge_graph import entity,validate_relation,validate_experience,graph
from knowledge_contract import normalize_term

def verify(connection,execute):
    issues=[]
    for row in execute(connection,'SELECT * FROM entity_aliases ORDER BY id').fetchall():
        try:entity(connection,execute,row['entity_table'],row['entity_id'])
        except (ValueError,TypeError,KeyError) as error:issues.append({'table':'entity_aliases','id':row['id'],'message':str(error)})
    for raw in execute(connection,'SELECT * FROM knowledge_links ORDER BY id').fetchall():
        row=dict(raw)
        try:validate_relation(connection,execute,row)
        except (ValueError,TypeError,KeyError) as error:issues.append({'table':'knowledge_links','id':row['id'],'message':str(error)})
    for row in execute(connection,"SELECT id FROM technical_experiences WHERE confirmation_status='已验证'").fetchall():
        try:validate_experience(connection,execute,row['id'])
        except (ValueError,TypeError,KeyError) as error:issues.append({'table':'technical_experiences','id':row['id'],'message':str(error)})
    names={}
    for node in graph(connection,execute)['nodes']:
        for name in {node['label'],*node['aliases']}:names.setdefault(normalize_term(name),set()).add(node['key'])
    ambiguous=[{'term':name,'objects':sorted(keys)} for name,keys in sorted(names.items()) if len(keys)>1]
    return {'valid':not issues,'issues':issues,'ambiguous_terms':ambiguous}

if __name__=='__main__':
    c=app.connect()
    try:report=verify(c,app.execute)
    finally:c.close()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report['valid'] else 1)
