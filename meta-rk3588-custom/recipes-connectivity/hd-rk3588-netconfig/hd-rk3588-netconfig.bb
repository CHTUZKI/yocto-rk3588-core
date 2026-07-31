SUMMARY = "Static Ethernet IP 192.168.1.14 for HD-RK3588-CORE"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://20-wired.network \
    file://90-hd-rk3588-net.preset \
"

inherit allarch

do_install() {
	install -d ${D}${systemd_unitdir}/network
	install -m 0644 ${WORKDIR}/20-wired.network ${D}${systemd_unitdir}/network/20-wired.network

	install -d ${D}${systemd_unitdir}/system-preset
	install -m 0644 ${WORKDIR}/90-hd-rk3588-net.preset \
		${D}${systemd_unitdir}/system-preset/90-hd-rk3588-net.preset
}

FILES:${PN} = " \
	${systemd_unitdir}/network/20-wired.network \
	${systemd_unitdir}/system-preset/90-hd-rk3588-net.preset \
"
RDEPENDS:${PN} = "systemd"
