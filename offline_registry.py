"""Trusted local checkpoint discovery; no model is imported in the web process."""

import os
from pathlib import Path
import re
import shutil
import sys
import uuid

DEFAULT_PROJECT = 'F:/Fighting!!!!!!!!!!/MyDinoFiuntune'
DEFAULT_PYTHON = 'C:/ProgramData/anaconda3/python.exe'


def default_registry(project=DEFAULT_PROJECT, python=DEFAULT_PYTHON):
    return {
        'format_version': 2,
        'defaults': {'backend': 'unified', 'python': str(python),
                     'project_dir': str(project), 'device': 'auto'},
        'checkpoint_dir': str(project).rstrip('/\\') + '/checkpoints/anomaly',
        'recursive': True,
        'models': [],
    }


def resolve_path(value, registry, python=False):
    path = Path(value).expanduser()
    if not path.is_absolute():
        found = shutil.which(str(path)) if python else None
        path = Path(found) if found else registry.parent / path
    return path.absolute() if python else path.resolve()


def discover(content, registry):
    if (not isinstance(content, dict) or not isinstance(content.get('defaults', {}), dict)
            or not isinstance(content.get('models', []), list)):
        raise ValueError('模型配置须包含 defaults 对象和 models 数组')
    defaults = dict(content.get('defaults', {}))
    entries = list(content.get('models', []))
    directory = None
    scan_backend = defaults.get('backend', 'unified')
    project = resolve_path(defaults['project_dir'], registry) if defaults.get('project_dir') else None
    if content.get('checkpoint_dir'):
        directory = resolve_path(content['checkpoint_dir'], registry)
        # Upgrade only the old default scan, without rewriting the user's file
        # or changing explicitly registered legacy models/custom directories.
        if (project and directory == (project / 'checkpoints').resolve()
                and scan_backend == 'dinov3' and content.get('format_version', 1) < 2):
            directory = directory / 'anomaly'
            scan_backend = 'unified'
        elif (directory.name.casefold() == 'anomaly' and scan_backend == 'dinov3'
              and content.get('format_version', 1) < 2):
            scan_backend = 'unified'
        if directory.is_dir():
            known = {os.path.normcase(str(resolve_path(e['checkpoint'], registry)))
                     for e in entries if isinstance(e, dict) and e.get('checkpoint')}
            paths = directory.rglob('*') if content.get('recursive', True) else directory.iterdir()
            for checkpoint in sorted(paths):
                if not checkpoint.is_file() or checkpoint.suffix.lower() != '.pt':
                    continue
                canonical = os.path.normcase(str(checkpoint.resolve()))
                if canonical in known:
                    continue
                known.add(canonical)
                entries.append({'id': 'model-' + uuid.uuid5(uuid.NAMESPACE_URL, canonical).hex[:20],
                                'name': checkpoint.relative_to(directory).with_suffix('').as_posix(),
                                'checkpoint': str(checkpoint), 'backend': scan_backend})
    results = []
    ids = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('模型条目必须为对象')
        model = {**defaults, **entry}
        model.setdefault('backend', 'unified')
        model.setdefault('python', sys.executable)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(model.get('id', ''))) or model['id'] in ids:
            raise ValueError('本地模型配置包含非法或重复编号')
        ids.add(model['id'])
        model.setdefault('name', model['id'])
        for key in ('project_dir', 'checkpoint', 'backbone_weights', 'python'):
            if model.get(key):
                model[key] = str(resolve_path(model[key], registry, python=key == 'python'))
        required = ['python', 'checkpoint']
        if model['backend'] == 'unified':
            required += ['project_dir']
        elif model['backend'] == 'dinov3':
            required += ['project_dir', 'backbone_weights']
        missing = [key for key in required if not model.get(key) or not Path(model[key]).exists()]
        if model['backend'] == 'unified' and model.get('project_dir') and Path(model['project_dir']).is_dir():
            missing += [name for name in ('models/task_model.py', 'data/dataset.py')
                        if not (Path(model['project_dir']) / name).is_file()]
        supported = model['backend'] in ('unified', 'dinov3', 'torchscript')
        model['available'] = not missing and supported
        model['reason'] = '本机缺少：' + ', '.join(missing) if missing else ''
        if not supported:
            model['reason'] = '模型后端仅支持 unified、dinov3 或 torchscript'
        results.append(model)
    if directory is not None and not directory.is_dir():
        discovery = '未找到模型目录，请检查本机工程目录下的 checkpoints/anomaly 或 checkpoint_dir 配置。'
    elif directory is not None:
        scope = '包含子目录' if content.get('recursive', True) else '仅当前目录'
        location = 'checkpoints/anomaly' if directory.name.casefold() == 'anomaly' else '配置目录'
        discovery = f'自动扫描 {location} 中的 .pt 检查点（{scope}）；刷新模型列表可发现新文件。'
        if not results:
            discovery += ' 当前没有发现 .pt 文件。'
    else:
        discovery = '使用管理员在本机配置中显式登记的检查点。'
    return results, discovery
