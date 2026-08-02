#!/bin/sh
# Board-side Qwen-Agent launcher (qwen_agent_onboard.py)
cd /opt/qwen_agent
export PYTHONPATH=/opt/qwen_agent/site-packages
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
exec python3 qwen_agent_onboard.py "$@"
