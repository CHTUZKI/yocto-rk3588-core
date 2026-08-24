SUMMARY = "Default LinuxCNC/SOEM configuration for RK3588 CNC image"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://99-linuxcnc-rt.conf \
    file://soem.env \
    file://soem-skeleton.hal \
    file://xfwm4.xml \
    file://linuxcnc-env.sh \
    file://20-rockchip-modesetting.conf \
    file://linuxcnc.desktop \
"

inherit allarch

do_install() {
	install -d ${D}${sysconfdir}/security/limits.d
	install -m 0644 ${WORKDIR}/99-linuxcnc-rt.conf \
		${D}${sysconfdir}/security/limits.d/99-linuxcnc-rt.conf

	install -d ${D}${sysconfdir}/rk3588-cnc
	install -m 0644 ${WORKDIR}/soem.env ${D}${sysconfdir}/rk3588-cnc/soem.env
	install -m 0644 ${WORKDIR}/soem-skeleton.hal ${D}${sysconfdir}/rk3588-cnc/soem-skeleton.hal

	install -d ${D}${sysconfdir}/profile.d
	install -m 0644 ${WORKDIR}/linuxcnc-env.sh ${D}${sysconfdir}/profile.d/linuxcnc-env.sh

	install -d ${D}${sysconfdir}/xdg/xfce4/xfconf/xfce-perchannel-xml
	install -m 0644 ${WORKDIR}/xfwm4.xml \
		${D}${sysconfdir}/xdg/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml

	install -d ${D}${datadir}/X11/xorg.conf.d
	install -m 0644 ${WORKDIR}/20-rockchip-modesetting.conf \
		${D}${datadir}/X11/xorg.conf.d/20-rockchip-modesetting.conf

	# 覆盖 linuxcnc 自带的 .desktop（root 登录需 RTAPI_UID≠0 等 env）
	install -d ${D}${datadir}/applications
	install -m 0644 ${WORKDIR}/linuxcnc.desktop \
		${D}${datadir}/applications/linuxcnc.desktop
}

FILES:${PN} = " \
	${sysconfdir}/security/limits.d/99-linuxcnc-rt.conf \
	${sysconfdir}/rk3588-cnc/soem.env \
	${sysconfdir}/rk3588-cnc/soem-skeleton.hal \
	${sysconfdir}/profile.d/linuxcnc-env.sh \
	${sysconfdir}/xdg/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml \
	${datadir}/X11/xorg.conf.d/20-rockchip-modesetting.conf \
	${datadir}/applications/linuxcnc.desktop \
"
