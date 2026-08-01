#!/usr/bin/env bash
# AgentScope Agent 自动化测试脚本
# 用法: ./run_test.sh "测试名" "输入1" "输入2" ...
set -euo pipefail
cd "$(dirname "$0")"

TEST_NAME="$1"; shift
INPUTS=("$@")
INPUT_FILE=$(mktemp)
for line in "${INPUTS[@]}"; do
  printf '%s\n' "$line"
done > "$INPUT_FILE"
printf '/quit\n' >> "$INPUT_FILE"

echo "=== TEST: $TEST_NAME ==="
timeout 300 bash -c 'cat "'"$INPUT_FILE"'" | ./run.sh 2>&1' || true
rm -f "$INPUT_FILE"
echo "=== END: $TEST_NAME ==="
