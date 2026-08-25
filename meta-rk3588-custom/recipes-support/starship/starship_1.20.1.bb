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

    # bash integration for login shells (/etc/profile.d)
    install -d ${D}${sysconfdir}/profile.d
    install -m 0644 ${WORKDIR}/starship.sh ${D}${sysconfdir}/profile.d/starship.sh

    # bash integration for non-login shells (/etc/bash.bashrc.d)
    # SSH non-login shells source /etc/bash.bashrc which in turn sources /etc/bash.bashrc.d/*.sh
    install -d ${D}${sysconfdir}/bash.bashrc.d
    install -m 0644 ${WORKDIR}/starship.sh ${D}${sysconfdir}/bash.bashrc.d/starship.sh

    # Ensure /etc/bash.bashrc sources bash.bashrc.d/*.sh
    if ! grep -q 'bash.bashrc.d' ${D}${sysconfdir}/bash.bashrc 2>/dev/null; then
        cat >> ${D}${sysconfdir}/bash.bashrc <<'BASHRC'

# Source /etc/bash.bashrc.d/*.sh for global non-login shell config (e.g. starship)
if [ -d /etc/bash.bashrc.d ]; then
    for f in /etc/bash.bashrc.d/*.sh; do
        [ -r "$f" ] && . "$f"
    done
fi
BASHRC
    fi
}

FILES:${PN} += " \
    ${sysconfdir}/starship.toml \
    ${sysconfdir}/profile.d/starship.sh \
    ${sysconfdir}/bash.bashrc.d/starship.sh \
    ${sysconfdir}/bash.bashrc \
"

RDEPENDS:${PN} += "bash"
