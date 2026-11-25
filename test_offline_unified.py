"""Discovery/probability contracts; optional real upstream CPU checkpoint tests.

Set AOI_TEST_MODEL_PROJECT to an up-to-date MyDinoFiuntune source tree to also
exercise its actual TaskModel with tiny random checkpoints. No production
weights or image data are used, and no accuracy claim is made by these tests.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

from configure_offline import main as configure
from offline_queue import OfflineQueue, parameters, render
from offline_registry import default_registry, discover


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'model project'
        for name in ('models/task_model.py', 'data/dataset.py'):
            target = self.project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
        self.registry = self.root / 'models.json'
        self.config = default_registry(self.project, sys.executable)
        self.directory = self.project / 'checkpoints/anomaly'
        self.directory.mkdir(parents=True)

    def checkpoint(self, name):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    def test_recursive_pt_only_stable_ids_and_refresh(self):
        self.checkpoint('best.pt')
        self.checkpoint('experiment two/best.PT')
        self.checkpoint('ignored.pth')
        self.checkpoint('notes.txt')
        models, message = discover(self.config, self.registry)
        self.assertEqual({m['name'] for m in models}, {'best', 'experiment two/best'})
        self.assertTrue(all(m['available'] and m['backend'] == 'unified' for m in models))
        self.assertTrue(all('backbone_weights' not in m for m in models))
        self.assertIn('子目录', message)
        ids = {m['name']: m['id'] for m in models}
        self.checkpoint('new.pt')
        refreshed, _ = discover(self.config, self.registry)
        self.assertEqual(len(refreshed), 3)
        self.assertTrue(all(m['id'] == ids[m['name']] for m in refreshed if m['name'] in ids))
        self.config['recursive'] = False
        current, _ = discover(self.config, self.registry)
        self.assertEqual({m['name'] for m in current}, {'best', 'new'})

    def test_explicit_entries_deduplicate_and_legacy_is_preserved(self):
        path = self.checkpoint('best.pt')
        self.config['models'] = [{'id': 'manual', 'name': 'Explicit legacy',
                                  'checkpoint': str(path), 'backend': 'dinov3'}]
        models, _ = discover(self.config, self.registry)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]['id'], 'manual')
        self.assertEqual(models[0]['backend'], 'dinov3')
        self.assertIn('backbone_weights', models[0]['reason'])

    def test_old_default_scan_upgrades_without_overwriting_registry(self):
        self.checkpoint('latest.pt')
        (self.directory.parent / 'old.pt').touch()
        self.config.pop('format_version')
        self.config['defaults']['backend'] = 'dinov3'
        self.config['checkpoint_dir'] = str(self.directory.parent)
        before = json.dumps(self.config)
        self.registry.write_text(before, encoding='utf-8')
        queue = OfflineQueue(self.root / 'data', registry_path=self.registry)
        self.addCleanup(queue.close)
        public = queue.models()
        self.assertEqual([(m['name'], m['backend']) for m in public['models']], [('latest', 'unified')])
        self.assertTrue(public['models'][0]['available'])
        self.assertNotIn('checkpoint', public['models'][0])
        self.assertEqual(self.registry.read_text(encoding='utf-8'), before)
        (self.directory / 'latest.pt').unlink()
        self.directory.rmdir()
        self.assertEqual(queue.models()['models'], [])
        self.assertIn('未找到', queue.models()['discovery'])

    def test_custom_directory_and_explicit_v2_backend_are_preserved(self):
        self.checkpoint('test.pt')
        self.config['defaults']['backend'] = 'dinov3'
        models, _ = discover(self.config, self.registry)
        self.assertEqual(models[0]['backend'], 'dinov3')
        self.config.pop('format_version')
        self.config['checkpoint_dir'] = str(self.project / 'custom')
        custom = Path(self.config['checkpoint_dir'])
        custom.mkdir()
        (custom / 'old.pt').touch()
        models, _ = discover(self.config, self.registry)
        self.assertEqual(models[0]['backend'], 'dinov3')

    def test_missing_project_api_is_reported(self):
        self.checkpoint('best.pt')
        (self.project / 'models/task_model.py').unlink()
        models, _ = discover(self.config, self.registry)
        self.assertFalse(models[0]['available'])
        self.assertIn('models/task_model.py', models[0]['reason'])

    def test_config_cli_uses_anomaly_without_backbone_and_refuses_overwrite(self):
        args = ['--project-dir', str(self.project), '--python', sys.executable,
                '--output', str(self.registry)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(configure(args), 0)
        saved = self.registry.read_bytes()
        config = json.loads(saved)
        self.assertEqual(Path(config['checkpoint_dir']), self.directory)
        self.assertNotIn('backbone_weights', config['defaults'])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            configure(args)
        self.assertEqual(self.registry.read_bytes(), saved)

    def test_windows_default_paths_are_preserved_in_generated_config(self):
        with contextlib.redirect_stdout(io.StringIO()):
            configure(['--output', str(self.registry)])
        config = json.loads(self.registry.read_text(encoding='utf-8'))
        self.assertEqual(config['checkpoint_dir'], 'F:/Fighting!!!!!!!!!!/MyDinoFiuntune/checkpoints/anomaly')
        self.assertEqual(config['defaults']['python'], 'C:/ProgramData/anaconda3/python.exe')


class ProbabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / 'image.png'
        Image.new('RGB', (48, 32), (80, 100, 120)).save(self.image)
        self.map = self.root / 'scores.npy'

    def result(self, scores, threshold=.5):
        np.save(self.map, np.asarray(scores, dtype=np.float32), allow_pickle=False)
        return render(self.image, self.map, self.root,
                      parameters({'seg_threshold': threshold, 'min_area': 1}), .8)

    def test_absolute_probability_preserved_and_threshold_endpoints(self):
        scores = np.full((4, 6), .02)
        result = self.result(scores)
        self.assertEqual(result['defect_pixels'], 0)
        self.assertAlmostEqual(result['normalization']['source_max'], .02)
        self.assertEqual(self.result(scores, 0)['defect_pixels'], 48 * 32)
        self.assertEqual(self.result(np.ones((4, 6)), 1)['defect_pixels'], 48 * 32)
        with Image.open(self.root / result['overlay_file']) as image:
            self.assertEqual(image.size, (48, 32))

    def test_multiclass_keeps_background_argmax_and_winning_class(self):
        planes = np.ones((3, 4, 6), dtype=np.float32)
        self.assertEqual(self.result(planes * np.array([.4, .3, .3])[:, None, None], .25)['defect_pixels'], 0)
        result = self.result(planes * np.array([.1, .7, .2])[:, None, None])
        self.assertEqual(result['class_pixels'], {'1': 48 * 32})
        self.assertEqual(result['defect_pixels'], 48 * 32)
        self.assertEqual(self.result(planes * np.array([.1, .7, .2])[:, None, None], .8)['defect_pixels'], 0)

    def test_invalid_saved_scores_and_thresholds_are_rejected(self):
        for score in (np.nan, np.inf, -0.1, 1.2):
            with self.subTest(score=score), self.assertRaises(ValueError):
                self.result(np.full((2, 2), score))
        for key in ('seg_threshold', 'image_threshold'):
            for value in (-.1, 1.01):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    parameters({key: value})


UPSTREAM = os.environ.get('AOI_TEST_MODEL_PROJECT')
HAS_TORCH = importlib.util.find_spec('torch') is not None


@unittest.skipUnless(UPSTREAM and HAS_TORCH, 'Optional: model Python + AOI_TEST_MODEL_PROJECT required')
class UpstreamCheckpointTests(unittest.TestCase):
    """Use the actual project API in a fresh process to avoid module cache pollution."""
    def run_contract(self, native=False, classes=2, invalid_size=False):
        script = r'''
import json,sys
from pathlib import Path
import numpy as np
import torch
from PIL import Image
torch.set_num_threads(1)
root,project,app,native,classes,invalid=sys.argv[1:]
root=Path(root);sys.path.insert(0,project)
from models.task_model import TaskModel,ModelConfig,checkpoint_payload,load_checkpoint
from data.dataset import get_image_transform
torch.manual_seed(23)
model=TaskModel(ModelConfig(mode='anomaly',hidden_size=32,num_heads=4,num_hidden_layers=2,
                           intermediate_size=64,patch_size=16,layers=[0,1],num_classes=int(classes)))
size=None if native=='1' else [32,64]
checkpoint=root/'tiny.pt';torch.save(checkpoint_payload(model,size),checkpoint)
source=root/'source.png'
image=Image.fromarray(np.random.default_rng(42).integers(0,256,(63 if invalid=='1' else 64,96,3),dtype=np.uint8))
image.save(source)
sys.path.insert(0,app)
from offline_runner import LocalPredictor
predictor=LocalPredictor({'backend':'unified','project_dir':project,'checkpoint':str(checkpoint),'device':'cpu'})
if invalid=='1':
    try: predictor.predict(str(source),str(root/'actual.npy'))
    except ValueError as e:
        assert '32' in str(e),str(e)
        assert not (root/'actual.npy').exists()
        print('native-size rejection passed');sys.exit(0)
    raise AssertionError('invalid native size was silently resized')
actual_result=predictor.predict(str(source),str(root/'actual.npy'))
reference,_=load_checkpoint(checkpoint,device='cpu')
with torch.inference_mode():
    image_score,maps=reference(get_image_transform(size,3)(image).unsqueeze(0))
expected=maps[0].numpy()
if expected.shape[0]==1:expected=expected[0]
np.testing.assert_allclose(np.load(root/'actual.npy'),expected,rtol=0,atol=0)
assert abs(actual_result['image_score']-float(image_score.item()))<1e-7
assert predictor.model_info['input_size']==size
assert predictor.model_info['format_version']==2
assert expected.shape[-2:]==((64,96) if size is None else (32,64))
print(json.dumps({'shape':list(expected.shape),'range':[float(expected.min()),float(expected.max())]}))
'''
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, '-c', script, root, str(Path(UPSTREAM).resolve()),
                                     str(Path(__file__).resolve().parent), str(int(native)),
                                     str(classes), str(int(invalid_size))],
                                    capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr[-5000:] + result.stdout[-1000:])

    def test_binary_fixed_non_square_checkpoint(self):
        self.run_contract()

    def test_multiclass_checkpoint(self):
        self.run_contract(classes=3)

    def test_native_resolution_checkpoint(self):
        self.run_contract(native=True)

    def test_native_size_error_does_not_resize_to_512(self):
        self.run_contract(native=True, invalid_size=True)


if __name__ == '__main__':
    unittest.main()
