# DEG2 on OCuLink instead of USB4 — cutover runbook

Target: MS-S1 Max (Strix Halo) → Minisforum DEG2 → Radeon AI PRO R9700 (gfx1201),
moved from the USB4/Thunderbolt tunnel to the DEG2's native PCIe mode.

## Why

In USB4 mode the GPU hangs off a **virtual** PCIe root port created by the USB4 NHI.
Three symptoms in `notes/hardware/r9700-egpu-report.md` §6 trace to that:

- `PCIE atomic ops is not supported` — atomics not routed through the tunnel
- `BAR 4 [io size 0x0100]: can't assign; no space` — crippled window on the virtual port
- no `retrain_link` on any hop — firmware-owned virtual bridge

Native PCIe fixes all three classes at once, and PCIe **hot-reset works through native
bridges**, which is what makes VFIO passthrough viable later. In USB4 mode reset does not
propagate, so the card is effectively one-assignment-per-boot.

## Bandwidth: OCuLink x4 is NOT an upgrade — judge init, not throughput

| Path | Raw per direction |
| --- | --- |
| USB4 v2 tunnel as measured (link 32 GT/s ×16 inside the tunnel) | ~9.5 GB/s, tunnel-limited |
| OCuLink, PCIe 4.0 **×4 electrically** | ~7.9 GB/s (~7 GB/s effective) |

So OCuLink is roughly equal, possibly marginally lower. That is fine, because the R9700
has 32 GB of its own GDDR6 at ~640 GB/s and decode is VRAM-bandwidth-bound, not
host-link-bound. The link only matters for model load and initial weight transfer
(≈4.5 s for 32 GB at 7 GB/s).

**Critical:** seeing `x4` after the switch is the **expected ceiling**, not a fault. In
USB4 mode `x4` was the bug. Do not chase it with `pci=` flags this time.

## Constraints

OCuLink is **not hot-pluggable** — unlike USB4, forcing it takes the link down or worse.
Both systems powered off **and unplugged** before touching the cable.
Minisforum does not officially support eGPU/dGPU, so expect to poke BIOS for the slot.

## Steps

1. Power off both machines, unplug.
2. DEG2 output switch (near the 24-pin) → **OCuLink / PCIe**.
3. DEG2 PSU switch to **full power** — not the position that throttled cold boot.
4. Fit the card + its PCIe power, seat the OCuLink cable at both ends.
5. **Check BIOS primary display = iGPU/onboard** before first boot, or a black console is
   possible when amdgpu posts a second GPU. Set this while still on USB4 if unsure.
6. Power dock first, wait for fans to settle, then power the host.

## What carries over

Still required: the `dcn_4_0_1_dmcub` firmware fix (ASIC, not transport) — see
[`../r9700-egpu-report.md`](../r9700-egpu-report.md) §6 item 9, and
[`stage/install-egpu-fixes.sh`](stage/install-egpu-fixes.sh).

Inert but harmless on OCuLink: `softdep amdgpu pre: thunderbolt`, `boltctl` enrollment,
the USB4 rear-port quirks. Remove only once it is working.

## Verify

```bash
BDF=$(lspci -d 1002:7551 | cut -d' ' -f1); echo "BDF=$BDF"
lspci -vvv -s "$BDF" | grep -E "LnkSta:|Kernel driver"
journalctl -k -b --no-pager | grep "$BDF" | grep -viE "VM flush|DMCUB error|PSR" | tail -30
ls -l /dev/dri/by-path/
```

Success = `DMUB hardware initialized`, **no** `failed to load ucode DMCUB`, **no**
`MES(1) failed to respond to msg=SET_HW_RSRC`, and a second render node under
`/dev/dri/by-path/`. Then `rocminfo` should list a third GPU and the cockpit can take
`--device /dev/kfd --device /dev/dri`.
