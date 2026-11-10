"""Additive knowledge and media migrations, including legacy attachment promotion."""
from pathlib import Path
from schema import TABLES,ddl
from catalog_storage import VIDEO_EXT

def columns(c,execute,mysql,t):
    return {r['Field'] if mysql else r['name']:r for r in execute(c,'SHOW COLUMNS FROM `'+t+'`' if mysql else 'PRAGMA table_info(`'+t+'`)').fetchall()}

def extend(c,execute,mysql):
    extensions={
      'assets': [('preview_asset_id','BIGINT' if mysql else 'INTEGER','assets')],
      'videos': [('asset_id','BIGINT' if mysql else 'INTEGER','assets'),('preview_asset_id','BIGINT' if mysql else 'INTEGER','assets')],
      'technical_experiences':[(n,'MEDIUMTEXT' if n=='conditions' and mysql else 'VARCHAR(191)' if mysql else 'TEXT',None) for n in ('experience_type','conditions','confirmation_status')],
      'model_tests':[(n,'MEDIUMTEXT' if n in ('parameter_snapshot','acceptance_criteria') and mysql else 'VARCHAR(191)' if mysql else 'TEXT',None) for n in ('inspection_surface','acceptance_criteria','parameter_snapshot','confirmation_status')],
      'knowledge_links':[('evidence_document_id','BIGINT' if mysql else 'INTEGER','technical_agreements'),('evidence_locator','VARCHAR(1024)' if mysql else 'TEXT',None)],
    }
    for table,fields in extensions.items():
        existing=columns(c,execute,mysql,table)
        for name,kind,ref in fields:
            if name not in existing:
                suffix=(f', ADD CONSTRAINT fk_{table}_{name} FOREIGN KEY ({name}) REFERENCES {ref}(id) ON DELETE RESTRICT ON UPDATE RESTRICT' if mysql else f' REFERENCES {ref}(id) ON DELETE RESTRICT ON UPDATE RESTRICT') if ref else ''
                execute(c,f'ALTER TABLE `{table}` ADD COLUMN `{name}` {kind}{suffix}')
    # Generic documents can exist without a project. Keep IDs and dependent rows.
    if mysql:
        f=columns(c,execute,mysql,'technical_agreements')['project_id']
        if f['Null']=='NO':execute(c,'ALTER TABLE technical_agreements MODIFY COLUMN project_id BIGINT NULL')
    elif columns(c,execute,mysql,'technical_agreements')['project_id']['notnull']:
        c.commit();execute(c,'PRAGMA foreign_keys=OFF')
        try:
            statement=next(s for s in ddl(False).split(';') if 'CREATE TABLE IF NOT EXISTS `technical_agreements`' in s)
            execute(c,statement.replace('`technical_agreements`','`documents_updated`',1))
            names=','.join('`'+n+'`' for n in columns(c,execute,mysql,'technical_agreements'))
            execute(c,f'INSERT INTO documents_updated ({names}) SELECT {names} FROM technical_agreements')
            execute(c,'DROP TABLE technical_agreements');execute(c,'ALTER TABLE documents_updated RENAME TO technical_agreements');c.commit()
        except Exception:c.rollback();raise
        finally:execute(c,'PRAGMA foreign_keys=ON')

def promote(c,execute,save):
    for r in execute(c,'SELECT DISTINCT document_type FROM technical_agreements WHERE document_type IS NOT NULL').fetchall():
        if not execute(c,'SELECT id FROM document_types WHERE name=?',(r['document_type'],)).fetchone():save(c,'document_types',{'name':r['document_type']})
    for raw in execute(c,'SELECT * FROM technical_experience_files WHERE asset_id IS NOT NULL').fetchall():
        r=dict(raw);a=execute(c,'SELECT * FROM assets WHERE id=?',(r['asset_id'],)).fetchone()
        if not a:continue
        if Path(a['file_name']).suffix.lower() in VIDEO_EXT:
            if not execute(c,'SELECT id FROM videos WHERE asset_id=?',(a['id'],)).fetchone():
                save(c,'videos',{'asset_id':a['id'],'name':Path(a['file_name']).stem,'file_name':a['file_name'],'relative_path':a['relative_path'],'file_size':a['file_size']})
        elif not execute(c,'SELECT id FROM agreement_files WHERE asset_id=?',(a['id'],)).fetchone():
            did=save(c,'technical_agreements',{'code':'KNOWLEDGE-ASSET-'+str(a['id']),'name':Path(a['file_name']).stem,'document_type':'技术经验资料'})
            save(c,'agreement_files',{'agreement_id':did,'asset_id':a['id']})
