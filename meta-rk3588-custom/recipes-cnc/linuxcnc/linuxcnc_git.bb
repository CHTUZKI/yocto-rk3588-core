SUMMARY = "LinuxCNC motion controller with Axis GUI"
DESCRIPTION = "LinuxCNC uspace build for PREEMPT_RT + SOEM EtherCAT on RK3588."
HOMEPAGE = "https://linuxcnc.org/"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/GPL-2.0-only;md5=801f80980d171dd6425610833a22dbe6"

SRC_URI = "git://github.com/linuxcnc/linuxcnc.git;protocol=https;branch=master \
           file://skip-tkinter-check-when-cross.patch \
"
SRCREV = "ab930078a55e06a8c591fe25ade20f729be22d34"

S = "${WORKDIR}/git/src"
B = "${WORKDIR}/build"

PV = "2.9.10+git${SRCPV}"

inherit autotools pkgconfig python3native

DEPENDS = " \
    autoconf-native automake-native libtool-native intltool-native \
    tcl-native tk-native \
    tcl tk \
    gtk+3 glib-2.0 libmodbus libusb1 libgpiod \
    boost fmt \
    libxmu libxinerama libxext libxi libxrandr libxrender libxscrnsaver \
    mesa libglu \
    readline libedit \
    python3 python3-numpy-native python3-pybind11 \
    yapps2-native \
    libtirpc \
    bison-native flex-native \
"

RDEPENDS:${PN} = " \
    tcl tk bwidget \
    bash \
    python3 python3-numpy python3-tkinter python3-pyopengl python3-pygobject \
    gtk+3 \
    mesa-demos \
    procps psmisc util-linux \
    coreutils \
    udev \
    ${@bb.utils.contains('DISTRO_FEATURES', 'systemd', 'systemd', '', d)} \
"

# configure 会探测目标机运行时工具路径；Yocto 构建时 PATH 不含 ps/kill 等，需显式缓存。
CACHED_CONFIGUREVARS += " \
    ac_cv_path_GREP=${bindir}/grep \
    ac_cv_path_AWK=${bindir}/awk \
    ac_cv_path_PS=${bindir}/ps \
    ac_cv_path_KILL=${bindir}/kill \
    ac_cv_path_WHOAMI=${bindir}/whoami \
    ac_cv_path_PIDOF=${base_sbindir}/pidof \
    ac_cv_path_IPCS=${bindir}/ipcs \
    ac_cv_path_FUSER=${bindir}/fuser \
"

EXTRA_OECONF = " \
    --with-realtime=uspace \
    --disable-build-documentation \
    --disable-manpages \
    --disable-check-runtime-deps \
    --with-tclConfig=${STAGING_LIBDIR}/tclConfig.sh \
    --with-tkConfig=${STAGING_LIBDIR}/tkConfig.sh \
"

export PYTHON = "${STAGING_BINDIR_NATIVE}/python3-native/python3"

do_configure:prepend() {
	cd ${S}
	./autogen.sh
	export PATH="${STAGING_BINDIR_NATIVE}:${PATH}"
}

do_configure() {
	cd ${S}
	${CACHED_CONFIGUREVARS} ./configure ${CONFIGUREOPTS} ${EXTRA_OECONF}
}

# tclConfig.sh / tkConfig.sh 给出 -I/usr/include/...，Yocto 交叉编译器不会将其映射到 sysroot
do_configure:append() {
	sed -i \
		-e "s|-I/usr/include/tcl8.6|-I${STAGING_INCDIR}/tcl8.6|g" \
		-e "s|-I/usr/include |-I${STAGING_INCDIR} |g" \
		-e "s|-L/usr/lib|-L${STAGING_LIBDIR}|g" \
		-e "s|${STAGING_DIR_NATIVE}/usr/lib -lpython3|${STAGING_LIBDIR} -lpython3|g" \
		-e "s|${STAGING_DIR_NATIVE}/usr/include/python3|${STAGING_INCDIR}/python3|g" \
		-e 's/$(Q)ld -d -r/$(Q)$(CC) -r/' \
		${S}/Makefile.inc
	sed -i \
		-e 's/$(Q)ld -d -r/$(Q)$(CC) -r/' \
		${S}/Makefile
}

do_compile() {
	oe_runmake -C ${S} -O build-software
}

do_install() {
	oe_runmake -C ${S} DESTDIR=${D} install-software
}

do_install:append() {
	# install 脚本可能保留构建机 python3-native / hosttools 路径
	for f in $(grep -rl 'python3-native/python3' ${D} 2>/dev/null || true); do
		sed -i '1s|.*|#!/usr/bin/env python3|' "$f"
	done
	for f in $(grep -rl 'hosttools' ${D}${bindir} ${D}${libdir}/linuxcnc 2>/dev/null || true); do
		sed -i -E 's|[^"= ]*hosttools/grep|/usr/bin/grep|g' "$f"
		sed -i -E 's|[^"= ]*hosttools/awk|/usr/bin/awk|g' "$f"
	done
	# Poky: python 模块在 dist-packages；pidof 在 /usr/bin
	if [ -f ${D}${bindir}/linuxcnc ]; then
		sed -i \
			-e 's|PYTHONPATH=$LINUXCNC_HOME/lib/python|PYTHONPATH=$LINUXCNC_HOME/lib/python3/dist-packages:$LINUXCNC_HOME/lib/python|g' \
			-e 's|PIDOF="/usr/sbin/pidof|PIDOF="/usr/bin/pidof|g' \
			-e 's|TCLLIBPATH=$LINUXCNC_HOME/lib/tcltk|TCLLIBPATH="/usr/lib/tcl8.6/bwidget $LINUXCNC_HOME/lib/tcltk"|g' \
			-e 's|TCLLIBPATH="$LINUXCNC_HOME/lib/tcltk $TCLLIBPATH"|TCLLIBPATH="/usr/lib/tcl8.6/bwidget $LINUXCNC_HOME/lib/tcltk $TCLLIBPATH"|g' \
			${D}${bindir}/linuxcnc
	fi
}

FILES:${PN} += " \
    ${datadir}/linuxcnc \
    ${sysconfdir}/linuxcnc \
    ${libdir}/linuxcnc \
    ${libdir}/python3/dist-packages \
    ${libdir}/tcltk/linuxcnc \
    ${datadir}/axis \
    ${datadir}/glade \
    ${datadir}/gmoccapy \
    ${datadir}/gscreen \
    ${datadir}/gtksourceview-4/language-specs \
    ${datadir}/qtvcp \
"

# 仅把 halcompile 导出到 sysroot，供 soem-linuxcnc-hal 交叉构建使用
linuxcnc_sysroot_preprocess() {
	install -d ${SYSROOT_DESTDIR}${bindir}
	install -m 0755 ${D}${bindir}/halcompile ${SYSROOT_DESTDIR}${bindir}/halcompile
	# 缩短 shebang，避免 QA shebang-size；构建机用 python3-native 执行
	sed -i '1s|.*|#!/usr/bin/env python3|' ${SYSROOT_DESTDIR}${bindir}/halcompile
}
SYSROOT_PREPROCESS_FUNCS += "linuxcnc_sysroot_preprocess"

INSANE_SKIP:${PN} += "already-stripped rpaths dev-so dev-elf shebang-size ldflags file-rdeps"
