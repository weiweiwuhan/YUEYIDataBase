"""Local administrator provisioning; credentials are written once to a private file."""
import argparse,os,csv
from pathlib import Path
import app,auth

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--count',type=int,default=50);parser.add_argument('--prefix',default='member');parser.add_argument('--output',required=True)
    args=parser.parse_args();output=Path(args.output).resolve()
    if output.is_relative_to(app.ROOT):raise SystemExit('请将密码清单保存到仓库之外')
    # Reserve a private output before modifying the database; never overwrite an existing list.
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    c=None;committed=False
    try:
        app.initialize();c=app.connect();entries=auth.create_accounts(c,app.execute,args.count,args.prefix)
        with os.fdopen(fd,'w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['username','password','role']);writer.writeheader();writer.writerows(entries);f.flush();os.fsync(f.fileno())
        c.commit();app.invalidate_state();committed=True
        print(f'已创建 {len(entries)} 个独立密码账号；密码清单仅保存到指定文件。')
    finally:
        if c:c.close()
        if not committed:output.unlink(missing_ok=True)
if __name__=='__main__':main()
