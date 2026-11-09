"""Upgrade an isolated pre-feature database twice, preserving records and links."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

class FeatureMigrationTests(unittest.TestCase):
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

if __name__=='__main__':unittest.main()
