#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d env ]]; then
  python3 -m venv env
  env/bin/python -m pip install --upgrade pip
  env/bin/python -m pip install -r requirements.txt
fi
exec env/bin/python chipforge_workstation.py "$@"
