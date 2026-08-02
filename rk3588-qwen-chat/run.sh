#!/bin/sh
# Board-side Qwen3 chat client: direct HTTP to local RKLLM, no agent/tools
cd /opt/qwen-chat
export PYTHONPATH=/opt/agentscope/site-packages
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
exec python3 chat.py "$@"
