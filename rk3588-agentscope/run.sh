#!/bin/sh
# Board-side AgentScope agent launcher
cd /opt/agentscope
export PYTHONPATH=/opt/agentscope/site-packages
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
exec python3 main.py "$@"
