# Personal hardware research

Purchase and performance research for **my** machines. This is deliberately kept
out of [`../../docs/`](../../docs), which documents the cockpit for all
maintainers and describes hardware the project owns (e.g. the 4-card ROCm
Threadripper behind [`../../docs/R9700_LLAMA.md`](../../docs/R9700_LLAMA.md))
rather than my own box.

**My box:** Minisforum MS-S1 Max — Ryzen AI Max+ 395 (Strix Halo), 128 GB unified
LPDDR5x, dual 10GbE, 320 W built-in PSU, full-length slot wired as PCIe 4.0 x4.

## Files

| File | Read it when |
| --- | --- |
| [`v100-egpu-decision.md`](v100-egpu-decision.md) | You want the **condensed** V100 / eGPU buy/no-buy answer and the physics behind it. Start here. |
| [`r9700-egpu-report.md`](r9700-egpu-report.md) | You need the **full** R9700 + Strix Halo report: benchmarks, street prices, attach options, caveats. ~100 KB, sections §0–§9h. |
| [`r9700-egpu-plan.md`](r9700-egpu-plan.md) | You want the research plan that produced the report above. |
| [`v100-raw-analysis.md`](v100-raw-analysis.md) | You want the unedited transcript the decision doc was distilled from. Provenance only. |
| [`proxmox/`](proxmox/README.md) | Setting up or restoring the Proxmox host and its Ubuntu VMs. |

## Conclusions worth keeping at hand

Written 2026-11-06 → 2026-11-07; the R9700 has since been bought, so the
"should I buy" framing is historical.

- **Decode speed ≈ memory bandwidth.** Strix Halo real-world ~200–230 GB/s is the
  ceiling being attacked; V100 PCIe 32 GB is 900 GB/s, R9700 ~640 GB/s.
- **llama.cpp layer split is one card active per token**, so 2 cards = 2× capacity
  at **1× speed**. Only tensor parallel with working P2P beats that, and on Volta
  that means NVLink, which means SXM2.
- **V100 PCIe has no working NVLink bridge.** Listings claiming "96 GB unified"
  over PCIe are wrong. NVLink is SXM2-only.
- **External attach is not the bottleneck** — OCuLink x4 ≈ USB4 ≈ 6–7 GB/s usable,
  and per-token traffic is KB-scale. Choose the wire for reliability. AMD eGPU on
  Strix Halo is throttled to the APU's BIOS power budget; NVIDIA eGPU is reported
  problem-free.
- **The MS-S1 Max cannot host a 250 W card internally** (320 W PSU vs a 160 W APU),
  so external or a separate networked box was always forced. Use the existing
  10GbE rather than USB4 networking.
- **Volta is a frozen platform:** driver 580.x and CUDA ≤ 12.9 are the last
  feature-supporting branches; `TORCH_CUDA_ARCH_LIST=7.0`. Horizon ~2027–28. If a
  Volta host is ever added to the cockpit, its pin belongs in a platform doc like
  a `docs/V100_VOLTA.md` plus an `sm_70` image variant — not smeared across backends.
