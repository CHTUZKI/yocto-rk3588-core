SUMMARY = "Real-time test and bring-up tools for HD-RK3588-CORE RT image"
DESCRIPTION = "cyclictest, stress-ng, and network utilities (no GPU modetest)"

inherit packagegroup

RDEPENDS:${PN} = " \
    rt-tests \
    stress-ng \
    htop \
    neofetch \
    ripgrep \
    iperf3 \
    ethtool \
    tcpdump \
"
