SUMMARY = "AgentScope 2 board-side Qwen3 agent"
DESCRIPTION = "AgentScope Agent with safe board file, Python and command tools"
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

python do_check_vendor() {
    path = os.path.join(d.getVar("TOPDIR"), "..", "deploy", "vendor",
                        "agentscope-aarch64-site.tar.gz")
    if not os.path.isfile(path):
        bb.fatal("agentscope-board: missing %s" % path)
}
addtask check_vendor before do_fetch
do_check_vendor[nostamp] = "1"

do_install() {
    install -d ${D}/opt/agentscope
    install -m 0755 ${WORKDIR}/main.py ${D}/opt/agentscope/main.py
    install -m 0644 ${WORKDIR}/board_tools.py ${D}/opt/agentscope/board_tools.py
    install -m 0644 ${WORKDIR}/config.py ${D}/opt/agentscope/config.py

    if [ -d ${WORKDIR}/agentscope-site ]; then
        mkdir -p ${D}/opt/agentscope/site-packages
        cp -a --no-preserve=ownership ${WORKDIR}/agentscope-site/. ${D}/opt/agentscope/site-packages/
        rm -rf ${D}/opt/agentscope/site-packages/bin
    else
        bbfatal "agentscope-site directory missing after unpack"
    fi
}

FILES:${PN} = "/opt/agentscope"
RDEPENDS:${PN} = "python3 python3-modules python3-asyncio rkllm-server"
INSANE_SKIP:${PN} += "already-stripped file-rdeps"
