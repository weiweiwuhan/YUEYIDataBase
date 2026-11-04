#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 ensure_deps.py
exec python3 app.py --no-browser --host 0.0.0.0 --port 8765
