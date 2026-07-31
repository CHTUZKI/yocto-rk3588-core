#!/usr/bin/env bash
# Build an aarch64 site-packages tree for on-board Qwen-Agent (Python 3.12).
# Output: deploy/vendor/qwen-agent-aarch64-site.tar.gz
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="${ROOT}/deploy/vendor"
SITE="${VENDOR}/qwen-agent-site"
WHEELS="${VENDOR}/qwen-agent-wheels"
TARBALL="${VENDOR}/qwen-agent-aarch64-site.tar.gz"
PIP_INDEX="${PIP_INDEX:-https://pypi.org/simple}"

mkdir -p "${VENDOR}"
rm -rf "${SITE}" "${WHEELS}"
mkdir -p "${SITE}" "${WHEELS}"

PIP=(python3 -m pip)
"${PIP[@]}" install -q -U "pip" "wheel" "setuptools"

CROSS=(
  --platform manylinux_2_17_aarch64
  --python-version 312
  --implementation cp
  --abi cp312
  --only-binary=:all:
)

# Minimal set to import Assistant and talk to a local OpenAI-compatible server.
PKGS=(
  qwen-agent
  openai
  httpx
  httpcore
  anyio
  h11
  idna
  certifi
  sniffio
  distro
  jiter
  pydantic
  pydantic-core
  annotated-types
  typing-extensions
  json5
  dashscope
  jsonlines
  jsonschema
  jsonschema-specifications
  referencing
  rpds-py
  attrs
  requests
  urllib3
  charset-normalizer
  aiohttp
  aiohappyeyeballs
  aiosignal
  frozenlist
  multidict
  yarl
  propcache
  python-dateutil
  six
  pyyaml
  tiktoken
  regex
  numpy
  tqdm
  packaging
  eval-type-backport
)

echo "==> Downloading aarch64/universal wheels to ${WHEELS}"
FAILED=()
for pkg in "${PKGS[@]}"; do
  if ! "${PIP[@]}" download -d "${WHEELS}" -i "${PIP_INDEX}" \
      "${CROSS[@]}" "${pkg}" >/tmp/qwen-agent-pip-dl.log 2>&1; then
    # Universal / py3-none-any wheels (no platform tag needed)
    if ! "${PIP[@]}" download -d "${WHEELS}" -i "${PIP_INDEX}" \
        --python-version 312 --only-binary=:all: "${pkg}" \
        >/tmp/qwen-agent-pip-dl2.log 2>&1; then
      echo "WARN: could not download wheel for ${pkg}" >&2
      FAILED+=("${pkg}")
    fi
  fi
done

# jieba is often sdist-only; vendor the pure-python tree from sdist.
if "${PIP[@]}" download -d "${WHEELS}" -i "${PIP_INDEX}" --no-deps jieba \
    >/tmp/qwen-agent-jieba.log 2>&1; then
  :
else
  echo "WARN: jieba download failed (optional for our Agent path)" >&2
fi

echo "==> Installing into ${SITE} (cross aarch64 target)"
# When --platform is set, pip accepts foreign wheels into --target.
"${PIP[@]}" install --no-compile --no-deps --target "${SITE}" \
  "${CROSS[@]}" \
  --no-index --find-links "${WHEELS}" \
  "${PKGS[@]}" 2>/tmp/qwen-agent-pip-install.log

# Unpack jieba sdist manually if present (avoid build isolation needing network).
shopt -s nullglob
for sdist in "${WHEELS}"/jieba-*.tar.gz; do
  tmp=$(mktemp -d)
  tar -xzf "${sdist}" -C "${tmp}"
  src=$(find "${tmp}" -maxdepth 2 -type d -name jieba | head -1)
  if [[ -n "${src}" ]]; then
    cp -a "${src}" "${SITE}/jieba"
    echo "Installed jieba from sdist"
  fi
  rm -rf "${tmp}"
done
shopt -u nullglob

if [[ ! -d "${SITE}/qwen_agent" ]]; then
  echo "ERROR: qwen_agent not installed into ${SITE}" >&2
  echo "Failed downloads: ${FAILED[*]:-none}" >&2
  tail -80 /tmp/qwen-agent-pip-install.log >&2 || true
  exit 1
fi

# Drop caches / tests to shrink the image a bit
find "${SITE}" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "${SITE}" -type d \( -name 'tests' -o -name 'test' \) -exec rm -rf {} + 2>/dev/null || true

echo "==> Packing ${TARBALL}"
tar -C "${VENDOR}" -czf "${TARBALL}" qwen-agent-site
ls -lh "${TARBALL}"
du -sh "${SITE}"
echo "Done. Failed optional pkgs: ${FAILED[*]:-none}"
