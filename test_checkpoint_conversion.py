"""Conversion policy/IO tests without requiring a GPU or a real model checkpoint."""
import tempfile,types,sys,unittest
from pathlib import Path
from unittest.mock import patch
import convert_checkpoint as conversion

class Tensor:
    shape=(2,3);dtype='float32'
    def detach(self):return self
    def cpu(self):return self
class ConversionTests(unittest.TestCase):
    def test_reject_non_tensor_training_objects(self):
        torch=types.SimpleNamespace(is_tensor=lambda v:isinstance(v,Tensor))
        with self.assertRaises(ValueError):conversion.extract_weights({'optimizer':'not weights'},torch)
        self.assertIn('layer',conversion.extract_weights({'model_state_dict':{'layer':Tensor()},'epoch':10},torch))
    def test_explicit_trust_and_verified_output_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'training.pt';source.write_bytes(b'original-training-checkpoint')
            calls=[];saved={}
            def load(path,**kwargs):
                calls.append(kwargs['weights_only'])
                if Path(path)==source:
                    if kwargs['weights_only']:raise ValueError('unsupported training metadata')
                    return {'model_state_dict':{'layer':Tensor()},'epoch':10}
                return saved['weights']
            def save(weights,path):saved['weights']=weights;Path(path).write_bytes(b'verified-pure-weights')
            torch=types.SimpleNamespace(load=load,save=save,is_tensor=lambda v:isinstance(v,Tensor),equal=lambda a,b:True)
            with patch.dict(sys.modules,{'torch':torch}):
                with self.assertRaises(SystemExit):conversion.main([str(source)])
                self.assertNotIn(False,calls)
                conversion.main([str(source),'--trust-source'])
                self.assertEqual((Path(tmp)/'training.safe.pt').read_bytes(),b'verified-pure-weights')
                self.assertEqual(source.read_bytes(),b'original-training-checkpoint')
                with self.assertRaises(SystemExit):conversion.main([str(source),'--trust-source'])
            self.assertIn(False,calls);self.assertTrue(calls[-1])
if __name__=='__main__':unittest.main()
