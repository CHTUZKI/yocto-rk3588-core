SUMMARY = "Expand rootfs ext4 to fill rootfsA partition on first boot"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://hd-rk3588-rootfs-expand.service"

inherit systemd

SYSTEMD_SERVICE:${PN} = "hd-rk3588-rootfs-expand.service"

do_install() {
	install -d ${D}${systemd_system_unitdir}
	install -m 0644 ${WORKDIR}/hd-rk3588-rootfs-expand.service \
		${D}${systemd_system_unitdir}/hd-rk3588-rootfs-expand.service
}

FILES:${PN} = "${systemd_system_unitdir}/hd-rk3588-rootfs-expand.service"
RDEPENDS:${PN} = "e2fsprogs-resize2fs"
