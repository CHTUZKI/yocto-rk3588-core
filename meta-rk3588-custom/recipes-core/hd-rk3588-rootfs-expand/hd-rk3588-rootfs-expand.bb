SUMMARY = "Manual rootfs expand helper for HD-RK3588-CORE"
DESCRIPTION = "Installs /usr/sbin/hd-rk3588-rootfs-expand.sh for on-demand \
ext4 grow-to-partition. Not started at boot (avoids eMMC wear / first-boot races)."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://hd-rk3588-rootfs-expand.sh"

do_install() {
	install -d ${D}${sbindir}
	install -m 0755 ${WORKDIR}/hd-rk3588-rootfs-expand.sh \
		${D}${sbindir}/hd-rk3588-rootfs-expand.sh
}

FILES:${PN} = "${sbindir}/hd-rk3588-rootfs-expand.sh"
RDEPENDS:${PN} = "e2fsprogs-resize2fs e2fsprogs"
