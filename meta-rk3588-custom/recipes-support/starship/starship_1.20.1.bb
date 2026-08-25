SUMMARY = "The minimal, blazing-fast, and infinitely customizable prompt for any shell"
DESCRIPTION = "Starship is the minimal, blazing fast, and highly customizable prompt \
for any shell! Shows relevant information at a glance, works on any shell, \
and is highly configurable."
HOMEPAGE = "https://starship.rs"
LICENSE = "ISC"
LIC_FILES_CHKSUM = "file://LICENSE;md5=a25cce5cb436456c4b21461a3ff95b0d"

SRC_URI = "git://github.com/starship/starship.git;protocol=https;nobranch=1;tag=v${PV} \
    file://starship.toml \
    file://starship.sh \
"

S = "${WORKDIR}/git"

CARGO_SRC_DIR = ""

inherit cargo cargo-update-recipe-crates

require ${BPN}-crates.inc

# Disable default features (battery, notify, gix-max-perf) to avoid
# extra native deps like cmake/zlib-ng and unnecessary functionality on a CNC board
CARGO_BUILD_FLAGS = "-v --frozen --target ${RUST_HOST_SYS} --release --manifest-path=${S}/Cargo.toml --no-default-features"

do_configure:prepend() {
    # Disable strip and LTO to speed up cross-build
    sed -i 's/strip\ =\ true/strip\ =\ false/g' ${S}/Cargo.toml
    sed -i 's/lto\ =\ true/lto\ =\ false/g' ${S}/Cargo.toml
    sed -i 's/codegen-units\ =\ 1/codegen-units\ =\ 16/g' ${S}/Cargo.toml
}

do_install:append() {
    # Default starship config
    install -d ${D}${sysconfdir}
    install -m 0644 ${WORKDIR}/starship.toml ${D}${sysconfdir}/starship.toml

    # bash integration script sourced by /etc/profile.d
    install -d ${D}${sysconfdir}/profile.d
    install -m 0644 ${WORKDIR}/starship.sh ${D}${sysconfdir}/profile.d/starship.sh
}

FILES:${PN} += "${sysconfdir}/starship.toml ${sysconfdir}/profile.d/starship.sh"

RDEPENDS:${PN} += "bash"
