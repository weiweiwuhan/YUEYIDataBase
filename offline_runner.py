"""Isolated local inference adapter for the supplied DINOv3 segmentation script.

Only a server-side administrator model manifest selects code/weights. This module
never accepts a browser-supplied command, imports no model until executed, and
never downloads weights. Stdout is reserved for the JSON-lines worker protocol.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import importlib
import json
import math
from pathlib import Path
import sys


def _existing_path(value, label, directory=False):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'缺少 {label} 配置')
    path = Path(value).expanduser().resolve()
    exists = path.is_dir() if directory else path.is_file()
    if not exists:
        raise ValueError(f'{label} 不存在：{path}')
    return path


def _device(torch, requested):
    if requested not in ('auto', 'cpu', 'cuda', 'mps'):
        raise ValueError('device 仅支持 auto、cpu、cuda 或 mps')
    has_mps = getattr(torch.backends, 'mps', None)
    if requested == 'auto':
        requested = 'cuda' if torch.cuda.is_available() else 'mps' if has_mps and has_mps.is_available() else 'cpu'
    if requested == 'cuda' and not torch.cuda.is_available():
        raise ValueError('指定了 CUDA，但当前 Python 环境不可用 CUDA')
    if requested == 'mps' and not (has_mps and has_mps.is_available()):
        raise ValueError('指定了 MPS，但当前 Python 环境不可用 MPS')
    return torch.device(requested)


class LocalPredictor:
    """Model instance is loaded once and reused for all requests in a worker."""

    def __init__(self, spec):
        if not isinstance(spec, dict):
            raise ValueError('模型配置必须为 JSON 对象')
        try:
            import numpy as np
            import torch
            from PIL import Image
            import torchvision.transforms as transforms
        except ImportError as exc:
            raise RuntimeError('模型 Python 环境缺少依赖；请在该环境安装 requirements-offline.txt 和本地模型工程依赖') from exc
        self.np, self.torch, self.Image = np, torch, Image
        self.device = _device(torch, spec.get('device', 'auto'))
        size = spec.get('input_size', 512)
        if isinstance(size, bool) or not isinstance(size, int) or not 32 <= size <= 4096:
            raise ValueError('input_size 必须为 32–4096 的整数，并与训练配置一致')
        self.transform = transforms.Compose([
            transforms.Resize((size, size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
        ])
        backend = spec.get('backend', 'dinov3')
        checkpoint = _existing_path(spec.get('checkpoint'), '训练检查点 checkpoint')
        if spec.get('memory_bank'):
            raise ValueError('当前适配器未启用 memory bank 融合；参考脚本默认 use_memory=False。需确认本地 MemoryBank 的安全加载接口后另行接入')
        if backend == 'torchscript':
            self.model = torch.jit.load(str(checkpoint), map_location=self.device).eval()
            self.extractor = None
        elif backend == 'dinov3':
            root = _existing_path(spec.get('project_dir'), '本地模型工程 project_dir', directory=True)
            if not (root / 'config.py').is_file() or not (root / 'models').is_dir():
                raise ValueError('project_dir 需包含 config.py 和 models/；请配置完整的本地模型工程')
            backbone_weights = _existing_path(spec.get('backbone_weights'), 'DINOv3 基础权重 backbone_weights')
            if backbone_weights.suffix.lower() != '.safetensors':
                raise ValueError('DINOv3 基础权重请使用参考脚本中的 .safetensors 文件')
            sys.path.insert(0, str(root))
            config = importlib.import_module('config')
            DINOv3ViTModel = importlib.import_module('models.dinov3').DINOv3ViTModel
            FeatureExtractor = importlib.import_module('models.feature_extractor').FeatureExtractor
            ImprovedAnomalyDetector = importlib.import_module('models.weidino').ImprovedAnomalyDetector
            backbone = DINOv3ViTModel()
            backbone.load_pretrained(str(backbone_weights))
            backbone.freeze()
            backbone.to(self.device).eval()
            extract_layers = spec.get('extract_layers', [4, 12, 16, 20])
            if not isinstance(extract_layers, list) or not extract_layers or not all(isinstance(i, int) and not isinstance(i, bool) for i in extract_layers):
                raise ValueError('extract_layers 必须为与训练匹配的整数列表')
            self.extractor = FeatureExtractor(backbone, layers=extract_layers)
            if hasattr(self.extractor, 'to'):
                self.extractor.to(self.device)
            if hasattr(self.extractor, 'eval'):
                self.extractor.eval()
            self.model = ImprovedAnomalyDetector(
                hidden_size=config.HIDDEN_SIZE,
                layers=config.EXTRACT_LAYERS,
                adapter_dim=getattr(config, 'ADAPTER_DIM', 128),
                num_prototypes=getattr(config, 'NUM_PROTOTYPES', 16),
                lambda_p=config.LAMBDA_P,
                tau=getattr(config, 'TAU', 0.1),
                init_std=config.WEIGHT_INIT_STD,
                focal_alpha=getattr(config, 'FOCAL_ALPHA', 0.25),
                focal_gamma=getattr(config, 'FOCAL_GAMMA', 2.0),
                dice_smooth=getattr(config, 'DICE_SMOOTH', 1.0),
                cls_loss_weight=getattr(config, 'CLS_LOSS_WEIGHT', 1.0),
                seg_loss_weight=getattr(config, 'SEG_LOSS_WEIGHT', 0.1),
                num_defects=0,
            ).to(self.device)
            # Checkpoints must contain tensors/state dictionaries. Never fall
            # back to arbitrary pickle execution when safe loading rejects one.
            try:
                ckpt = torch.load(str(checkpoint), map_location=self.device, weights_only=True)
            except Exception as exc:
                raise ValueError('检查点安全加载失败；请在可信模型环境中另存为纯 state_dict，不能使用 weights_only=False 绕过') from exc
            state = ckpt.get('model_state_dict', ckpt) if isinstance(ckpt, dict) else None
            if not isinstance(state, dict):
                raise ValueError('checkpoint 必须为 state_dict 或包含 model_state_dict 的字典')
            self.model.load_state_dict(state, strict=True)
            self.model.eval()
        else:
            raise ValueError('backend 仅支持 dinov3 或 torchscript')

    def predict(self, input_path, output_path):
        source = _existing_path(input_path, '输入图片')
        output = Path(output_path).resolve()
        if output.suffix.lower() != '.npy':
            raise ValueError('输出文件必须为 .npy 原始分割分数')
        with self.Image.open(source) as image:
            image.seek(0)
            tensor = self.transform(image.convert('RGB')).unsqueeze(0).to(self.device)
        with self.torch.inference_mode():
            features = self.extractor(tensor) if self.extractor is not None else tensor
            result = self.model(features)
        if not isinstance(result, dict) or 'seg_map' not in result:
            raise ValueError('模型输出须为包含 seg_map 的字典')
        scores = result['seg_map']
        if hasattr(scores, 'detach'):
            scores = scores.detach().float().cpu().numpy()
        scores = self.np.asarray(scores, dtype=self.np.float32)
        while scores.ndim > 2 and scores.shape[0] == 1:
            scores = scores[0]
        if scores.ndim != 2 or not scores.size or max(scores.shape) > 16384 or scores.size > 16_777_216:
            raise ValueError('seg_map 须为 H×W 或前导维度均为1的单通道分割图')
        if not self.np.isfinite(scores).all():
            raise ValueError('模型分割分数包含 NaN/Inf，不能生成有效检测结果')
        image_score = result.get('image_score')
        if image_score is None:
            image_score = float(scores.max())
        elif hasattr(image_score, 'detach'):
            if image_score.numel() != 1:
                raise ValueError('单张推理的 image_score 须为单个数值')
            image_score = float(image_score.detach().cpu().item())
        else:
            image_score = float(image_score)
        if not math.isfinite(image_score):
            raise ValueError('image_score 包含 NaN/Inf')
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + '.tmp')
        with temporary.open('wb') as handle:
            self.np.save(handle, scores, allow_pickle=False)
        temporary.replace(output)
        return {'ok': True, 'image_score': image_score, 'height': int(scores.shape[0]), 'width': int(scores.shape[1])}


def _emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-json', required=True)
    parser.add_argument('--input')
    parser.add_argument('--output')
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args(argv)
    try:
        spec = json.loads(Path(args.model_json).read_text(encoding='utf-8-sig'))
        with redirect_stdout(sys.stderr):
            predictor = LocalPredictor(spec)
    except Exception as exc:
        _emit({'ready': False, 'ok': False, 'error': str(exc)})
        return 1
    if args.serve:
        _emit({'ready': True})
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('任务请求必须为 JSON 对象')
                with redirect_stdout(sys.stderr):
                    result = predictor.predict(request['input'], request['output'])
                _emit(result)
            except Exception as exc:
                _emit({'ok': False, 'error': str(exc)})
        return 0
    if not args.input or not args.output:
        parser.error('单次运行需要 --input 和 --output')
    try:
        with redirect_stdout(sys.stderr):
            result = predictor.predict(args.input, args.output)
        _emit(result)
        return 0
    except Exception as exc:
        _emit({'ok': False, 'error': str(exc)})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
