SUMMARY = "Board-side Qwen3 chat client (direct HTTP to local RKLLM)"
DESCRIPTION = "Simple CLI chat client that talks to the local RKLLM OpenAI-compatible \
server via HTTP. No agent, no tools — just pure model conversation with \
streaming SSE output and prompt_toolkit Chinese input support."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

FILESEXTRAPATHS:prepend := "${TOPDIR}/../rk3588-qwen-chat:"

SRC_URI = " \
    file://chat.py \
    file://config.py \
    file://run.sh \
"

S = "${WORKDIR}"
do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}/opt/qwen-chat
    install -m 0755 ${WORKDIR}/chat.py ${D}/opt/qwen-chat/chat.py
    install -m 0644 ${WORKDIR}/config.py ${D}/opt/qwen-chat/config.py
    install -m 0755 ${WORKDIR}/run.sh ${D}/opt/qwen-chat/run.sh
}

FILES:${PN} = "/opt/qwen-chat"
# Reuse agentscope's site-packages for requests + prompt_toolkit
RDEPENDS:${PN} = "python3 python3-modules agentscope-board"
