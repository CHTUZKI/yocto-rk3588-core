SUMMARY = "Qwen2.5-Coder-3B Instruct RKLLM model for RK3588 (w8a8_g128)"
DESCRIPTION = "Qwen2.5-Coder-3B-Instruct w8a8_g128 rkllm artifact for coding-focused \
on-board inference. Aligned with RKLLM runtime 1.2.x. Not installed into update.img \
(keep rootfs.img <4GiB); SCP to /opt/models/ after flash."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

COMPATIBLE_HOST = "aarch64.*-linux"

FILESEXTRAPATHS:prepend := "${TOPDIR}/../deploy/models:"

SRC_URI = "file://Qwen2.5-Coder-3B-Instruct-w8a8-rk3588.rkllm;name=model"

# Filled after download; do_check_model also validates size.
SRC_URI[model.sha256sum] = "a3075cf80325f59b2bc89178b7f085a840201aaac3bab25c79857dc8d5b41565"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

python do_check_model() {
    path = os.path.join(d.getVar("TOPDIR"), "..", "deploy", "models",
                        "Qwen2.5-Coder-3B-Instruct-w8a8-rk3588.rkllm")
    if not os.path.isfile(path):
        bb.fatal("qwen25-coder-3b-rkllm: model missing at %s\n"
                 "Place the ~4G .rkllm under deploy/models/ before building." % path)
    size = os.path.getsize(path)
    if size < 3000000000:
        bb.fatal("qwen25-coder-3b-rkllm: model looks incomplete (%d bytes) at %s" % (size, path))
}
addtask check_model before do_fetch
do_check_model[nostamp] = "1"

do_install() {
	install -d ${D}/opt/models
	install -m 0644 ${WORKDIR}/Qwen2.5-Coder-3B-Instruct-w8a8-rk3588.rkllm \
		${D}/opt/models/Qwen2.5-Coder-3B-Instruct-w8a8-rk3588.rkllm
}

FILES:${PN} = "/opt/models/Qwen2.5-Coder-3B-Instruct-w8a8-rk3588.rkllm"
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_SYSROOT_STRIP = "1"
INSANE_SKIP:${PN} += "already-stripped"
