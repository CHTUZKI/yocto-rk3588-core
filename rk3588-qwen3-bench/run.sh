#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv --without-pip .venv 2>/dev/null || python3 -m venv .venv
  if [ ! -x .venv/bin/pip ]; then
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip-rk3588-qwen3-bench.py
    .venv/bin/python /tmp/get-pip-rk3588-qwen3-bench.py
  fi
fi

if ! .venv/bin/python -c 'import requests' 2>/dev/null; then
  .venv/bin/python -m pip install -q -r requirements.txt
fi

export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
exec .venv/bin/python bench.py "$@"
