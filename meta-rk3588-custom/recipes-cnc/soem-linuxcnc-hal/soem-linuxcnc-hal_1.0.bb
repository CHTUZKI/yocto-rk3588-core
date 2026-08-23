SUMMARY = "LinuxCNC HAL component using SOEM EtherCAT master"
DESCRIPTION = "Userspace HAL bridge between LinuxCNC and SOEM (raw socket EtherCAT)."
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/GPL-2.0-only;md5=801f80980d171dd6425610833a22dbe6"

SRC_URI = "file://soem_linuxcnc.c \
           file://soem_linuxcnc.h \
           file://soem_linuxcnc.comp \
"

S = "${WORKDIR}"
B = "${WORKDIR}/build"

DEPENDS = "linuxcnc soem virtual/libc yapps2-native python3-native"

inherit pkgconfig python3native

do_configure[noexec] = "1"

do_compile() {
	mkdir -p ${B}
	${CC} ${CFLAGS} ${LDFLAGS} -fPIC -shared \
		-I${STAGING_INCDIR}/soem \
		-o ${B}/libsoem_linuxcnc.so ${S}/soem_linuxcnc.c \
		-L${STAGING_LIBDIR} -lsoem -lpthread -lrt

	cp -f ${B}/libsoem_linuxcnc.so ${S}/

	export PATH="${STAGING_BINDIR_NATIVE}:${STAGING_BINDIR}:${PATH}"
	cd ${S}
	# 只生成 C 源，避免 halcompile 内部 Makefile 使用错误的 host 路径
	python3 ${STAGING_BINDIR}/halcompile --preprocess -o ${B}/soem_linuxcnc.c soem_linuxcnc.comp

	${CC} ${CFLAGS} ${LDFLAGS} \
		-I${S} -I${STAGING_INCDIR} -I${STAGING_INCDIR}/soem -I${STAGING_INCDIR}/linuxcnc \
		-URTAPI -U__MODULE__ -DULAPI \
		-o ${B}/soem_linuxcnc ${B}/soem_linuxcnc.c \
		-L${B} -L${STAGING_LIBDIR} -lsoem_linuxcnc -lsoem -llinuxcnchal -lpthread -lrt
}

do_install() {
	install -d ${D}${libdir}
	install -m 0755 ${B}/libsoem_linuxcnc.so ${D}${libdir}/

	install -d ${D}${bindir}
	install -m 4755 ${B}/soem_linuxcnc ${D}${bindir}/soem_linuxcnc
}

FILES:${PN} = "${bindir}/soem_linuxcnc ${libdir}/libsoem_linuxcnc.so"
FILES:${PN}-dev = ""

RDEPENDS:${PN} = "linuxcnc soem"

INSANE_SKIP:${PN} += "dev-elf file-rdeps"
