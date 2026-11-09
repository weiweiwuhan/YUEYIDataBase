"""Exercise the assistant and experience imports through authenticated HTTP.

Every test uses an isolated SQLite database and disables model generation. No
API key, paid provider call, production data, or downloaded model is required.
"""
import csv
import http.cookiejar
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parent
PASSWORD = 'assistant-http-test-password'
BOOTSTRAP = """
import app
import auth
app.initialize()
c = app.connect()
try:
    hashed = auth.password_hash('assistant-http-test-password')
    for username, role in [('admin', 'admin'), ('editor', 'editor'), ('other', 'editor')]:
        app.execute(c, 'INSERT INTO app_users (username,password_hash,role) VALUES (?,?,?)',
                    (username, hashed, role))
    app.save(c, 'projects', {'code': 'HTTP-PROJECT', 'name': 'HTTP 测试项目'})
    app.save(c, 'products', {'name': 'HTTP 测试产品'})
    c.commit()
finally:
    c.close()
app.main()
"""


def csv_bytes(headers, rows):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode('utf-8-sig')


class AssistantHTTPTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name) / 'data'
        self.data.mkdir()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        self.base = 'http://127.0.0.1:' + str(port)
        env = dict(os.environ, AOI_DATA=str(self.data), DB_ENGINE='sqlite',
                   HOST='127.0.0.1', PYTHONDONTWRITEBYTECODE='1',
                   AOI_RAG_API_KEY='', AOI_RAG_LOCAL='0',
                   AOI_RAG_BASE_URL='https://api.deepseek.com', AOI_RAG_MODEL='deepseek-chat')
        env.pop('AOI_SECURE_COOKIE', None)
        self.log = tempfile.TemporaryFile()
        self.addCleanup(self.log.close)
        self.process = subprocess.Popen(
            [sys.executable, '-c', BOOTSTRAP, '--no-browser', '--port', str(port)],
            cwd=ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self.addCleanup(self.stop_server)
        self.guest, self.admin, self.editor, self.other = (self.client() for _ in range(4))
        deadline = time.monotonic() + 15
        while True:
            try:
                self.api(self.guest, '/api/state')
                break
            except (OSError, urllib.error.URLError):
                if self.process.poll() is not None or time.monotonic() >= deadline:
                    self.log.seek(0)
                    self.fail('HTTP server did not start: ' + self.log.read().decode(errors='replace'))
                time.sleep(.05)
        for opener, username in ((self.admin, 'admin'), (self.editor, 'editor'), (self.other, 'other')):
            self.api(opener, '/api/auth/login', {'username': username, 'password': PASSWORD})

    def test_long_experience_is_preserved_and_chunked_without_truncation(self):
        solution='检查相机触发线路和光源。'*850+'最终确认现场恢复。'
        content=csv_bytes(['问题类型','问题描述','解决方案'],[['fault_fix','相机长方案维护',solution]])
        query=urlencode({'name':'long.csv','project_id':1,'product_id':1,'status':'已解决'})
        preview=self.api(self.admin,'/api/after-sales/import-preview?'+query,raw=content)
        self.assertFalse(preview['errors'])
        result=self.api(self.admin,'/api/after-sales/import?'+query,raw=content)
        self.assertEqual(result['imported'],1)
        state=self.api(self.admin,'/api/state')
        self.assertEqual(state['data']['after_sales'][0]['resolution'],solution)
        status=self.api(self.editor,'/api/assistant/status')
        self.assertGreaterEqual(status['documents'],2)
        self.assertEqual(status['after_sales_count'],1)

    def test_invalid_knowledge_field_does_not_poison_existing_sources(self):
        valid=csv_bytes(['问题类型','问题描述','解决方案'],[['fault_fix','相机不拍照','检查相机触发线路']])
        self.api(self.admin,'/api/assistant/knowledge-import?name=valid.csv',raw=valid)
        source=self.data/'rag'/'knowledge_sources.json';before=source.read_bytes()
        bad=csv_bytes(['问题类型','问题描述','解决方案'],[['分类'*150,'另一问题','检查线路']])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.api(self.admin,'/api/assistant/knowledge-import?name=bad.csv',raw=bad)
        self.assertEqual(caught.exception.code,400)
        self.assertEqual(source.read_bytes(),before)
        response=self.api(self.editor,'/api/assistant/chat',{'question':'相机不拍照'})
        self.assertEqual(response['mode'],'retrieval_only')
        self.assertTrue(response['sources'])

    def test_technical_experience_attachments_retrieval_edit_delete_and_permissions(self):
        record = {'name':'标注边界规范','category':'标注规范','tags':'轮廓复核',
                  'content':'标注缺陷时沿真实轮廓绘制，边界必须由第二位人员复核。'}
        self.rejected(403,self.guest,'/api/save',{'table':'technical_experiences','record':record})
        eid=self.api(self.editor,'/api/save',{'table':'technical_experiences','record':record})['id']
        query=urlencode({'kind':'technical_experience','experience_id':eid,'name':'边界操作.pdf'})
        upload=self.api(self.editor,'/api/upload?'+query,raw=b'%PDF-test-procedure')
        asset_id=upload['asset_id']
        video=self.api(self.editor,'/api/upload?'+urlencode({'kind':'technical_experience','experience_id':eid,'name':'操作演示.mp4'}),raw=b'0123456789')
        request=urllib.request.Request(self.base+'/api/video?asset_id='+str(video['asset_id']),headers={'Range':'bytes=2-5'})
        with self.guest.open(request) as response:
            self.assertEqual(response.status,206)
            self.assertEqual(response.read(),b'2345')
        status=self.api(self.editor,'/api/assistant/status')
        self.assertEqual(status['technical_experience_count'],1)
        answer=self.api(self.editor,'/api/assistant/chat',{'question':'标注边界如何复核'})
        self.assertTrue(any(r['source_type']=='technical_experiences' and r['source_id']==str(eid) for r in answer['sources']))
        self.assertIn('第二位人员',answer['answer'])
        self.rejected(400,self.editor,'/api/save',{'table':'technical_experience_files','record':{'experience_id':eid}})
        self.rejected(400,self.editor,'/api/save',{'table':'technical_experience_files','record':{'experience_id':eid,'asset_id':asset_id}})
        self.rejected(403,self.editor,'/api/delete',{'table':'technical_experiences','id':eid})
        record['content']='标注缺陷沿真实轮廓绘制，边界由负责人三次复核。'
        self.api(self.editor,'/api/save',{'table':'technical_experiences','id':eid,'record':record})
        answer=self.api(self.editor,'/api/assistant/chat',{'question':'标注边界如何复核'})
        self.assertIn('三次复核',answer['answer'])
        self.assertNotIn('第二位人员',answer['answer'])
        self.api(self.admin,'/api/delete',{'table':'technical_experiences','id':eid})
        self.assertFalse(self.api(self.guest,'/api/state')['data']['technical_experience_files'])
        answer=self.api(self.editor,'/api/assistant/chat',{'question':'标注边界如何复核'})
        self.assertFalse(any(r['source_type']=='technical_experiences' for r in answer['sources']))
        with self.guest.open(self.base+'/api/media?id='+str(asset_id)+'&mode=original') as response:
            self.assertEqual(response.read(),b'%PDF-test-procedure')

    def test_software_modules_and_general_document_upload(self):
        for module in ['大模型测试','AI检测稳定性测试','AI运行时间测试','算法重复误差测试','自定义模块']:
            record={'name':module,'test_module':module,'model_name':'检测软件',
                    'test_method':'连续运行一千次','expected_result':'无异常','actual_result':'平均耗时 18 ms'}
            self.api(self.editor,'/api/save',{'table':'model_tests','record':record})
        state=self.api(self.guest,'/api/state')['data']
        self.assertEqual(len(state['model_tests']),5)
        self.assertEqual(state['model_tests'][-1]['actual_result'],'平均耗时 18 ms')
        record={'project_id':1,'code':'DOC-TEST','name':'工具操作说明','document_type':'操作说明'}
        upload=self.api(self.editor,'/api/upload?'+urlencode({'kind':'agreement_new','name':'工具说明.pdf','record':json.dumps(record)}),raw=b'%PDF-tool-guide')
        state=self.api(self.guest,'/api/state')['data']
        self.assertEqual(state['technical_agreements'][0]['document_type'],'操作说明')
        self.assertEqual(state['agreement_files'][0]['asset_id'],upload['asset_id'])

    def stop_server(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    @staticmethod
    def client():
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def api(self, opener, path, payload=None, raw=None):
        body = raw if raw is not None else (
            json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None)
        headers = {'X-AOI-Client': 'local-v1', 'Content-Type':
                   'application/octet-stream' if raw is not None else 'application/json'}
        request = urllib.request.Request(self.base + path, data=body, headers=headers)
        with opener.open(request, timeout=15) as response:
            self.assertEqual(response.headers.get_content_type(), 'application/json')
            return json.loads(response.read())

    def rejected(self, status, opener, path, payload=None, raw=None):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.api(opener, path, payload, raw)
        try:
            self.assertEqual(caught.exception.code, status)
            error = json.loads(caught.exception.read())
            self.assertTrue(error['error'])
            return error
        finally:
            caught.exception.close()

    def cases(self):
        return self.api(self.guest, '/api/state')['data']['after_sales']

    @staticmethod
    def case_record(**changes):
        return dict(project_id=1, product_id=1, name='相机触发丢帧', status='已解决',
                    symptom='相机触发丢帧，工件经过时没有图像。',
                    resolution='检查编码器触发接线，重新设置相机曝光时间。', **changes)

    @staticmethod
    def import_path(preview=False, **changes):
        query = dict(name='cases.csv', project_id=1, product_id=1, status='已解决')
        query.update(changes)
        return ('/api/after-sales/import-preview?' if preview else '/api/after-sales/import?') + urlencode(query)

    def test_roles_protect_bulk_actions_and_preserve_editor_single_record_access(self):
        for opener, username, role in ((self.admin, 'admin', 'admin'),
                                       (self.editor, 'editor', 'editor')):
            identity = self.api(opener, '/api/state')['auth']
            self.assertEqual((identity['username'], identity['role']), (username, role))
        self.assertIsNone(self.api(self.guest, '/api/state')['auth'])
        self.rejected(403, self.guest, '/api/assistant/status')
        self.rejected(403, self.guest, '/api/assistant/history')
        self.rejected(403, self.guest, '/api/assistant/chat', {'question': '相机触发丢帧'})

        content = csv_bytes(['question', 'solution', 'category'],
                            [['相机触发丢帧', '检查触发接线。', '相机']])
        for opener in (self.guest, self.editor):
            self.rejected(403, opener, self.import_path(preview=True), raw=content)
            self.rejected(403, opener, self.import_path(), raw=content)
            self.rejected(403, opener, '/api/assistant/knowledge-import?name=kb.csv', raw=content)
            self.rejected(403, opener, '/api/assistant/rebuild', {})
        self.assertEqual(self.cases(), [])

        record = self.case_record()
        record['created_by'] = 'forged-author'
        saved = self.api(self.editor, '/api/save', {'table': 'after_sales', 'record': record})
        row = self.cases()[0]
        self.assertEqual(row['id'], saved['id'])
        self.assertEqual(row['created_by'], 'editor')
        self.assertEqual(row['updated_by'], 'editor')
        self.assertTrue(row['created_at'])
        self.assertTrue(row['updated_at'])
        record['resolution'] = '由录入员更新处理方案。'
        self.api(self.editor, '/api/save', {'table': 'after_sales', 'id': saved['id'], 'record': record})
        self.assertEqual(self.cases()[0]['resolution'], record['resolution'])
        self.rejected(403, self.editor, '/api/delete', {'table': 'after_sales', 'id': saved['id']})
        self.api(self.admin, '/api/delete', {'table': 'after_sales', 'id': saved['id']})
        self.assertEqual(self.cases(), [])
        self.assertEqual(self.api(self.admin, '/api/assistant/rebuild', {})['after_sales_count'], 0)

    def test_csv_preview_commit_duplicates_authors_and_atomic_invalid_bindings(self):
        content = csv_bytes(['question', 'solution', 'category'], [
            ['相机触发丢帧', '检查编码器触发线，并重新设置曝光。', '相机'],
            ['输送带速度不稳定', '清洁编码器并检查驱动器参数。', '输送机构'],
        ])
        preview = self.api(self.admin, self.import_path(preview=True), raw=content)
        self.assertEqual((preview['total'], preview['valid_count'], preview['duplicate_count']), (2, 2, 0))
        self.assertEqual(preview['errors'], [])
        self.assertNotIn('rows', preview)
        self.assertEqual(self.cases(), [])
        for item in preview['preview']:
            self.assertEqual(item['record']['project_id'], 1)
            self.assertEqual(item['record']['product_id'], 1)
            self.assertEqual(item['record']['status'], '已解决')
        imported = self.api(self.admin, self.import_path(), raw=content)
        self.assertEqual((imported['imported'], imported['duplicates']), (2, 0))
        self.assertTrue(imported['index_updated'])
        rows = self.cases()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['symptom'], '相机触发丢帧')
        self.assertIn('问题类型：相机', rows[0]['remark'])
        for row in rows:
            self.assertEqual((row['created_by'], row['updated_by']), ('admin', 'admin'))
            self.assertTrue(row['created_at'])
            self.assertTrue(row['updated_at'])
        duplicate = self.api(self.admin, self.import_path(preview=True), raw=content)
        self.assertEqual((duplicate['valid_count'], duplicate['duplicate_count']), (0, 2))
        repeated = self.api(self.admin, self.import_path(), raw=content)
        self.assertEqual((repeated['imported'], repeated['duplicates']), (0, 2))
        self.assertEqual(self.cases(), rows)

        # A valid row before an invalid binding must not be partially committed.
        invalid = csv_bytes(['question', 'solution', 'project_id', 'product_id'], [
            ['镜头划伤', '更换镜头。', 1, 1],
            ['设备震动', '紧固机架。', 999999, 1],
        ])
        plan = self.api(self.admin, self.import_path(preview=True), raw=invalid)
        self.assertEqual(plan['valid_count'], 1)
        self.assertEqual(plan['errors'][0]['row'], 3)
        self.rejected(400, self.admin, self.import_path(), raw=invalid)
        self.assertEqual(self.cases(), rows)

    def test_retrieval_history_feedback_and_automatic_experience_refresh(self):
        initial = self.api(self.editor, '/api/assistant/status')
        self.assertFalse(initial['configured'])
        knowledge = csv_bytes(['问题描述', '解决方案', '问题类型'], [
            ['高温烘箱温控过冲', '重新整定温控 PID 参数并校验热电偶。', '温控'],
        ])
        knowledge_path = '/api/assistant/knowledge-import?' + urlencode({'name': '本地知识.csv'})
        imported = self.api(self.admin, knowledge_path, raw=knowledge)
        self.assertEqual((imported['imported'], imported['duplicates']), (1, 0))
        self.assertEqual(imported['status']['knowledge_count'], 1)
        repeated = self.api(self.admin, knowledge_path, raw=knowledge)
        self.assertEqual((repeated['imported'], repeated['duplicates']), (0, 1))
        self.assertEqual(self.cases(), [])

        record = self.case_record()
        case_id = self.api(self.editor, '/api/save', {'table': 'after_sales', 'record': record})['id']
        dirty = self.api(self.editor, '/api/assistant/status')
        self.assertTrue(dirty['dirty'])
        self.assertEqual((dirty['after_sales_count'], dirty['knowledge_count']), (1, 1))
        answer = self.api(self.editor, '/api/assistant/chat', {'question': '相机触发丢帧'})
        self.assertEqual(answer['mode'], 'retrieval_only')
        self.assertIn('未经大模型分析', answer['warning'])
        self.assertIn(record['resolution'], answer['answer'])
        source_id = 'after_sales:' + str(case_id)
        matching = [source for source in answer['sources'] if source['id'] == source_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]['title'], record['name'])
        self.assertIn(record['resolution'], matching[0]['text'])
        self.assertEqual(matching[0]['source_type'], 'after_sales')
        self.assertFalse(self.api(self.editor, '/api/assistant/status')['dirty'])

        conversation = answer['conversation_id']
        history_path = '/api/assistant/history?' + urlencode({'id': conversation})
        messages = self.api(self.editor, history_path)['messages']
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['answer'], answer['answer'])
        self.assertEqual(messages[0]['sources'], answer['sources'])
        self.assertEqual(messages[0]['question_id'], answer['question_id'])
        self.assertEqual(self.api(self.editor, '/api/assistant/history')['conversations'][0]['id'], conversation)
        self.assertEqual(self.api(self.other, '/api/assistant/history')['conversations'], [])
        for opener in (self.other, self.admin):
            self.rejected(403, opener, history_path)
            self.rejected(403, opener, '/api/assistant/chat',
                          {'question': '继续', 'conversation_id': conversation})
            self.rejected(403, opener, '/api/assistant/feedback',
                          {'question_id': answer['question_id'], 'rating': 'helpful'})
        feedback = self.api(self.editor, '/api/assistant/feedback', {
            'question_id': answer['question_id'], 'rating': 'helpful', 'comment': '与现场经验一致。'})
        self.assertEqual(feedback['rating'], 'helpful')
        self.assertEqual(self.api(self.editor, history_path)['messages'][0]['feedback'],
                         {'rating': 'helpful', 'comment': '与现场经验一致。'})

        record['resolution'] = '更新方案：更换屏蔽触发线并将防抖时间设置为 300 微秒。'
        self.api(self.admin, '/api/save', {'table': 'after_sales', 'id': case_id, 'record': record})
        updated = self.cases()[0]
        self.assertEqual((updated['created_by'], updated['updated_by']), ('editor', 'admin'))
        refreshed = self.api(self.editor, '/api/assistant/chat',
                             {'question': '相机触发丢帧', 'conversation_id': conversation})
        self.assertEqual(refreshed['mode'], 'retrieval_only')
        self.assertIn(record['resolution'], refreshed['answer'])
        self.assertNotEqual(refreshed['index_version'], answer['index_version'])
        self.assertEqual(len(self.api(self.editor, history_path)['messages']), 2)

        self.api(self.admin, '/api/delete', {'table': 'after_sales', 'id': case_id})
        deleted = self.api(self.editor, '/api/assistant/chat', {'question': '相机触发丢帧'})
        self.assertNotIn(source_id, [source['id'] for source in deleted['sources']])
        status = self.api(self.editor, '/api/assistant/status')
        self.assertEqual((status['after_sales_count'], status['knowledge_count'], status['documents']), (0, 1, 1))
        self.assertFalse(status['dirty'])
        index = json.loads((self.data / 'rag' / 'index.json').read_text('utf-8'))
        self.assertNotIn(source_id, [source['id'] for source in index['documents']])
        kb_answer = self.api(self.editor, '/api/assistant/chat', {'question': '高温烘箱温控过冲'})
        self.assertEqual(kb_answer['mode'], 'retrieval_only')
        self.assertIn('校验热电偶', kb_answer['answer'])
        self.assertTrue(kb_answer['sources'])


if __name__ == '__main__':
    unittest.main()
