"""Export a local training checkpoint as pure tensor weights; never overwrite the source.

Default loading is weights_only=True. --trust-source explicitly permits Python
pickle for a checkpoint you trained or otherwise fully trust, only in this local
CLI. The web server never uses that option.
"""
import argparse
from collections.abc import Mapping
from pathlib import Path
import os,tempfile


def extract_weights(checkpoint,torch):
    if isinstance(checkpoint,Mapping):
        for key in ('model_state_dict','state_dict','model'):
            candidate=checkpoint.get(key)
            if isinstance(candidate,Mapping) and candidate:
                checkpoint=candidate;break
    if not isinstance(checkpoint,Mapping) or not checkpoint:raise ValueError('未找到模型权重字典；支持 model_state_dict、state_dict 或纯权重字典')
    if not all(isinstance(k,str) and torch.is_tensor(v) for k,v in checkpoint.items()):raise ValueError('权重字典必须仅包含字符串键和张量值，不会把其他训练对象写入输出')
    return {k:v.detach().cpu() for k,v in checkpoint.items()}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',help='你自己的原训练检查点 .pt/.pth')
    parser.add_argument('--output',help='默认生成同目录的 原文件名.safe.pt')
    parser.add_argument('--trust-source',action='store_true',help='仅对你自己训练或完全可信的检查点允许本机 pickle 加载；不要用于来源不明文件')
    args=parser.parse_args(argv)
    source=Path(args.source).expanduser().resolve()
    output=Path(args.output).expanduser().resolve() if args.output else source.with_name(source.stem+'.safe.pt')
    if not source.is_file():parser.error('原检查点不存在')
    if source==output or output.exists():parser.error('输出已存在或等于源文件，不会覆盖；请换输出路径')
    try:import torch
    except ImportError:parser.error('请使用已经能运行原模型的 Python 环境执行此命令')
    try:checkpoint=torch.load(str(source),map_location='cpu',weights_only=True)
    except Exception as exc:
        if not args.trust_source:parser.error('安全加载失败。只有确认这是你自己训练的可信文件时，才可加 --trust-source 在本机转换。原始原因：'+str(exc))
        checkpoint=torch.load(str(source),map_location='cpu',weights_only=False)
    weights=extract_weights(checkpoint,torch)
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.converting-',suffix='.tmp',dir=str(output.parent));os.close(fd);temporary=Path(name)
    try:
        torch.save(weights,str(temporary))
        verified=torch.load(str(temporary),map_location='cpu',weights_only=True)
        if set(verified)!=set(weights) or not all(torch.is_tensor(verified[k]) and verified[k].shape==v.shape and verified[k].dtype==v.dtype and torch.equal(verified[k],v) for k,v in weights.items()):raise ValueError('转换后的权重验证失败，未发布输出文件')
        # Exclusive link publishes only the verified complete file; fails rather than overwrite.
        os.link(temporary,output)
        print(f'转换完成：{output}\n已验证 weights_only=True 可加载，权重张量完全一致。原文件未修改。请在网页选择 {output.stem} 后重新提交图片。')
    finally:temporary.unlink(missing_ok=True)
if __name__=='__main__':main()
