"""Verify archive failures restore both database paths and original files."""
import os,subprocess,sys,tempfile,unittest
from pathlib import Path
class CatalogStorageTests(unittest.TestCase):
    def test_conflicting_destination_rolls_back_all_prior_moves(self):
        code='''
import app
from pathlib import Path
app.initialize();c=app.connect()
for name in ('first.png','second.png'):
    (app.UPLOADS/('legacy-'+name)).write_bytes(name.encode())
    app.save(c,'assets',{'asset_type':'image','file_name':name,'storage_mode':'file','relative_path':'legacy-'+name,'status':'available'})
c.commit();c.close()
conflict=app.UPLOADS/'images'/'2'/'second.png';conflict.parent.mkdir(parents=True);conflict.write_bytes(b'preserve-existing')
try:app.initialize()
except ValueError as e:assert '归档目标已有文件' in str(e)
else:raise AssertionError('Expected archive conflict')
c=app.connect()
for row in c.execute('SELECT * FROM assets').fetchall():
    assert row['relative_path']=='legacy-'+row['file_name']
    assert (app.UPLOADS/row['relative_path']).read_bytes()==row['file_name'].encode()
assert conflict.read_bytes()==b'preserve-existing'
assert not (app.UPLOADS/'images'/'1'/'first.png').exists()
c.close()
'''
        with tempfile.TemporaryDirectory() as data:
            result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parent,env=dict(os.environ,AOI_DATA=data,DB_ENGINE='sqlite',PYTHONDONTWRITEBYTECODE='1'),capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode())
if __name__=='__main__':unittest.main()
