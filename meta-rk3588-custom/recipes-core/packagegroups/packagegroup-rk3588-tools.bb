SUMMARY = "Useful bring-up tools for HD-RK3588-CORE"
DESCRIPTION = "Full-featured Linux command set: system inspection, network \
diagnostics, file/archive tools, editors, terminal multiplexers, and Python runtime."

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
    usb-automount \
    \
    util-linux \
    util-linux-lsblk \
    util-linux-findmnt \
    util-linux-fstrim \
    procps \
    lsof \
    findutils \
    \
    jq \
    file \
    strace \
    tree \
    \
    rsync \
    socat \
    nmap \
    \
    vim \
    nano \
    tmux \
    screen \
    \
    xz \
    zip \
    \
    cronie \
    ca-certificates \
    \
    usbutils \
    pciutils \
    \
    parted \
    smartmontools \
    hdparm \
    i2c-tools \
"
