# V100 / eGPU — raw analysis transcript

> **Fork-only research note.** Unedited AI research transcript that fed
> [v100-egpu-decision.md](./v100-egpu-decision.md). Kept for provenance; the
> decision doc is the summary to read. Never part of upstream.

---

Before I write this up, five things actually change the recommendation — especially now that "external" is settled, since external changes the attach path more than the card choice.

Analyzing your answers...

Your answers settled it. Recording the durable findings, then the wrap-up.

Created memory file

## Two findings that restructure your plan

**1. Attach is a non-decision — which is good news.** Your MS-S1 Max's full-length slot is *physically* x16 but **electrically PCIe 4.0 x4** (ServeTheHome and NAS Compares both flag this). OCuLink x4 ≈ USB4 ≈ 6–7 GB/s usable. So your OCuLink-vs-USB4 question doesn't matter for bandwidth, and neither does internal-vs-external. Pick whichever enclosure is well-built. Since you already have **dual 10GbE**, network-attach at ~1.25 GB/s is also viable — and I'd use 10GbE, not USB4 networking, which is still fragile on Linux.

**2. Your MS-S1 can't host these internally anyway.** 320W built-in PSU against a 160W APU leaves no headroom for a 250W card. External was forced regardless. Good that you'd already decided.

## The bandwidth trap — read this before buying anything

Your goal is *faster tokens/s on models that already fit in 128 GB*. This is the one goal V100 genuinely nails, but the intuition "two cards = double speed" is **wrong**, and it's what makes the NVLink thread a red herring:

| Split mode | Cards active per token | Decode bandwidth | Needs NVLink? |
|---|---|---|---|
| llama.cpp **layer split** | Sequential — one at a time | `model_bytes / BW_of_one_card` | No — gain ≈ 0 |
| vLLM **tensor parallel** | Simultaneous | Sums, minus allreduce | Effectively yes |

With layer split across 2× V100, total time per token is `(½model/BW) + (½model/BW) = model/BW` — **identical to one card**. You get 2× capacity, 1× speed.

So, decisively:

- Model fits in **one** V100 32 GB → **one card** is the fastest *and* cheapest config.
- Model needs 2+ cards → layer split buys capacity at unchanged speed; only NVLink-backed tensor parallel recovers speed, and that's the SXM2 carrier rabbit hole.

