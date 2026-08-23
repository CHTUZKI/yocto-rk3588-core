SUMMARY = "Default LinuxCNC/SOEM configuration for RK3588 CNC image"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://99-linuxcnc-rt.conf \
    file://soem.env \
    file://soem-skeleton.hal \
"

inherit allarch

do_install() {
	install -d ${D}${sysconfdir}/security/limits.d
	install -m 0644 ${WORKDIR}/99-linuxcnc-rt.conf \
		${D}${sysconfdir}/security/limits.d/99-linuxcnc-rt.conf

	install -d ${D}${sysconfdir}/rk3588-cnc
	install -m 0644 ${WORKDIR}/soem.env ${D}${sysconfdir}/rk3588-cnc/soem.env
	install -m 0644 ${WORKDIR}/soem-skeleton.hal ${D}${sysconfdir}/rk3588-cnc/soem-skeleton.hal
}

FILES:${PN} = " \
	${sysconfdir}/security/limits.d/99-linuxcnc-rt.conf \
	${sysconfdir}/rk3588-cnc/soem.env \
	${sysconfdir}/rk3588-cnc/soem-skeleton.hal \
"
