SUMMARY = "Board-side Qwen3 RKLLM benchmark tool"
DESCRIPTION = "CLI benchmark that measures RKLLM generation latency and throughput \
by sending prompts to the local OpenAI-compatible server and timing \
first-token / total generation."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

FILESEXTRAPATHS:prepend := "${TOPDIR}/../rk3588-qwen3-bench:"

SRC_URI = " \
    file://bench.py \
    file://config.py \
    file://run.sh \
"

S = "${WORKDIR}"
do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}/opt/qwen3-bench
    install -m 0755 ${WORKDIR}/bench.py ${D}/opt/qwen3-bench/bench.py
    install -m 0644 ${WORKDIR}/config.py ${D}/opt/qwen3-bench/config.py
    install -m 0755 ${WORKDIR}/run.sh ${D}/opt/qwen3-bench/run.sh
}

FILES:${PN} = "/opt/qwen3-bench"
# Reuse agentscope's site-packages for requests
RDEPENDS:${PN} = "python3 python3-modules agentscope-board"
