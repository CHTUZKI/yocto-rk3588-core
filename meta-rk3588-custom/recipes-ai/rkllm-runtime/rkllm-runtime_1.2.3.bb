SUMMARY = "Rockchip RKLLM runtime (prebuilt aarch64)"
DESCRIPTION = "librkllmrt + llm_demo and bundled libstdc++/libgcc/libgomp for RKLLM 1.2.3"
HOMEPAGE = "https://github.com/airockchip/rknn-llm"
LICENSE = "CLOSED"

COMPATIBLE_HOST = "aarch64.*-linux"

# Prebuilt binaries live next to the build tree (not in git).
FILESEXTRAPATHS:prepend := "${TOPDIR}/../deploy/rkllm:"

SRC_URI = " \
    file://librkllmrt.so \
    file://llm_demo \
    file://rkllm.h \
    file://libstdc++.so.6 \
    file://libgcc_s.so.1 \
    file://libgomp.so.1 \
"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

python do_check_deploy() {
    deploy = os.path.join(d.getVar("TOPDIR"), "..", "deploy", "rkllm")
    missing = []
    for f in ("librkllmrt.so", "llm_demo", "rkllm.h", "libstdc++.so.6", "libgcc_s.so.1", "libgomp.so.1"):
        path = os.path.join(deploy, f)
        if not os.path.isfile(path):
            missing.append(path)
    if missing:
        bb.fatal("rkllm-runtime: missing deploy files:\n  " + "\n  ".join(missing))
}
addtask check_deploy before do_fetch
do_check_deploy[nostamp] = "1"

do_install() {
	install -d ${D}/opt/rkllm
	install -m 0755 ${WORKDIR}/librkllmrt.so ${D}/opt/rkllm/librkllmrt.so
	install -m 0755 ${WORKDIR}/llm_demo ${D}/opt/rkllm/llm_demo
	install -m 0644 ${WORKDIR}/rkllm.h ${D}/opt/rkllm/rkllm.h
	install -m 0644 ${WORKDIR}/libstdc++.so.6 ${D}/opt/rkllm/libstdc++.so.6
	install -m 0644 ${WORKDIR}/libgcc_s.so.1 ${D}/opt/rkllm/libgcc_s.so.1
	install -m 0644 ${WORKDIR}/libgomp.so.1 ${D}/opt/rkllm/libgomp.so.1
}

FILES:${PN} = "/opt/rkllm/*"
# Bundled copies of libstdc++/libgcc/libgomp — do not register as system shlib providers.
PRIVATE_LIBS:${PN} = "libstdc++.so.6 libgcc_s.so.1 libgomp.so.1 librkllmrt.so"
INSANE_SKIP:${PN} += "already-stripped ldflags libdir file-rdeps dev-so"
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_SYSROOT_STRIP = "1"
