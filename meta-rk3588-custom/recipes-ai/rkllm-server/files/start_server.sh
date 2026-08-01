#!/bin/sh
# Start RKLLM OpenAI-compatible Flask server on the board.
# Auto-detects model path: /opt/models first, then /mnt/usb/models.
set -e
cd "$(dirname "$0")"
export LD_LIBRARY_PATH="/opt/rkllm${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# If model path is given as argument, use it directly
if [ -n "${1:-}" ]; then
    MODEL="$1"
else
    # Auto-detect: scan common locations for any .rkllm file
    MODEL=""
    for dir in /opt/models /mnt/usb/models; do
        if [ -d "$dir" ]; then
            found=$(ls "$dir"/*.rkllm 2>/dev/null | head -n 1)
            if [ -n "$found" ]; then
                MODEL="$found"
                break
            fi
        fi
    done
    if [ -z "$MODEL" ]; then
        echo "ERROR: no .rkllm model found in /opt/models or /mnt/usb/models" >&2
        exit 1
    fi
fi

echo "Starting RKLLM server with model: $MODEL"
exec python3 flask_server.py \
  --rkllm_model_path "$MODEL" \
  --target_platform rk3588
