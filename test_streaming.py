"""Real SSE over local HTTP, including upstream failure and private histories."""
import io,json,os,threading,time,unittest,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
import test_assistant_http as harness
from rag_assistant import RagAssistant

class FakeModel(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def log_message(self,*args):pass
    def do_POST(self):
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if not request.get('stream'):
            self.send_response(400);self.end_headers();return
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        self.wfile.write(b': heartbeat\n\n')
        for part in ('先检查','触发线路。'):
            event={'choices':[{'delta':{'content':part},'finish_reason':None}]}
            self.wfile.write(('data: '+json.dumps(event,ensure_ascii=False)+'\n\n').encode());self.wfile.flush();time.sleep(.15)
        if not self.server.truncated:
            self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');self.wfile.flush()

class StreamingHTTPTests(unittest.TestCase):
    client=staticmethod(harness.AssistantHTTPTests.client)
    api=harness.AssistantHTTPTests.api
    rejected=harness.AssistantHTTPTests.rejected
    stop_server=harness.AssistantHTTPTests.stop_server
    def setUp(self):
        self.model=ThreadingHTTPServer(('127.0.0.1',0),FakeModel);self.model.truncated=False
        threading.Thread(target=self.model.serve_forever,daemon=True).start()
        self.addCleanup(self.model.server_close);self.addCleanup(self.model.shutdown)
        bootstrap=harness.BOOTSTRAP.replace('app.main()',"import os\nos.environ.update(AOI_RAG_LOCAL='1',AOI_RAG_BASE_URL='http://127.0.0.1:%s/v1')\napp.main()"%self.model.server_port)
        with patch.object(harness,'BOOTSTRAP',bootstrap):harness.AssistantHTTPTests.setUp(self)
        self.api(self.admin,'/api/assistant/knowledge-import?name=test.csv',raw='问题描述,解决方案\n相机不拍照,先检查触发线路。\n'.encode('utf-8-sig'))
    def stream(self,payload,opener=None):
        request=urllib.request.Request(self.base+'/api/assistant/chat-stream',json.dumps(payload).encode(),{'Content-Type':'application/json','X-AOI-Client':'local-v1'})
        return (opener or self.editor).open(request,timeout=5)
    def events(self,response):
        kind=None;events=[]
        for line in response:
            text=line.decode().strip()
            if text.startswith('event:'):kind=text[6:].strip()
            if text.startswith('data:'):events.append((kind,json.loads(text[5:])))
        return events
    def test_incremental_delivery_done_and_private_history(self):
        with self.stream({'question':'相机不拍照'}) as response:
            self.assertEqual(response.headers['X-Accel-Buffering'],'no')
            first=None;events=[];kind=None
            for line in response:
                text=line.decode().strip()
                if text.startswith('event:'):kind=text[6:].strip()
                if text.startswith('data:'):
                    event=(kind,json.loads(text[5:]));events.append(event)
                    if kind=='delta' and first is None:
                        first=event[1]['text']
                        # The second upstream token has not arrived and no finished question exists yet.
                        history=self.api(self.editor,'/api/assistant/history')
                        cid=history['conversations'][0]['id']
                        self.assertEqual(self.api(self.editor,'/api/assistant/history?id='+cid)['messages'],[])
            self.assertEqual(first,'先检查')
        done=next(data for kind,data in events if kind=='done')
        self.assertEqual(done['mode'],'model');self.assertEqual(done['answer'],'先检查触发线路。')
        self.assertEqual(''.join(v['text'] for k,v in events if k=='delta'),done['answer'])
        self.assertTrue(done['sources'])
        self.rejected(403,self.other,'/api/assistant/chat-stream',{'question':'相机','conversation_id':done['conversation_id']})
        self.rejected(403,self.guest,'/api/assistant/chat-stream',{'question':'相机'})
        self.rejected(400,self.editor,'/api/assistant/chat-stream',{'question':''})
    def test_truncated_stream_replaces_partial_answer_and_never_saves_it_as_model(self):
        self.model.truncated=True
        with self.stream({'question':'相机不拍照'}) as response:events=self.events(response)
        self.assertTrue(any(k=='delta' for k,v in events))
        done=next(v for k,v in events if k=='done')
        self.assertEqual(done['mode'],'service_error');self.assertIn('中断',done['warning'])
        self.assertNotEqual(done['answer'],'先检查触发线路。');self.assertTrue(any(k=='reset' for k,v in events))
        history=self.api(self.editor,'/api/assistant/history?id='+done['conversation_id'])
        self.assertEqual(history['messages'][0]['mode'],'service_error')

if __name__=='__main__':unittest.main()
