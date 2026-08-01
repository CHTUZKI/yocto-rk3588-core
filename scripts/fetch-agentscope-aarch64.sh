#!/usr/bin/env bash
# Build a Python 3.12 aarch64 AgentScope 2.0.5 site-packages archive for Yocto.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="${ROOT}/deploy/vendor"
SITE="${VENDOR}/agentscope-site"
WHEELS="${VENDOR}/agentscope-wheels"
TARBALL="${VENDOR}/agentscope-aarch64-site.tar.gz"
PIP_INDEX="${PIP_INDEX:-https://pypi.org/simple}"

mkdir -p "${VENDOR}"
rm -rf "${SITE}" "${WHEELS}"
mkdir -p "${SITE}" "${WHEELS}"

PIP=(python3 -m pip)
CROSS=(
  --platform manylinux_2_17_aarch64
  --python-version 312
  --implementation cp
  --abi cp312
  --only-binary=:all:
)

PKGS=(
  'agentscope==2.0.5'
  'prompt_toolkit>=3.0.47'
  openai httpx aioitertools docstring-parser filetype json5 json-repair
  'mcp<2.0.0' python-datauri
  opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
  opentelemetry-semantic-conventions python-socketio shortuuid
  python-frontmatter aiofiles jinja2 tree-sitter tree-sitter-bash tzdata
  pydantic pydantic-core typing-extensions annotated-types
)

for pkg in "${PKGS[@]}"; do
  echo "Downloading ${pkg}"
  "${PIP[@]}" download -d "${WHEELS}" -i "${PIP_INDEX}" "${CROSS[@]}" "${pkg}"
done

"${PIP[@]}" install --no-compile --no-deps --target "${SITE}" \
  "${CROSS[@]}" --no-index --find-links "${WHEELS}" "${PKGS[@]}"

find "${SITE}" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "${SITE}" -type d \( -name tests -o -name test \) -prune -exec rm -rf {} +
tar -C "${VENDOR}" -czf "${TARBALL}" agentscope-site
ls -lh "${TARBALL}"
