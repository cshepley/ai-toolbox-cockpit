#!/usr/bin/env bash
# Undo notes/hardware/proxmox/stage/install-egpu-fixes.sh
#   sudo ./rollback-egpu-fixes.sh
set -euo pipefail
FW=/usr/lib/firmware/amdgpu
BLOB="$FW/dcn_4_0_1_dmcub.bin.zst"
GRUB=/etc/default/grub
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

if [ -f "$BLOB.backup" ]; then
  rm -f "$BLOB" && cp -a "$BLOB.backup" "$BLOB"
  echo "restored original $BLOB"
elif [ -f "$BLOB.orig-symlink" ]; then
  rm -f "$BLOB" && ln -s "$(cat "$BLOB.orig-symlink")" "$BLOB"
  echo "restored original symlink: $BLOB -> $(readlink "$BLOB")"
else
  echo "WARNING: no backup or orig-symlink found for $BLOB, left as-is"
fi
rm -f /boot/grub/grub.cfg.bak-egpu
[ -f "$GRUB.bak-egpu" ] && cp -a "$GRUB.bak-egpu" "$GRUB" && echo "restored GRUB"
rm -f /etc/modprobe.d/amd-egpu.conf /etc/udev/rules.d/99-amd-egpu-pm.rules
echo "removed modprobe + udev rules"
command -v update-grub >/dev/null && update-grub
update-initramfs -u -k "$(uname -r)"
echo "DONE. Reboot to return to the previous state."
