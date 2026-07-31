SUMMARY = "Qwen3-4B Instruct RKLLM model for RK3588 (w8a8)"
DESCRIPTION = "Qwen3-4B-Instruct-2507 w8a8 rkllm artifact aligned with RKLLM runtime 1.2.3"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

COMPATIBLE_HOST = "aarch64.*-linux"

FILESEXTRAPATHS:prepend := "${TOPDIR}/../deploy/models:"

SRC_URI = "file://Qwen3-4B-Instruct-2507-w8a8-rk3588.rkllm;name=model"
SRC_URI[model.sha256sum] = "922e60a2f1b2989d6b486707b8b65fe6f923da097cffd388f09ddf63277efce7"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

python do_check_model() {
    path = os.path.join(d.getVar("TOPDIR"), "..", "deploy", "models",
                        "Qwen3-4B-Instruct-2507-w8a8-rk3588.rkllm")
    if not os.path.isfile(path):
        bb.fatal("qwen3-4b-rkllm: model missing at %s\n"
                 "Place the ~4.6G .rkllm under deploy/models/ before building." % path)
    size = os.path.getsize(path)
    if size < 4000000000:
        bb.fatal("qwen3-4b-rkllm: model looks incomplete (%d bytes) at %s" % (size, path))
}
addtask check_model before do_fetch
do_check_model[nostamp] = "1"

do_install() {
	install -d ${D}/opt/models
	install -m 0644 ${WORKDIR}/Qwen3-4B-Instruct-2507-w8a8-rk3588.rkllm \
		${D}/opt/models/Qwen3-4B-Instruct-2507-w8a8-rk3588.rkllm
}

FILES:${PN} = "/opt/models/Qwen3-4B-Instruct-2507-w8a8-rk3588.rkllm"
# Huge binary blob — skip strip / debug split.
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_SYSROOT_STRIP = "1"
INSANE_SKIP:${PN} += "already-stripped"
