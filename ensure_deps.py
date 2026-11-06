import sys,subprocess
try:import PIL
except ImportError:
    print('Installing Pillow for thumbnails and original image preview...')
    subprocess.run([sys.executable,'-m','pip','install','Pillow>=10,<13'],check=True)

try:import numpy,scipy
except ImportError:
    subprocess.run([sys.executable,'-m','pip','install','numpy>=1.26,<3','scipy>=1.11,<2'],check=True)

try:import openpyxl
except ImportError:
    subprocess.run([sys.executable,'-m','pip','install','openpyxl>=3.1,<4'],check=True)
