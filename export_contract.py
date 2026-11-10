"""Export portable contracts from schema.py; --check detects generated drift."""
import argparse
import json
from pathlib import Path
from schema import T,ddl,json_schema

def artifacts():
    contract={'$schema':'https://json-schema.org/draft/2020-12/schema','title':'AOI catalog exchange','type':'object','additionalProperties':False,
              'properties':{t['name']:{'type':'array','items':json_schema(t['name'])} for t in T}}
    return {'schema.mysql.sql':ddl(True),'schemas/catalog.schema.json':json.dumps(contract,ensure_ascii=False,indent=2)+'\n'}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args();root=Path(__file__).resolve().parent
    for name,content in artifacts().items():
        path=root/name
        if args.check:
            if not path.is_file() or path.read_text('utf-8')!=content:raise SystemExit('Contract drift: '+name+'; run python export_contract.py')
        else:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf-8')
