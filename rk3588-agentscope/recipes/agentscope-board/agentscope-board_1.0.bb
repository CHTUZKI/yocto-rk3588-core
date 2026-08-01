SUMMARY = "AgentScope 2 board-side Qwen3 agent"
DESCRIPTION = "Lightweight AgentScope ReAct agent with safe board file and Python tools"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

COMPATIBLE_HOST = "aarch64.*-linux"
FILESEXTRAPATHS:prepend := "${TOPDIR}/../rk3588-agentscope:${TOPDIR}/../deploy/vendor:"

SRC_URI = " \
    file://main.py \
    file://board_tools.py \
    file://config.py \
    file://agentscope-aarch64-site.tar.gz \
"

S = "${WORKDIR}"
do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_check_vendor() {
    if [ ! -f "${TOPDIR}/../deploy/vendor/agentscope-aarch64-site.tar.gz" ]; then
        bbfatal "agentscope-board: missing deploy/vendor/agentscope-aarch64-site.tar.gz"
    fi
}
addtask check_vendor before do_fetch

do_install() {
    install -d ${D}/opt/agentscope
    install -m 0755 ${WORKDIR}/main.py ${D}/opt/agentscope/main.py
    install -m 0644 ${WORKDIR}/board_tools.py ${D}/opt/agentscope/board_tools.py
    install -m 0644 ${WORKDIR}/config.py ${D}/opt/agentscope/config.py
    mkdir -p ${D}/opt/agentscope/site-packages
    tar -xzf ${WORKDIR}/agentscope-aarch64-site.tar.gz -C ${D}/opt/agentscope/site-packages --strip-components=1
}

FILES:${PN} = "/opt/agentscope"
RDEPENDS:${PN} = "python3 python3-modules python3-asyncio rkllm-server"
INSANE_SKIP:${PN} += "already-stripped file-rdeps"
