SUMMARY = "systemd-timesyncd NTP config for HD-RK3588-CORE (China NTP servers)"
DESCRIPTION = "Board has no RTC battery; time resets on power cycle. \
systemd-timesyncd default uses Google NTP which is unreachable from China. \
This drop-in configures Aliyun / Tencent / cn.pool.ntp.org so time syncs \
on first boot, fixing SSL certificate validation for HTTPS."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://china-ntp.conf"

S = "${WORKDIR}"

do_install() {
	install -d ${D}${sysconfdir}/systemd/timesyncd.conf.d
	install -m 0644 ${WORKDIR}/china-ntp.conf \
		${D}${sysconfdir}/systemd/timesyncd.conf.d/china-ntp.conf
}

FILES:${PN} = "${sysconfdir}/systemd/timesyncd.conf.d/china-ntp.conf"
RDEPENDS:${PN} = "systemd"
