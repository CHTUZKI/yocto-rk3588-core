#!/usr/bin/env bash
# 测板上 RKLLM token 速度（直连 HTTP）
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv --without-pip .venv 2>/dev/null || python3 -m venv .venv
  if [ ! -x .venv/bin/pip ]; then
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip-rk3588-qwen-chat.py
    .venv/bin/python /tmp/get-pip-rk3588-qwen-chat.py
  fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
exec python bench.py "$@"
