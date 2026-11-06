"""HTTP checks for offline inference using temporary data and a synthetic runner.

The runner fixture tests API integration, not the accuracy of a production model.
"""
import http.cookiejar
import io
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

from PIL import Image

import auth
from test_offline import PARAMS, RUNNER, TERMINAL


ROOT = Path(__file__).resolve().parent
BOOTSTRAP = """
import os
import app
from offline_queue import OfflineQueue
app.OFFLINE_ENGINE = OfflineQueue(
    app.DATA, registry_path=os.environ['AOI_TEST_REGISTRY'],
    runner_path=os.environ['AOI_TEST_RUNNER'])
app.main()
"""


class OfflineHTTPTests(unittest.TestCase):
    def test_authenticated_offline_upload_predict_and_resegment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'data'
            data.mkdir()
            runner = root / 'synthetic_runner.py'
            runner.write_text(RUNNER, encoding='utf-8')
            checkpoint = root / 'synthetic-test-only.pt'
            checkpoint.write_bytes(b'test fixture, not a loadable model')
            registry = root / 'models.json'
            registry.write_text(json.dumps({'models': [{
                'id': 'http-fixture', 'name': 'Synthetic HTTP test-only model',
                'backend': 'torchscript', 'python': sys.executable,
                'checkpoint': str(checkpoint), 'device': 'cpu',
            }]}), encoding='utf-8')
            with sqlite3.connect(data / 'aoi.db') as db:
                auth.initialize(db, lambda c, q, args=(): c.execute(q, args), False)
                for username, role in [('editor', 'editor'), ('other', 'editor'), ('admin', 'admin')]:
                    db.execute('INSERT INTO app_users (username,password_hash,role) VALUES (?,?,?)',
                               (username, auth.password_hash('offline-test-password'), role))
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            env = dict(os.environ, AOI_DATA=str(data), DB_ENGINE='sqlite',
                       AOI_TEST_REGISTRY=str(registry), AOI_TEST_RUNNER=str(runner),
                       HOST='127.0.0.1', PYTHONDONTWRITEBYTECODE='1')
            env.pop('AOI_SECURE_COOKIE', None)
            base = 'http://127.0.0.1:' + str(port)

            def client():
                return urllib.request.build_opener(
                    urllib.request.ProxyHandler({}),
                    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

            guest, owner, other, admin = (client() for _ in range(4))

            def request(opener, path, payload=None, raw=None):
                body = raw if raw is not None else (
                    json.dumps(payload).encode() if payload is not None else None)
                headers = {'X-AOI-Client': 'local-v1', 'Content-Type':
                           'application/octet-stream' if raw is not None else 'application/json'}
                req = urllib.request.Request(base + path, data=body, headers=headers)
                with opener.open(req, timeout=10) as response:
                    return response.read(), response.headers.get_content_type()

            def api(opener, path, payload=None, raw=None):
                body, ctype = request(opener, path, payload, raw)
                self.assertEqual(ctype, 'application/json')
                return json.loads(body)

            def denied(opener, path, payload=None):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    api(opener, path, payload)
                self.assertEqual(caught.exception.code, 403)
                caught.exception.close()

            with tempfile.TemporaryFile() as log:
                process = subprocess.Popen(
                    [sys.executable, '-c', BOOTSTRAP, '--no-browser', '--port', str(port)],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 15
                    while True:
                        try:
                            api(guest, '/api/state')
                            break
                        except (OSError, urllib.error.URLError):
                            if process.poll() is not None or time.monotonic() >= deadline:
                                log.seek(0)
                                self.fail('HTTP server did not start: ' + log.read().decode(errors='replace'))
                            time.sleep(.05)
                    script, ctype = request(guest, '/offline.js')
                    self.assertEqual(ctype, 'text/javascript')
                    self.assertGreater(len(script), 100)
                    denied(guest, '/api/offline/models')
                    denied(guest, '/api/offline/jobs', {'model_id': 'http-fixture'})
                    for opener, username in ((owner, 'editor'), (other, 'other'), (admin, 'admin')):
                        api(opener, '/api/auth/login',
                            {'username': username, 'password': 'offline-test-password'})
                    models = api(owner, '/api/offline/models')
                    self.assertTrue(models['configured'])
                    self.assertEqual(models['models'][0]['id'], 'http-fixture')
                    self.assertTrue(models['models'][0]['available'])
                    job = api(owner, '/api/offline/jobs',
                              {'model_id': 'http-fixture', 'params': PARAMS})['job']
                    self.assertEqual(job['created_by'], 'editor')
                    job_query = '/api/offline/jobs?' + urlencode({'id': job['id']})
                    denied(other, job_query)
                    self.assertEqual(api(admin, job_query)['job']['id'], job['id'])
                    self.assertEqual(api(other, '/api/offline/jobs')['jobs'], [])
                    image = io.BytesIO()
                    Image.new('RGB', (64, 48), (200, 10, 20)).save(image, format='PNG')
                    upload_query = '/api/offline/upload?' + urlencode({
                        'job_id': job['id'], 'name': 'HTTP 原图.png'})
                    item = api(owner, upload_query, raw=image.getvalue())['item']
                    self.assertEqual(item['name'], 'HTTP 原图.png')
                    api(owner, '/api/offline/submit', {'job_id': job['id']})
                    deadline = time.monotonic() + 20
                    while True:
                        finished = api(owner, job_query)['job']
                        if finished['status'] in TERMINAL:
                            break
                        if time.monotonic() >= deadline:
                            self.fail('Offline HTTP job did not finish: ' + repr(finished))
                        time.sleep(.025)
                    self.assertEqual(finished['status'], 'completed', finished)
                    self.assertEqual(len(finished['items']), 1)
                    self.assertTrue(finished['items'][0]['result']['is_anomaly'])
                    self.assertNotIn('model_config', finished)
                    file_query = '/api/offline/file?' + urlencode({
                        'job_id': job['id'], 'item_id': item['id'], 'kind': 'overlay'})
                    denied(other, file_query)
                    png, ctype = request(owner, file_query)
                    self.assertEqual(ctype, 'image/png')
                    with Image.open(io.BytesIO(png)) as overlay:
                        self.assertEqual(overlay.size, (64, 48))
                    changed = api(owner, '/api/offline/resegment', {
                        'job_id': job['id'], 'item_id': item['id'],
                        'params': {**PARAMS, 'seg_threshold': 1.1},
                    })['item']
                    self.assertFalse(changed['result']['is_anomaly'])
                    self.assertEqual(changed['result']['defect_pixels'], 0)
                    mask_query = '/api/offline/file?' + urlencode({
                        'job_id': job['id'], 'item_id': item['id'], 'kind': 'mask'})
                    mask, _ = request(admin, mask_query)
                    with Image.open(io.BytesIO(mask)) as rendered:
                        self.assertEqual(rendered.getextrema(), (0, 0))
                finally:
                    if process.poll() is None:
                        process.send_signal(signal.SIGINT)
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
