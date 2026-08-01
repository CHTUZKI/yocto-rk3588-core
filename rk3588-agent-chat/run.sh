#!/usr/bin/env bash
# 在 PC/WSL 上运行（不是板子）：安装依赖并启动中文对话客户端
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv --without-pip .venv 2>/dev/null || python3 -m venv .venv
  if [ ! -x .venv/bin/pip ]; then
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip-rk3588-chat.py
    .venv/bin/python /tmp/get-pip-rk3588-chat.py
  fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate
if ! .venv/bin/python -c 'import paramiko, prompt_toolkit' 2>/dev/null; then
  .venv/bin/python -m pip install -q -r requirements.txt
fi
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
echo "在本机启动客户端，将 SSH 连接开发板..."
exec python chat.py "$@"
