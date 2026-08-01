#!/bin/sh
# Start RKLLM OpenAI-compatible Flask server on the board.
set -e
cd "$(dirname "$0")"
export LD_LIBRARY_PATH="/opt/rkllm${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
MODEL="${1:-/opt/models/Qwen2.5-Coder-3B-Instruct-w8a8-rk3588.rkllm}"
exec python3 flask_server.py \
  --rkllm_model_path "$MODEL" \
  --target_platform rk3588
