"""Upgrade an isolated pre-feature database twice, preserving records and links."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

class FeatureMigrationTests(unittest.TestCase):
    def test_v17_upgrade_adds_evidence_fields_without_changing_links(self):
        code='''
import app
app.initialize();c=app.connect()
app.save(c,'model_tests',{'id':8,'name':'旧测试','model_name':'模型A'})
app.save(c,'technical_experiences',{'id':9,'name':'旧经验','content':'原始经验'})
c.execute('DROP TABLE knowledge_links')
c.execute('CREATE TABLE knowledge_links (id INTEGER PRIMARY KEY,source_table TEXT,source_id INTEGER,relation TEXT,target_table TEXT,target_id INTEGER,conditions TEXT,confirmation_status TEXT,evidence_test_id INTEGER REFERENCES model_tests(id),created_by TEXT,created_at TEXT,updated_by TEXT,updated_at TEXT)')
c.execute("INSERT INTO knowledge_links (id,source_table,source_id,relation,target_table,target_id,conditions) VALUES (17,'technical_experiences',9,'测试依据','model_tests',8,'原始条件')")
c.commit();c.close()
app.initialize();app.initialize();c=app.connect()
row=dict(c.execute('SELECT * FROM knowledge_links WHERE id=17').fetchone())
assert row['conditions']=='原始条件' and row['source_id']==9 and row['target_id']==8
assert row['evidence_document_id'] is None and row['evidence_locator'] is None
assert not c.execute('PRAGMA foreign_key_check').fetchall()
c.close()
'''
        with tempfile.TemporaryDirectory() as data:
            env=dict(os.environ,AOI_DATA=data,DB_ENGINE='sqlite',PYTHONDONTWRITEBYTECODE='1')
            result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parent,env=env,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode())

    def test_incremental_upgrade_preserves_legacy_data(self):
        code='''
import app
app.initialize()
c=app.connect()
project=app.save(c,'projects',{'code':'P','name':'旧项目'})
test=app.save(c,'model_tests',{'name':'旧测试','model_name':'旧模型','yield_rate':99})
doc=app.save(c,'technical_agreements',{'project_id':project,'name':'旧协议','code':'DOC'})
aid=app.save(c,'assets',{'asset_type':'document','file_name':'old.pdf','storage_mode':'file','status':'available'})
link=app.save(c,'agreement_files',{'agreement_id':doc,'asset_id':aid})
for field in ('test_module','test_method','expected_result','actual_result'):
    c.execute('ALTER TABLE model_tests DROP COLUMN '+field)
c.execute('ALTER TABLE technical_agreements DROP COLUMN document_type')
c.commit();c.close()
app.initialize();app.initialize()
c=app.connect()
assert dict(c.execute('SELECT * FROM model_tests WHERE id=?',(test,)).fetchone())['test_module']=='大模型测试'
assert c.execute('SELECT yield_rate FROM model_tests WHERE id=?',(test,)).fetchone()[0]==99
assert c.execute('SELECT document_type FROM technical_agreements WHERE id=?',(doc,)).fetchone()[0]=='技术协议'
assert c.execute('SELECT asset_id FROM agreement_files WHERE id=?',(link,)).fetchone()[0]==aid
assert not c.execute('PRAGMA foreign_key_check').fetchall()
c.close()
'''
        with tempfile.TemporaryDirectory() as data:
            env=dict(os.environ,AOI_DATA=data,DB_ENGINE='sqlite',PYTHONDONTWRITEBYTECODE='1')
            subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parent,env=env,check=True,capture_output=True)

    def test_v16_upgrade_promotes_attachments_and_categorizes_existing_files(self):
        code='''
import app,sqlite3
from pathlib import Path
c=app.connect();c.executescript(Path('test_fixtures/schema_v1_6.sqlite.sql').read_text())
c.execute("INSERT INTO technical_experiences (id,name,content) VALUES (1,'旧经验','原始步骤')")
for aid,name,body in [(1,'旧规范.pdf',b'%PDF-preserved'),(2,'旧视频.mp4',b'video-preserved')]:
    rel='old-uuid-'+name;(app.UPLOADS/rel).write_bytes(body)
    c.execute("INSERT INTO assets (id,asset_type,file_name,storage_mode,relative_path,status) VALUES (?,'document',?,'file',?,'available')",(aid,name,rel))
    c.execute('INSERT INTO technical_experience_files (experience_id,asset_id) VALUES (1,?)',(aid,))
c.commit();c.close()
app.initialize();app.initialize()
c=app.connect()
assert c.execute('SELECT count(*) FROM technical_agreements').fetchone()[0]==1
assert c.execute('SELECT count(*) FROM videos').fetchone()[0]==1
assert c.execute('SELECT count(*) FROM technical_experience_files').fetchone()[0]==2
assert c.execute('SELECT project_id FROM technical_agreements').fetchone()[0] is None
for aid,kind,body in [(1,'documents',b'%PDF-preserved'),(2,'videos',b'video-preserved')]:
    a=c.execute('SELECT * FROM assets WHERE id=?',(aid,)).fetchone()
    assert a['relative_path'].startswith(kind+'/')
    assert Path(a['relative_path']).name==a['file_name']
    assert (app.UPLOADS/a['relative_path']).read_bytes()==body
assert not c.execute('PRAGMA foreign_key_check').fetchall()
c.close()
'''
        with tempfile.TemporaryDirectory() as data:
            env=dict(os.environ,AOI_DATA=data,DB_ENGINE='sqlite',PYTHONDONTWRITEBYTECODE='1')
            result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parent,env=env,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode())

if __name__=='__main__':unittest.main()
