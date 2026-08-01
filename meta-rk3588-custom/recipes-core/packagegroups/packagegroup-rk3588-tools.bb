SUMMARY = "Useful bring-up tools for HD-RK3588-CORE"
DESCRIPTION = "modetest, network utilities, and a few CLI helpers"

inherit packagegroup

RDEPENDS:${PN} = " \
    libdrm-tests \
    htop \
    neofetch \
    ripgrep \
    iperf3 \
    ethtool \
    tcpdump \
    python3 \
    python3-modules \
    python3-pip \
    python3-flask \
    exfatprogs \
    dosfstools \
"
