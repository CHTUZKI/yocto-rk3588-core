# Rockchip vendor kernel (develop-6.1) with RKNPU for RKLLM / RKNN.
# RT builds use MACHINE=hd-rk3588-core-rt (see linux-rockchip_6.1.bb).
# Kept in meta-rk3588-custom; meta-rockchip still provides machine/U-Boot/rkbin.

SUMMARY = "Rockchip Linux kernel (official develop-6.1)"
SECTION = "kernel"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://COPYING;md5=6bc538ed5bd9a7fc9398086aedcd7e46"

inherit kernel

COMPATIBLE_MACHINE = "^hd-rk3588-core"

LINUX_VERSION = "6.1.141"
PV = "${LINUX_VERSION}+git${SRCPV}"
LINUX_VERSION_EXTENSION ?= "-rockchip"

SRC_URI = " \
    git://github.com/rockchip-linux/kernel.git;protocol=https;branch=develop-6.1 \
    file://hd-rk3588-core.dts \
    file://mali-valhall.cfg \
    file://rockchip_rt.config \
    file://disable-accel.cfg \
    file://hd-rk3588-core-rt-overlay.dtsi \
    file://0001-stmmac-resume-PHY-before-DMA-soft-reset.patch \
    file://0002-dwmac-rk-enable-clk-mac-and-default-rgmii-1g.patch \
    file://0003-dw-hdmi-rockchip-drive-enable-gpio-high-at-probe.patch \
    file://0004-arm64-select-ARCH_SUPPORTS_RT.patch \
"

RK3588_KERNEL_RT ?= "${@bb.utils.contains('MACHINEOVERRIDES', 'rt', '1', '0', d)}"

# develop-6.1 tip as of plan implementation (reproducible pin)
SRCREV = "b4ef083dc0c3608e744deabb43dc6b781aadbe6e"

S = "${WORKDIR}/git"

# Vendor arm64 defconfig (includes RKNPU, VOP, USB3, etc.)
# Plain `inherit kernel` does not honor KBUILD_DEFCONFIG (that is kernel-yocto);
# copy it to WORKDIR/defconfig before kernel_do_configure.
KBUILD_DEFCONFIG = "rockchip_linux_defconfig"

# Machine also sets KERNEL_CLASSES = kernel-fitimage / KERNEL_IMAGETYPE = fitImage
KERNEL_IMAGETYPE ?= "Image"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

do_configure:prepend() {
	if [ -f "${S}/arch/${ARCH}/configs/${KBUILD_DEFCONFIG}" ]; then
		cp -f "${S}/arch/${ARCH}/configs/${KBUILD_DEFCONFIG}" "${WORKDIR}/defconfig"
	else
		bbfatal "KBUILD_DEFCONFIG ${KBUILD_DEFCONFIG} not found under ${S}/arch/${ARCH}/configs/"
	fi

	if [ "${RK3588_KERNEL_RT}" = "1" ]; then
		install -d "${B}"
		cp -f "${WORKDIR}/defconfig" "${B}/.config"
		oe_runmake -C "${S}" O="${B}" ARCH="${ARCH}" scripts
		"${S}/scripts/kconfig/merge_config.sh" -m -O "${B}" \
			"${B}/.config" \
			"${WORKDIR}/rockchip_rt.config" \
			"${WORKDIR}/disable-accel.cfg"
		cp -f "${B}/.config" "${WORKDIR}/defconfig"
		rm -f "${B}/.config"
	else
		# Plain inherit kernel does not auto-merge .cfg fragments; append Valhall GPU.
		if [ -f "${WORKDIR}/mali-valhall.cfg" ]; then
			cat "${WORKDIR}/mali-valhall.cfg" >> "${WORKDIR}/defconfig"
		fi
	fi
}

do_configure:append() {
	install -d "${S}/arch/arm64/boot/dts/rockchip"
	cp -f "${WORKDIR}/hd-rk3588-core.dts" \
		"${S}/arch/arm64/boot/dts/rockchip/hd-rk3588-core.dts"

	if [ "${RK3588_KERNEL_RT}" = "1" ] && [ -f "${WORKDIR}/hd-rk3588-core-rt-overlay.dtsi" ]; then
		cat "${WORKDIR}/hd-rk3588-core-rt-overlay.dtsi" >> \
			"${S}/arch/arm64/boot/dts/rockchip/hd-rk3588-core.dts"
	fi

	makefile="${S}/arch/arm64/boot/dts/rockchip/Makefile"
	if [ -f "${makefile}" ] && ! grep -q 'hd-rk3588-core\.dtb' "${makefile}"; then
		sed -i '/rk3588-evb4-lp4-v10-linux\.dtb/a\\tdtb-$(CONFIG_ARCH_ROCKCHIP) += hd-rk3588-core.dtb' \
			"${makefile}"
	fi
}

# Vendor tree is large; avoid sparse QA noise on modules packaging
INSANE_SKIP:kernel-vmlinux += "buildpaths"
