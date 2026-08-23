SUMMARY = "Simple Open EtherCAT Master (SOEM)"
DESCRIPTION = "SOEM is an open source EtherCAT master library for user-space raw sockets."
HOMEPAGE = "https://github.com/OpenEtherCATsociety/SOEM"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://LICENSE;md5=9e0f3a6879e76ac16053729f3b05a2d4"

SRC_URI = "git://github.com/OpenEtherCATsociety/SOEM.git;protocol=https;nobranch=1"
SRCREV = "abbf0d42e38d6cfbaa4c1e9e8e07ace651c386fd"

S = "${WORKDIR}/git"

do_configure:prepend() {
	sed -i 's/-Werror/-Wno-error/g' ${S}/CMakeLists.txt
}

inherit cmake

EXTRA_OECMAKE = "-DBUILD_TESTS=FALSE -DCMAKE_POSITION_INDEPENDENT_CODE=ON"

BBCLASSEXTEND = "native nativesdk"
