#!/bin/sh
# Manual helper: grow ext4 rootfs to fill GPT partition.
# Usage (on board, as root):
#   hd-rk3588-rootfs-expand.sh
#
# Not enabled at boot. Safe to re-run: marker / give-up / already-full
# checks avoid needless resize2fs (eMMC wear).
#
set -eu

FLAG=/etc/hd-rk3588-rootfs-expanded
GIVEUP=/etc/hd-rk3588-rootfs-expand.give-up
FAILCNT=/etc/hd-rk3588-rootfs-expand.failcnt
PARTLABEL_LINK=/dev/disk/by-partlabel/rootfsA
# Do not call resize2fs for tiny leftover (alignment); avoids needless metadata writes.
MIN_EXPAND_BYTES=$((16 * 1024 * 1024))
MAX_FAILS=3

log() {
	echo "hd-rk3588-rootfs-expand: $*"
}

mark_done() {
	touch "$FLAG"
	rm -f "$FAILCNT" "$GIVEUP" 2>/dev/null || true
	sync
}

mark_giveup() {
	log "giving up after repeated failures (protect eMMC); see $GIVEUP"
	echo "$*" > "$GIVEUP"
	sync
}

bump_fail() {
	n=0
	if [ -f "$FAILCNT" ]; then
		n=$(cat "$FAILCNT" 2>/dev/null || echo 0)
	fi
	n=$((n + 1))
	echo "$n" > "$FAILCNT"
	sync
	log "fail count=$n/$MAX_FAILS"
	if [ "$n" -ge "$MAX_FAILS" ]; then
		mark_giveup "resize failed $n times: $*"
		exit 0
	fi
}

if [ -f "$FLAG" ]; then
	log "marker exists, skip (no eMMC resize)"
	exit 0
fi

if [ -f "$GIVEUP" ]; then
	log "give-up marker exists, skip (no eMMC resize)"
	exit 0
fi

resolve_root_dev() {
	if [ -e "$PARTLABEL_LINK" ]; then
		readlink -f "$PARTLABEL_LINK"
		return 0
	fi
	majmin=$(awk '$5 == "/" { print $3; exit }' /proc/self/mountinfo 2>/dev/null || true)
	if [ -n "${majmin:-}" ] && [ -e "/sys/dev/block/$majmin" ]; then
		base=$(basename "$(readlink -f "/sys/dev/block/$majmin")")
		if [ -b "/dev/$base" ]; then
			echo "/dev/$base"
			return 0
		fi
	fi
	if [ -b /dev/mmcblk0p3 ]; then
		echo /dev/mmcblk0p3
		return 0
	fi
	return 1
}

wait_resolve_dev() {
	i=0
	while [ "$i" -lt 60 ]; do
		if dev=$(resolve_root_dev); then
			echo "$dev"
			return 0
		fi
		i=$((i + 1))
		sleep 0.5
	done
	return 1
}

part_bytes() {
	dev=$1
	if command -v blockdev >/dev/null 2>&1; then
		blockdev --getsize64 "$dev" && return 0
	fi
	base=$(basename "$dev")
	sectors=$(cat "/sys/class/block/$base/size" 2>/dev/null || echo 0)
	echo $((sectors * 512))
}

fs_bytes() {
	dev=$1
	fb=$(df -P -B1 / 2>/dev/null | awk 'NR==2 { print $2; exit }' || true)
	if [ -n "${fb:-}" ] && [ "$fb" -gt 0 ] 2>/dev/null; then
		echo "$fb"
		return 0
	fi
	fb=$(df -k / 2>/dev/null | awk 'NR==2 { print $2 * 1024; exit }' || true)
	if [ -n "${fb:-}" ] && [ "$fb" -gt 0 ] 2>/dev/null; then
		echo "$fb"
		return 0
	fi
	out=$(/usr/sbin/dumpe2fs -h "$dev" 2>/dev/null || true)
	blocks=$(printf '%s\n' "$out" | awk -F: '/^Block count/ { gsub(/^[ \t]+|[ \t]+$/,"",$2); print $2; exit }')
	bsize=$(printf '%s\n' "$out" | awk -F: '/^Block size/ { gsub(/^[ \t]+|[ \t]+$/,"",$2); print $2; exit }')
	if [ -n "${blocks:-}" ] && [ -n "${bsize:-}" ]; then
		echo $((blocks * bsize))
		return 0
	fi
	echo 0
}

DEV=$(wait_resolve_dev) || {
	log "ERROR: cannot resolve root partition device"
	bump_fail "resolve device"
	exit 1
}
log "root device: $DEV"

PB=$(part_bytes "$DEV")
FB=$(fs_bytes "$DEV")
log "partition=$PB bytes, filesystem=$FB bytes"

if [ "$PB" -le 0 ]; then
	log "ERROR: bad partition size"
	bump_fail "bad partition size"
	exit 1
fi

if [ "$FB" -gt 0 ]; then
	# df excludes reserved blocks (~5%); ≥92% of partition ⇒ treat as full.
	if [ $((FB * 100)) -ge $((PB * 92)) ]; then
		log "already filled (df=$FB ≥ 92% of part=$PB), mark done — no resize2fs"
		mark_done
		exit 0
	fi
	slack=$((PB - FB))
	if [ "$slack" -lt "$MIN_EXPAND_BYTES" ]; then
		log "already filled (slack=${slack}B < ${MIN_EXPAND_BYTES}B), mark done — no resize2fs"
		mark_done
		exit 0
	fi
	log "need expand: slack=${slack}B"
else
	log "filesystem size unknown; will try resize2fs once (no-op if already max)"
fi

log "running resize2fs $DEV (one-shot grow)"
if /usr/sbin/resize2fs "$DEV"; then
	mark_done
	log "done"
	exit 0
fi

log "resize2fs failed"
bump_fail "resize2fs"
exit 1
