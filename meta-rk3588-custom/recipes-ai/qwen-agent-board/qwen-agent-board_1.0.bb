SUMMARY = "On-board Qwen-Agent scripts and vendored Python deps"
DESCRIPTION = "qwen_agent_onboard + agent_session with aarch64 site-packages for local RKLLM"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

COMPATIBLE_HOST = "aarch64.*-linux"

FILESEXTRAPATHS:prepend := "${TOPDIR}/../deploy/vendor:"

SRC_URI = " \
    file://qwen_agent_onboard.py \
    file://agent_session.py \
    file://run.sh \
    file://qwen-agent-aarch64-site.tar.gz;name=site \
"

# Filled after scripts/fetch-qwen-agent-aarch64.sh; do_check_vendor fails if missing.
# Checksum is optional for local file:// — verified by presence + size in do_check_vendor.

do_configure[noexec] = "1"
do_compile[noexec] = "1"

python do_check_vendor() {
    path = os.path.join(d.getVar("TOPDIR"), "..", "deploy", "vendor",
                        "qwen-agent-aarch64-site.tar.gz")
    if not os.path.isfile(path):
        bb.fatal("qwen-agent-board: missing %s\n"
                 "Run: scripts/fetch-qwen-agent-aarch64.sh" % path)
    if os.path.getsize(path) < 1000000:
        bb.fatal("qwen-agent-board: vendor tarball looks too small: %s" % path)
}
addtask check_vendor before do_fetch
do_check_vendor[nostamp] = "1"

S = "${WORKDIR}"

do_install() {
	install -d ${D}/opt/qwen_agent
	install -m 0644 ${WORKDIR}/qwen_agent_onboard.py ${D}/opt/qwen_agent/qwen_agent_onboard.py
	install -m 0644 ${WORKDIR}/agent_session.py ${D}/opt/qwen_agent/agent_session.py
	install -m 0755 ${WORKDIR}/run.sh ${D}/opt/qwen_agent/run.sh

	# Tarball contains top-level dir qwen-agent-site/; avoid host uid via --no-preserve=ownership
	if [ -d ${WORKDIR}/qwen-agent-site ]; then
		mkdir -p ${D}/opt/qwen_agent/site-packages
		cp -a --no-preserve=ownership ${WORKDIR}/qwen-agent-site/. ${D}/opt/qwen_agent/site-packages/
		# Drop host pip "bin/" wrappers (not useful on target path layout)
		rm -rf ${D}/opt/qwen_agent/site-packages/bin
		# Drop static libs shipped inside numpy wheels (not needed at runtime)
		find ${D}/opt/qwen_agent/site-packages -type f -name '*.a' -delete
	else
		bbfatal "qwen-agent-site directory missing after unpack"
	fi
}

FILES:${PN} = "/opt/qwen_agent"
RDEPENDS:${PN} = " \
    python3 \
    python3-modules \
    python3-pip \
    rkllm-server \
"
INSANE_SKIP:${PN} += "already-stripped ldflags libdir file-rdeps staticdev"
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