**Which is why the SXM2/NVLink carriers you asked about are the wrong spend for your stated goal.** I did verify them: the open [`LiuXinyu12378/SXM2_to_PCIE_adapter`](https://github.com/LiuXinyu12378/SXM2_to_PCIE_adapter) is explicitly *"no NVLink, plug-and-play"*, and the open [`pigeon-labs-stack/v100-sxm2-reference`](https://github.com/pigeon-labs-stack/v100-sxm2-reference) is a pinout kit, not a board (you'd need your own 156.25 MHz NVHS clock and presence-detect loop). NVLink is only *proven* on unbranded Taobao "One Cat AI"-style carriers — the Level1Techs backplane author got GPUs up over PCIe but never demonstrated NVLink bandwidth. Highest cost, least proven, and it pays off at 4+ cards on tensor-parallel serving. Not your use case.

## Tiers by memory / price

Verified anchor: **2× V100 PCIe 32 GB has stabilized at $630–720 each** on the secondary market. V100 has *not* cratered like DDR4 — HBM2 competes with HBM3e for the same wafers, so these hold value. 16 GB figures below are estimates.

| Tier | Config | Usable weights | Real decode vs your 395 | Cost all-in | Verdict |
|---|---|---|---|---|---|
| **A** | 1× V100 PCIe **32 GB** | ~28 GB | **~4×** (~110–135 t/s on 13B Q4) | **$750–950** | ✅ Matches your goal exactly |
| **B** | 1× V100 PCIe 16 GB | ~13 GB | ~4×, capacity-limited | $300–450 | Cheapest speed proof-of-concept |
| **C** | 2× V100 PCIe 32 GB, layer split | ~60 GB | **same as one card** | $1,400–1,750 | Capacity you said you don't need |
| **D** | 2× SXM2 + NVLink carrier, vLLM TP | ~60 GB | ~5–7× if TP works | $1,900–2,800 | Unproven hardware, blows budget |

Rough sizing: $/usable-GB is best at Tier A (~$30/GB) and worst at Tier D (~$40/GB plus risk). **Tier A is the answer, and it sits at the *bottom* of your $1,200–2,500 range.**

## Recommended build

```
1× Tesla V100 PCIe 32GB blower        ~$650–720
used mini-ITX board + CPU + RAM        ~$120–180
PSU (450–550W, plenty)                 ~$60
OCuLink/USB4 dual enclosure or riser   ~$90–150
10GbE DAC/SFP+ (you have the ports)     ~$30
NVHS: not needed — PCIe card, no SXM2   $0
─────────────────────────────────────────────
total                                  ~$950–1,250
```

Skip water cooling. You said noise is fine in the garage, and there are no good off-the-shelf blocks for Tesla PCBs — V100's HBM needs active airflow too, so a waterblock-only swap tends to cook the memory. The author of that open adapter repo independently reports custom turbine mods holding **<75 °C** where other SXM2 turbine mods hit an 82 °C wall, which tells you blower-style airflow is the mature path. Power: one card keeps the whole box near **~350 W**, easy on a 15 A/120 V circuit even with the MS-S1 running. That respects your outlet constraint; Tier C at ~800 W would start to crowd it.

Use the ~$1,200 you save on a second card later *only if* you actually hit the 28 GB ceiling — and then know you're buying capacity, not speed.

## Software pinning (you accepted documented pinning)

This is the part that bites, and it's the real cost of Volta in 2026:

| Constraint | Pin to | Why |
|---|---|---|
| NVIDIA driver | **580.x** | Last branch with feature support for Maxwell/Pascal/Volta; 590+ drops them |
| CUDA toolkit | **≤ 12.9** | CUDA 13.0 removed offline compilation + libraries for sm_70 |
| PyTorch | last **CUDA 12.x** build | [`pytorch#190385`](https://github.com/pytorch/pytorch/issues/190385) marks the cutoff |
| Kernel arch | `TORCH_CUDA_ARCH_LIST=7.0` | `sm_70` |

Treat that host as a **frozen platform**, not a rolling one. Realistic maintainability horizon is ~2027–28, after which driver 580.x stops surviving new kernels even with security-only updates. Fit for a dedicated garage box; a poor fit for anything you want to keep upgrading.

This maps cleanly onto how your project already handles per-platform quirks — same shape as `docs/R9700_LLAMA.md` / `docs/INTEL_B70.md`. If you do this, the driver/CUDA pin belongs in a `docs/V100_VOLTA.md` platform doc plus an `sm_70`-flagged image variant, not smeared across backends. I haven't touched the repo — say the word and I'll draft that doc and a catalogue/profile skeleton once you've confirmed the exact PyTorch build against a real card, per your AGENTS.md rule about validating runtime behavior remotely rather than on the dev machine.

**Bottom line:** buy one V100 PCIe 32 GB, attach it over OCuLink, keep the 395's 128 GB pool intact, skip NVLink entirely, and bank ~$1,000.Skip water cooling. You said noise is fine in the garage, and there are no good off-the-shelf blocks for Tesla PCBs — V100's HBM needs active airflow too, so a waterblock-only swap tends to cook the memory. The author of that open adapter repo independently reports custom turbine mods holding **<75 °C** where other SXM2 turbine mods hit an 82 °C wall, which tells you blower-style airflow is the mature path. Power: one card keeps the whole box near **~350 W**, easy on a 15 A/120 V circuit even with the MS-S1 running. That respects your outlet constraint; Tier C at ~800 W would start to crowd it.

Use the ~$1,200 you save on a second card later *only if* you actually hit the 28 GB ceiling — and then know you're buying capacity, not speed.

## Software pinning (you accepted documented pinning)

This is the part that bites, and it's the real cost of Volta in 2026:

| Constraint | Pin to | Why |
|---|---|---|
| NVIDIA driver | **580.x** | Last branch with feature support for Maxwell/Pascal/Volta; 590+ drops them |
| CUDA toolkit | **≤ 12.9** | CUDA 13.0 removed offline compilation + libraries for sm_70 |
| PyTorch | last **CUDA 12.x** build | [`pytorch#190385`](https://github.com/pytorch/pytorch/issues/190385) marks the cutoff |
| Kernel arch | `TORCH_CUDA_ARCH_LIST=7.0` | `sm_70` |

Treat that host as a **frozen platform**, not a rolling one. Realistic maintainability horizon is ~2027–28, after which driver 580.x stops surviving new kernels even with security-only updates. Fit for a dedicated garage box; a poor fit for anything you want to keep upgrading.

This maps cleanly onto how your project already handles per-platform quirks — same shape as `docs/R9700_LLAMA.md` / `docs/INTEL_B70.md`. If you do this, the driver/CUDA pin belongs in a `docs/V100_VOLTA.md` platform doc plus an `sm_70`-flagged image variant, not smeared across backends. I haven't touched the repo — say the word and I'll draft that doc and a catalogue/profile skeleton once you've confirmed the exact PyTorch build against a real card, per your AGENTS.md rule about validating runtime behavior remotely rather than on the dev machine.

**Bottom line:** buy one V100 PCIe 32 GB, attach it over OCuLink, keep the 395's 128 GB pool intact, skip NVLink entirely, and bank ~$1,000.