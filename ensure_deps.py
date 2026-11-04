import sys,subprocess
try:import PIL
except ImportError:
    print('Installing Pillow for thumbnails and original image preview...')
    subprocess.run([sys.executable,'-m','pip','install','Pillow>=10,<13'],check=True)
