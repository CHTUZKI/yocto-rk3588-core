SUMMARY = "Minimal image for HD-RK3588-CORE"
DESCRIPTION = "Minimal Linux image for Vanxak HD-RK3588-CORE with update.img output"

inherit core-image
inherit rk3588-image
inherit rockchip-updateimg

IMAGE_INSTALL = " \
    packagegroup-core-boot \
    kernel-modules \
    openssh \
    openssh-sftp-server \
    hd-rk3588-netconfig \
    iproute2 \
    ${CORE_IMAGE_EXTRA_INSTALL} \
"

IMAGE_FEATURES += " \
    debug-tweaks \
    ssh-server-openssh \
"

IMAGE_FSTYPES += "ext4"

# Vendor-like update.img layout + board MiniLoader (DDR @ 115200).
# Cold boot: MiniLoader IDB → u-boot.itb @ 0x4000 → rootfsA (fitImage).
# Console baud is 115200 (confirmed with 参考文件/update.img).
VENDOR_IMG_DIR = "${TOPDIR}/../参考文件/ImageUbuntu_RK3588-B2B"

RK_UPDATEIMG_SOC = "auto"
RK_UPDATEIMG_FLASH_IDBLOCK = "0"
RK_UPDATEIMG_PARAMETER_MODE = "manual"
RK_UPDATEIMG_PARAMETER_CMDLINE = "mtdparts=:0x00002000@0x00004000(uboot),0x00000800@0x00006000(misc),0x00060000@0x00006800(rootfsA)"
RK_UPDATEIMG_ROOTDEV = "PARTLABEL=rootfsA"
RK_UPDATEIMG_ROOTFS_TYPE = "ext4"
RK_UPDATEIMG_EXTRA_DEPENDS += "rockchip-rkbin:do_deploy"
RK_UPDATEIMG_LOADER_CANDIDATES = "${VENDOR_IMG_DIR}/MiniLoaderAll.bin loader.bin MiniLoaderAll.bin"
RK_UPDATEIMG_UBOOT_CANDIDATES = "u-boot.itb uboot.img u-boot.img"
RK_UPDATEIMG_REQUIRED_IMAGES = "loader.bin uboot.img misc.img rootfs.img"
RK_UPDATEIMG_OPTIONAL_IMAGES = "trust.img idblock.img boot.img"
RK_UPDATEIMG_PARTITION_IMAGE_MAP = "\
uboot:uboot.img \
misc:misc.img \
rootfsA:rootfs.img \
rootfs:rootfs.img \
root:rootfs.img \
"
