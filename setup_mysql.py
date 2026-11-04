"""Local Docker Compose setup. Retains existing credentials and volumes."""
import os,secrets,subprocess,webbrowser
from pathlib import Path
os.chdir(Path(__file__).resolve().parent)
p=Path('.env')
if not p.exists():
    p.write_text('DB_PASSWORD='+secrets.token_hex(24)+'\nMYSQL_ROOT_PASSWORD='+secrets.token_hex(24)+'\n',encoding='utf-8')
    try:p.chmod(0o600)
    except OSError:pass
print('Starting MySQL and AOI app. Initial run downloads Docker images. Existing data is retained.')
subprocess.run(['docker','compose','up','--build','-d'],check=True)
print('Open http://127.0.0.1:8765 after the app starts. Data entry and uploads now use MySQL.')
webbrowser.open('http://127.0.0.1:8765')
