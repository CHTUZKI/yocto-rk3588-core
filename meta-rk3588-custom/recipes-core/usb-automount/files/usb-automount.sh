#!/bin/sh
# usb-automount.sh — auto-mount USB drives on boot and on hotplug.
#
# Scans /dev/sd* partitions, mounts the first usable one to /mnt/usb.
# Supports exFAT, vfat, ext4, ntfs (if drivers present).
# Safe to run repeatedly: skips already-mounted devices.

set -eu

MOUNT_POINT="/mnt/usb"
WAIT_TIMEOUT=30  # seconds to wait for USB device to appear at boot

log() {
    echo "usb-automount: $*" | tee -a /tmp/usb-automount.log
}

is_mounted() {
    mount | grep -q " ${MOUNT_POINT} "
}

# If already mounted, exit cleanly
if is_mounted; then
    log "already mounted, skipping"
    exit 0
fi

# Wait for USB block device to appear (at boot USB may take a few seconds)
for i in $(seq 1 "$WAIT_TIMEOUT"); do
    if ls /dev/sd?* 2>/dev/null | grep -q .; then
        break
    fi
    sleep 1
done

# Find first usable partition
PART=""
for dev in /dev/sda1 /dev/sda2 /dev/sdb1 /dev/sdb2 /dev/sdc1 /dev/sdc2; do
    [ -b "$dev" ] || continue
    PART="$dev"
    break
done

# Fall back to whole device (no partition table)
if [ -z "$PART" ]; then
    for dev in /dev/sda /dev/sdb /dev/sdc; do
        [ -b "$dev" ] || continue
        PART="$dev"
        break
    done
fi

if [ -z "$PART" ]; then
    log "no USB block device found"
    exit 1
fi

log "found device: $PART"

# Create mount point
mkdir -p "$MOUNT_POINT"

# Detect filesystem and mount
# Try common filesystems; first one that works wins.
for fs in exfat vfat ext4 ext3 ext2 ntfs-3g; do
    # Check if kernel supports this fs
    grep -q "\b${fs}\b" /proc/filesystems 2>/dev/null || continue

    if mount -t "$fs" -o rw,iocharset=utf8,errors=remount-ro \
         "$PART" "$MOUNT_POINT" 2>/dev/null; then
        log "mounted $PART as $fs at $MOUNT_POINT"
        exit 0
    fi
done

# Last resort: let mount auto-detect
if mount -o rw,errors=remount-ro "$PART" "$MOUNT_POINT" 2>/dev/null; then
    log "mounted $PART (auto-detect) at $MOUNT_POINT"
    exit 0
fi

log "failed to mount $PART"
exit 1
