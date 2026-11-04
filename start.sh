#!/bin/sh
cd "$(dirname "$0")" || exit 1
python3 ensure_deps.py || exit 1
exec python3 app.py
