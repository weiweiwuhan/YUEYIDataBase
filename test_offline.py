"""Offline queue integration tests with a synthetic runner, never a production model.

These fixtures validate orchestration and score-map rendering only. They do not
claim actual DINOv3 model accuracy or checkpoint compatibility.
"""
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from offline_queue import OfflineQueue


OWNER = {'id': 1, 'username': 'test-editor', 'role': 'editor'}
OTHER = {'id': 2, 'username': 'other-editor', 'role': 'editor'}
ADMIN = {'id': 3, 'username': 'test-admin', 'role': 'admin'}
PARAMS = {'seg_threshold': .5, 'image_threshold': None,
          'min_area': 8, 'alpha': .5, 'smooth_sigma': 0}
TERMINAL = {'completed', 'completed_with_errors', 'failed', 'cancelled', 'interrupted'}

# The synthetic runner is deliberately written only under TemporaryDirectory.
# It requires no checkpoint, torch runtime, GPU, or external service.
RUNNER = r'''
import argparse,json,sys,time
import numpy as np
from PIL import Image
p=argparse.ArgumentParser()
p.add_argument('--model-json',required=True)
p.add_argument('--serve',action='store_true')
a=p.parse_args()
print(json.dumps({'ready':True}),flush=True)
for line in sys.stdin:
    try:
        request=json.loads(line)
        with Image.open(request['input']) as im:
            r,g,b=im.convert('RGB').getpixel((0,0))
        if g==13:raise ValueError('synthetic per-image failure')
        if g==50:time.sleep(.8)
        scores=np.full((8,8),.01,dtype=np.float32)
        if r>=100:scores[2:6,2:6]=.8
        np.save(request['output'],scores,allow_pickle=False)
        print(json.dumps({'ok':True,'image_score':float(scores.max()),'height':8,'width':8}),flush=True)
    except Exception as e:
        print(json.dumps({'ok':False,'error':str(e)}),flush=True)
'''


class OfflineQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runner = self.root / 'synthetic_runner.py'
        self.runner.write_text(RUNNER, encoding='utf-8')
        self.checkpoint = self.root / 'synthetic-test-only.pt'
        self.checkpoint.write_bytes(b'test fixture; not a loadable checkpoint')
        self.registry = self.root / 'models.json'
        self.registry.write_text(json.dumps({'models': [{
            'id': 'fixture-model', 'name': 'Synthetic test-only model',
            'backend': 'torchscript', 'python': sys.executable,
            'checkpoint': str(self.checkpoint), 'device': 'cpu',
        }]}), encoding='utf-8')
        self.data = self.root / 'data'
        self.queue = self.make_queue()

    def tearDown(self):
        if self.queue is not None:
            self.queue.close()
        self.temp.cleanup()

    def make_queue(self):
        return OfflineQueue(self.data, registry_path=self.registry,
                            runner_path=self.runner)

    def new_job(self, params=None):
        return self.queue.create(OWNER, 'fixture-model', dict(PARAMS if params is None else params))

    def upload(self, job, name='source.png', color=(200, 10, 20)):
        buf = io.BytesIO()
        Image.new('RGB', (64, 48), color).save(buf, format='PNG')
        raw = buf.getvalue()
        return self.queue.upload(OWNER, job['id'], name, io.BytesIO(raw), len(raw))

    def wait(self, job, expected=None, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.queue.get(OWNER, job['id'])
            if state['status'] in TERMINAL:
                if expected is not None:
                    self.assertEqual(state['status'], expected, state)
                return state
            time.sleep(.025)
        self.fail('Job did not reach a terminal state: ' + repr(state))

    def test_single_image_overlay_and_raw_threshold_adjustment(self):
        job = self.new_job()
        item = self.upload(job)
        self.queue.submit(OWNER, job['id'])
        state = self.wait(job, 'completed')
        self.assertEqual(len(state['items']), 1)
        finished = state['items'][0]
        self.assertEqual(finished['id'], item['id'])
        self.assertEqual(finished['status'], 'completed', finished)
        self.assertTrue(finished['result']['is_anomaly'])
        self.assertGreater(finished['result']['defect_pixels'], 0)
        for kind in ('original', 'overlay', 'mask'):
            with Image.open(self.queue.file(OWNER, job['id'], item['id'], kind)) as image:
                self.assertEqual(image.size, (64, 48), kind)
        original = Image.open(self.queue.file(OWNER, job['id'], item['id'], 'original')).convert('RGB')
        overlay = Image.open(self.queue.file(OWNER, job['id'], item['id'], 'overlay')).convert('RGB')
        self.assertFalse(np.array_equal(np.asarray(original), np.asarray(overlay)))
        self.assertEqual(original.getpixel((0, 0)), overlay.getpixel((0, 0)))
        gated = self.queue.resegment(OWNER, job['id'], item['id'], {**PARAMS, 'image_threshold': .9})
        self.assertEqual(gated['result']['defect_pixels'], 0)
        filtered = self.queue.resegment(OWNER, job['id'], item['id'], {**PARAMS, 'min_area': 5000})
        self.assertEqual(filtered['result']['defect_pixels'], 0)
        # A threshold above all raw scores must clear the mask without model rerun.
        changed = self.queue.resegment(OWNER, job['id'], item['id'],
                                       {**PARAMS, 'seg_threshold': 1.1})
        self.assertEqual(changed['result']['defect_pixels'], 0)
        self.assertFalse(changed['result']['is_anomaly'])
        with Image.open(self.queue.file(OWNER, job['id'], item['id'], 'mask')) as mask:
            self.assertEqual(int(np.asarray(mask).max()), 0)

    def test_batch_returns_each_image_and_isolates_model_failure(self):
        job = self.new_job()
        self.upload(job, 'defect.png', (200, 10, 20))
        self.upload(job, 'normal.png', (10, 10, 20))
        self.upload(job, 'bad-inference.png', (200, 13, 20))
        self.queue.submit(OWNER, job['id'])
        state = self.wait(job, 'completed_with_errors')
        self.assertEqual(len(state['items']), 3)
        by_name = {item['name']: item for item in state['items']}
        self.assertEqual(by_name['defect.png']['status'], 'completed')
        self.assertTrue(by_name['defect.png']['result']['is_anomaly'])
        self.assertEqual(by_name['normal.png']['status'], 'completed')
        self.assertFalse(by_name['normal.png']['result']['is_anomaly'])
        self.assertEqual(by_name['bad-inference.png']['status'], 'failed')
        self.assertTrue(by_name['bad-inference.png'].get('error'))

    def test_completed_image_is_readable_while_batch_is_still_running(self):
        job = self.new_job()
        first = self.upload(job, 'first.png')
        self.upload(job, 'slow-second.png', (200, 50, 20))
        self.queue.submit(OWNER, job['id'])
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = self.queue.get(OWNER, job['id'])
            if state['items'][0]['status'] == 'completed':
                break
            time.sleep(.01)
        else:
            self.fail('First image result was not published: ' + repr(state))
        self.assertEqual(state['status'], 'running', state)
        self.assertIn(state['items'][1]['status'], ('uploaded', 'running'))
        with Image.open(self.queue.file(OWNER, job['id'], first['id'], 'overlay')) as image:
            self.assertEqual(image.size, (64, 48))
        self.wait(job, 'completed')

    def test_job_and_file_access_is_owner_or_admin_only(self):
        job = self.new_job()
        item = self.upload(job)
        with self.assertRaises(PermissionError):
            self.queue.get(OTHER, job['id'])
        with self.assertRaises(PermissionError):
            self.queue.upload(OTHER, job['id'], 'foreign.png', io.BytesIO(b'no'), 2)
        with self.assertRaises(PermissionError):
            self.queue.file(OTHER, job['id'], item['id'], 'original')
        public = self.queue.get(ADMIN, job['id'])
        self.assertEqual(public['id'], job['id'])
        self.assertNotIn('model_config', public)
        self.assertNotIn('original_file', public['items'][0])
        self.assertTrue(Path(self.queue.file(ADMIN, job['id'], item['id'], 'original')).is_file())
        self.assertFalse(any(x['id'] == job['id'] for x in self.queue.list(OTHER)))
        with self.assertRaises((PermissionError, ValueError)):
            self.queue.get(OWNER, '../../outside')

    def test_invalid_images_names_parameters_and_missing_model(self):
        with self.assertRaises(ValueError):
            self.queue.create(OWNER, 'not-configured', PARAMS)
        for values in ({'seg_threshold': -1}, {'alpha': 1.5},
                       {'min_area': 1.5}, {'smooth_sigma': -1},
                       {'seg_threshold': float('nan')}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.new_job({**PARAMS, **values})
        job = self.new_job()
        for name in ('../outside.png', 'bad/name.png'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.upload(job, name)
        with self.assertRaises(ValueError):
            self.queue.upload(OWNER, job['id'], 'too-large.png', io.BytesIO(b''), 33*1024*1024)
        with self.assertRaises((ValueError, OSError)):
            self.queue.upload(OWNER, job['id'], 'bad.png', io.BytesIO(b'bad'), 3)
        self.assertEqual(len(self.queue.get(OWNER, job['id'])['items']), 0)
        with self.assertRaises(ValueError):
            self.queue.submit(OWNER, job['id'])

    def test_simulated_crash_marks_running_job_interrupted(self):
        job = self.new_job()
        item = self.upload(job)
        self.queue.close()
        self.queue = None
        manifest = self.data / 'offline_tests' / job['id'] / 'job.json'
        state = json.loads(manifest.read_text(encoding='utf-8'))
        state['status'] = 'running'
        state['items'][0]['status'] = 'running'
        manifest.write_text(json.dumps(state), encoding='utf-8')
        self.queue = self.make_queue()
        restored = self.queue.get(OWNER, job['id'])
        self.assertEqual(restored['status'], 'interrupted')
        self.assertEqual(restored['items'][0]['status'], 'failed')
        self.assertEqual(restored['items'][0]['id'], item['id'])

    def test_live_close_interrupts_active_batch_and_persists_terminal_items(self):
        job = self.new_job()
        self.upload(job, 'running.png', (200, 50, 20))
        self.upload(job, 'waiting.png')
        self.queue.submit(OWNER, job['id'])
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = self.queue.get(OWNER, job['id'])
            if state['items'][0]['status'] == 'running':
                break
            time.sleep(.01)
        else:
            self.fail('First item did not start before close: ' + repr(state))
        self.queue.close()
        stopped = self.queue.get(OWNER, job['id'])
        self.assertEqual(stopped['status'], 'interrupted', stopped)
        self.assertTrue(all(item['status'] in ('completed', 'failed', 'cancelled')
                            for item in stopped['items']), stopped)
        self.queue = self.make_queue()
        restored = self.queue.get(OWNER, job['id'])
        self.assertEqual(restored['status'], 'interrupted')
        self.assertEqual([item['status'] for item in restored['items']],
                         [item['status'] for item in stopped['items']])

    def test_upload_stream_does_not_block_polling_and_reserves_submission(self):
        job = self.new_job()
        buf = io.BytesIO()
        Image.new('RGB', (64, 48), (200, 10, 20)).save(buf, format='PNG')
        raw = buf.getvalue()
        entered = threading.Event()
        release = threading.Event()

        class SlowStream(io.BytesIO):
            def read(self, size=-1):
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('Test did not release upload stream')
                return super().read(size)

        with ThreadPoolExecutor(max_workers=2) as pool:
            upload = pool.submit(self.queue.upload, OWNER, job['id'],
                                 'slow-upload.png', SlowStream(raw), len(raw))
            try:
                self.assertTrue(entered.wait(2), 'Upload did not start reading')
                poll = pool.submit(self.queue.get, OWNER, job['id'])
                state = poll.result(timeout=1)
                self.assertEqual(state['status'], 'uploading')
                self.assertEqual(len(state['items']), 0)
                # An upload reservation prevents premature queue submission.
                with self.assertRaises(ValueError):
                    self.queue.submit(OWNER, job['id'])
            finally:
                release.set()
            item = upload.result(timeout=5)
        self.assertEqual(item['status'], 'uploaded')
        self.assertEqual(len(self.queue.get(OWNER, job['id'])['items']), 1)

    def test_queue_cancel_and_saved_job_results_survive_restart(self):
        slow = self.new_job()
        self.upload(slow, color=(200, 50, 20))
        self.queue.submit(OWNER, slow['id'])
        waiting = self.new_job()
        self.upload(waiting)
        self.queue.submit(OWNER, waiting['id'])
        self.assertGreaterEqual(self.queue.get(OWNER, waiting['id'])['queue_position'], 1)
        self.queue.cancel(OWNER, waiting['id'])
        self.assertEqual(self.queue.get(OWNER, waiting['id'])['status'], 'cancelled')
        done = self.wait(slow, 'completed')
        self.queue.close()
        self.queue = self.make_queue()
        restored = self.queue.get(OWNER, slow['id'])
        self.assertEqual(restored['status'], 'completed')
        self.assertEqual(restored['items'][0]['id'], done['items'][0]['id'])
        path = self.queue.file(OWNER, slow['id'], done['items'][0]['id'], 'overlay')
        self.assertTrue(Path(path).is_file())


if __name__ == '__main__':
    unittest.main(verbosity=2)
