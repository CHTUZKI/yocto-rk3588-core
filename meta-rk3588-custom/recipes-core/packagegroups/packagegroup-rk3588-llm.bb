SUMMARY = "RKLLM Qwen2.5-Coder-3B server and on-board Agent"
DESCRIPTION = "Runtime, Flask OpenAI server, and Qwen-Agent for HD-RK3588-CORE. \
Model (~4G Coder-3B) is NOT in the image: Rockchip update.img truncates partition blobs >4GiB; \
SCP deploy/models/*.rkllm to /opt/models/ after flash."

inherit packagegroup

RDEPENDS:${PN} = " \
    rkllm-runtime \
    rkllm-server \
    qwen-agent-board \
"
