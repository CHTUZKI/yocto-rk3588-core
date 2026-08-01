SUMMARY = "USB drive auto-mount service"
DESCRIPTION = "Mounts the first USB drive partition to /mnt/usb at boot. \
Supports exFAT, vfat, ext4, ntfs. Safe to run repeatedly."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://usb-automount.sh \
    file://usb-automount.service \
"

S = "${WORKDIR}"

do_install() {
    install -d ${D}${sbindir}
    install -m 0755 ${WORKDIR}/usb-automount.sh \
        ${D}${sbindir}/usb-automount.sh

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/usb-automount.service \
        ${D}${systemd_system_unitdir}/usb-automount.service
}

FILES:${PN} = " \
    ${sbindir}/usb-automount.sh \
    ${systemd_system_unitdir}/usb-automount.service \
"

inherit systemd

SYSTEMD_SERVICE:${PN} = "usb-automount.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

RDEPENDS:${PN} = "exfatprogs dosfstools"
