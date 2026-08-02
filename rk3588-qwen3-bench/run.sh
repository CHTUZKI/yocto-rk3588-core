#!/bin/sh
# Board-side Qwen3 RKLLM benchmark
cd /opt/qwen3-bench
export PYTHONPATH=/opt/agentscope/site-packages
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
exec python3 bench.py "$@"
