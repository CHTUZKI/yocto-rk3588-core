#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv --without-pip .venv 2>/dev/null || python3 -m venv .venv
  if [ ! -x .venv/bin/pip ]; then
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip-rk3588-agentscope.py
    .venv/bin/python /tmp/get-pip-rk3588-agentscope.py
  fi
fi

if ! .venv/bin/python -c 'import agentscope' 2>/dev/null; then
  .venv/bin/python -m pip install -q -r requirements.txt
fi

export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"

# Auto-detect model server: on the board use 127.0.0.1, on PC fall back to board IP
if [ -z "${AGENTSCOPE_MODEL_SERVER:-}" ]; then
  if [ -e /proc/device-tree ] || [ -e /sys/class/rknpu ] || [ "$(uname -m)" = "aarch64" ]; then
    export AGENTSCOPE_MODEL_SERVER="http://127.0.0.1:8080/v1"
  else
    export AGENTSCOPE_MODEL_SERVER="http://192.168.1.14:8080/v1"
  fi
fi

exec .venv/bin/python main.py "$@"
