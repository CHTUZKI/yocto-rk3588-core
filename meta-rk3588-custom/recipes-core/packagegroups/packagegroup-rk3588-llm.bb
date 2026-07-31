SUMMARY = "RKLLM Qwen3-4B server and on-board Agent"
DESCRIPTION = "Runtime, 4B model, Flask OpenAI server, and Qwen-Agent for HD-RK3588-CORE"

inherit packagegroup

RDEPENDS:${PN} = " \
    rkllm-runtime \
    qwen3-4b-rkllm \
    rkllm-server \
    qwen-agent-board \
"
