"""Create a trusted server-local model registry; no model is executed or downloaded."""
import argparse
import json
import ntpath
import os
from pathlib import Path
import tempfile

from offline_registry import DEFAULT_PROJECT, DEFAULT_PYTHON, default_registry

REFERENCE_BACKBONE = 'F:/Fighting!!!!!!!!!!/UniADet-main/dinov3/model.safetensors'


def configured_path(value,preserve_symlink=False):
    """Preserve Windows drive paths even when preparing config on another OS."""
    text = str(value).strip()
    if not text:
        raise ValueError('路径不能为空')
    if ntpath.splitdrive(text)[0] and os.name != 'nt':
        return text.replace('\\', '/')
    path=Path(text).expanduser()
    return str(path.absolute() if preserve_symlink else path.resolve())


def main(argv=None):
    default_data = Path(os.environ.get('AOI_DATA', str(Path(__file__).resolve().parent / 'data'))).expanduser()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir', default=DEFAULT_PROJECT)
    parser.add_argument('--python', default=DEFAULT_PYTHON, help='模型环境的 python.exe，不一定是启动网页的 Python')
    parser.add_argument('--backend', choices=['unified','dinov3','torchscript'], default='unified', help='默认使用最新统一检查点；dinov3仅兼容旧工程')
    parser.add_argument('--checkpoint-dir', help='统一模型默认 project-dir/checkpoints/anomaly，扫描 .pt')
    parser.add_argument('--no-recursive', action='store_true', help='只扫描目录当前层，默认包含子目录')
    parser.add_argument('--backbone-weights', help='默认先检查 project-dir/dinov3/model.safetensors，再用参考脚本路径')
    parser.add_argument('--output', default=str(default_data / 'offline_models.json'))
    parser.add_argument('--force', action='store_true', help='明确覆盖已有配置；默认拒绝覆盖')
    args = parser.parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    if output.exists() and not args.force:
        parser.error(f'已有配置，未覆盖：{output}。确需替换时使用 --force。')
    project = configured_path(args.project_dir)
    checkpoints = configured_path(args.checkpoint_dir or project.rstrip('/\\') + ('/checkpoints/anomaly' if args.backend=='unified' else '/checkpoints'))
    local_backbone = Path(project) / 'dinov3' / 'model.safetensors'
    backbone = configured_path(args.backbone_weights or (str(local_backbone) if local_backbone.is_file() else REFERENCE_BACKBONE))
    python = configured_path(args.python,preserve_symlink=True)
    document = default_registry(project,python)
    document['checkpoint_dir']=checkpoints
    document['recursive']=not args.no_recursive
    document['defaults']['backend']=args.backend
    if args.backend=='dinov3':
        document['defaults'].update(backbone_weights=backbone,input_size=512,extract_layers=[4,12,16,20])
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, ensure_ascii=False, indent=2) + '\n'
    # Prepare complete contents first. --force uses replacement; default reserves
    # the final path exclusively so a concurrent command cannot overwrite it.
    if args.force:
        fd, name = tempfile.mkstemp(prefix='.offline-models-', suffix='.tmp', dir=str(output.parent))
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(encoded);handle.flush();os.fsync(handle.fileno())
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        try:
            with output.open('x', encoding='utf-8') as handle:
                handle.write(encoded);handle.flush();os.fsync(handle.fileno())
        except FileExistsError:
            parser.error(f'配置已由其他操作创建，未覆盖：{output}')
    print(f'已写入本机模型配置：{output}')
    checks = [('模型 Python', python), ('模型工程', project), ('检查点目录', checkpoints)]
    if args.backend=='dinov3':checks.insert(2,('基础权重',backbone))
    missing = []
    for label, value in checks:
        exists = Path(value).is_dir() if label in ('模型工程', '检查点目录') else Path(value).is_file()
        if not exists:
            missing.append(label);print(f'未找到 {label}：{value}')
    project_files=('models/task_model.py','data/dataset.py') if args.backend=='unified' else ('config.py','models/dinov3.py','models/feature_extractor.py','models/weidino.py') if args.backend=='dinov3' else ()
    project_missing = [name for name in project_files if not (Path(project) / name).is_file()]
    if project_missing:
        print('工程中尚未找到：' + '、'.join(project_missing))
    directory = Path(checkpoints)
    files = sorted(p for p in (directory.iterdir() if args.no_recursive else directory.rglob('*')) if p.is_file() and p.suffix.lower()=='.pt') if directory.is_dir() else []
    print(f'发现 {len(files)} 个 .pt 检查点，网页会自动扫描该目录'+('。' if args.no_recursive else '及其子目录。'))
    if args.backend=='unified':print('使用统一 format_version=2 检查点；按模型自身尺寸/预处理预测，使用0–1分数，无需额外基础权重。')
    if args.backend=='dinov3' and not args.backbone_weights and backbone == configured_path(REFERENCE_BACKBONE):
        print('基础权重使用参考脚本中的路径；请在实际模型电脑核对。')
    if missing or project_missing or not files:
        print('配置已保存，但运行前仍需修正上述缺失项。未执行模型，不能视为推理就绪。')
    else:
        print('路径检查通过；尚未加载模型或验证依赖，请在网页用一张图片验证实际推理。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
