#!/usr/bin/env bash
# Install the R9700/gfx1201 eGPU bring-up fixes on Ubuntu 24.04.5.
#   sudo ./install-egpu-fixes.sh /path/to/upstream/dcn_4_0_1_dmcub.bin.zst
# Safe to re-run. See rollback-egpu-fixes.sh to undo.
set -euo pipefail

BLOB_SRC="${1:?usage: $0 <path-to-dcn_4_0_1_dmcub.bin.zst>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FW=/usr/lib/firmware/amdgpu
BLOB="$FW/dcn_4_0_1_dmcub.bin.zst"
GRUB=/etc/default/grub

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
[ -f "$BLOB_SRC" ] || { echo "no such blob: $BLOB_SRC"; exit 1; }

echo "== 1. firmware: replace the dcn_4_0_1_dmcub symlink =="
# Record the original state BEFORE touching it. On Ubuntu this is a symlink, so
# a later `cp -a` of it after `rm` would back up nothing at all.
if [ -L "$BLOB" ]; then
  echo "   current: symlink -> $(readlink "$BLOB")  (this is the bug)"
  [ -f "$BLOB.orig-symlink" ] || readlink "$BLOB" > "$BLOB.orig-symlink"
  rm -f "$BLOB"
elif [ ! -f "$BLOB.backup" ] && [ ! -f "$BLOB.orig-symlink" ]; then
  cp -a "$BLOB" "$BLOB.backup"
  echo "   backed up the existing real file as $BLOB.backup"
fi
cp -a "$BLOB_SRC" "$BLOB"
chmod 644 "$BLOB"
zstd -t "$BLOB" >/dev/null
echo "   installed real blob: $(stat -c%s "$BLOB") bytes, sha $(zstd -dc "$BLOB" | sha256sum | cut -c1-16)"

echo "== 2. modprobe options =="
install -m 644 "$HERE/amd-egpu.conf" /etc/modprobe.d/amd-egpu.conf
echo "   /etc/modprobe.d/amd-egpu.conf:"
sed -n 's/^/     /p' /etc/modprobe.d/amd-egpu.conf | grep -v '^ *#' || true

echo "== 3. udev: keep the eGPU out of runtime suspend =="
install -m 644 "$HERE/99-amd-egpu-pm.rules" /etc/udev/rules.d/99-amd-egpu-pm.rules
echo "   installed"

echo "== 4. GRUB kernel parameters =="
# Only pcie_aspm is added here: it is a core-kernel flag, not an amdgpu module
# option, so modprobe.d cannot carry it. All the amdgpu.* knobs live in
# /etc/modprobe.d/amd-egpu.conf, which initramfs-tools copies into the initramfs.
# Left alone on purpose: pci=realloc, pcie_port_pm=off, pcie_ports=native are
# already set from the earlier round and bus enumeration already succeeds.
want="pcie_aspm=off"
cp -a "$GRUB" "$GRUB.bak-egpu"
sed -i -E 's/ *pcie_aspm=off//g' "$GRUB"
sed -i -E "s|^(GRUB_CMDLINE_LINUX_DEFAULT=\".*)\"$|\1 ${want}\"|" "$GRUB"
grep -n GRUB_CMDLINE_LINUX_DEFAULT "$GRUB"
echo "   (previous GRUB saved as $GRUB.bak-egpu)"
# Editing /etc/default/grub does nothing on its own; grub.cfg must be regenerated.
if command -v update-grub >/dev/null 2>&1; then
  update-grub
else
  grub-mkconfig -o /boot/grub/grub.cfg
fi
grep -c "pcie_aspm=off" /boot/grub/grub.cfg >/dev/null && echo "   grub.cfg regenerated and contains pcie_aspm=off"

echo "== 5. rebuild initramfs =="
update-initramfs -u -k "$(uname -r)"

echo
echo "DONE. Power-cycle the DEG2, then reboot the host (dock first, then host)."
echo "Check afterwards with: journalctl -k -b | grep -E '97:00.0.*(DMCUB|DMUB|probe)'"
