# V100 / eGPU Upgrade Decision — Strix Halo (Minisforum MS-S1 Max)

**Date:** 2026-11-07 · **Host:** Minisforum MS-S1 Max, Ryzen AI Max+ 395, 128 GB unified · **Status: scratch decision doc — not repo content, do not commit**

> Scope note: the R9700 in `docs/R9700_LLAMA.md` belongs to the multi-maintainer
> repo's hardware, not this box. No spare Radeon card is on hand. This report is a
> personal hardware purchase decision, independent of the project.

---

## 0. The goal and the constraints (from the brief)

| Item | Decision |
| --- | --- |
| **Primary goal** | Faster **tokens/s on models that already fit in 128 GB** (bandwidth play, not capacity) |
| **Attach** | External only — OCuLink / USB4 / Thunderbolt, **or** a separate mini-ITX box networked back |
| **Budget** | $1,200–2,500 (GPU + carrier + PSU + cooling + interconnect) |
| **Risk** | Pinned versions acceptable **if documented** (driver 580.x / CUDA 12.9) |
| **Environment** | Garage/rack — noise OK, watercooling possible, **power/outlet limits matter** |

---

## 1. Physics that drives every conclusion

**Memory bandwidth ≈ decode tokens/s.** Approx, 13B Q4 (≈8 GB), decode-bound:

| Device | VRAM | Bandwidth | Approx t/s (13B Q4) | Notes |
| --- | --- | ---: | ---: | --- |
| Strix Halo 395 (baseline) | 128 GB unified | ~200–230 GB/s real | ~28 | what you own |
| Radeon RX 9700 XT | 16 GB GDDR6 | ~640 GB/s (approx) | ~75–85 | RDNA4 |
| RTX 5060 Ti 16 GB | 16 GB GDDR7 | 448 GB/s (128-bit) | ~55–70 | consumer, current stack |
| **Tesla V100 PCIe 32 GB** | 32 GB HBM2 | **900 GB/s** | **~110–130** | ECC reserve ≈ 2 GB |
| Tesla V100 SXM2 32 GB | 32 GB HBM2 | 1130 GB/s | ~140–150 | needs carrier + NVHS clock |

**Three rules that dominate everything:**

1. **Layer split (llama.cpp) = one card active per token.** Two cards = 2× *capacity*, **1× speed.** Two V100s or two 5060 Ti still decode at single-card speed. The only way two cards beat one on speed is tensor-parallel **with working P2P**, which needs NVLink (SXM2) — GeForce has no PCIe P2P at all.
2. **NVLink on V100 is SXM2-only.** The Amazon HP listing's "NVLink → 96 GB @ 300 GB/s" text is **false for the PCIe card** (no bridge connector). Buying two PCIe V100s does *not* give unified memory.
3. **External attach is NOT the bottleneck.** OCuLink ≈ USB4 ≈ ~6.5 GB/s usable; per-token traffic is a few KB. Decode is identical internal vs external. Choose the wire for **reliability**, not throughput. Load (~30 GB) is the only slow part (~24 s over 10GbE, ~5 s over x4).

**MS-S1 Max hard limits (verified):** internal slot is physical x16 but **electrical PCIe 4.0 x4**; two M.2 = x4 + x1; **320 W PSU behind a 160 W APU = no internal dGPU headroom.** External was always forced.

---

## 2. The five options, scored

Scored against the stated goal (decode speed / fit) and your risk profile.

### Option 1 — Frankenstein: 2× 32 GB V100 (PCIe or SXM2) on a DIY jig
- **Speed goal:** PCIe pair → 900 GB/s (one-card speed, +capacity). SXM2 pair **+ NVLink** → the only config that truly exceeds one card, via tensor parallel.
- **Today's prices:** HP V100 32 GB passive (renewed) **$899.90 ea**; YBaoTong SXM2→PCIe bracket **$98.88** + Noctua fan ~$17.
- **Fatal caveats:** passive card needs ducted high-static-pressure airflow (or water); V100 power is **CPU/EPS 8-pin, not PCIe 6+2**; 2-slot; 250 W each. SXM2 NVLink is **only proven on unbranded "One Cat"-style Taobao carriers** — the open pinout kit is not a board, and no one has published working NVLink bandwidth from a DIY build. Two V100s bought to get "64 GB unified" is a **myth** (see Rule 2).
- **Verdict: NOT for this goal.** At 1–2 cards, NVLink pays nothing and the SXM2 carrier is the highest-cost, least-proven hardware in the whole search. The frankenstein jig is a capacity or 4-card-serving project, which you ruled out.

### Option 2 — Commercial consumer card in a commercial eGPU (OCuLink / USB4 / TB)
- **Best-in-class config:** **1× V100 32 GB is the cheapest 900 GB/s** you can attach. But a *headless* Tesla in an external box is the riskiest integration: many sub-$100 OCuLink docks are **slot-power-only (75 W)** and give no EPS connector → can't feed 250 W.
- **Attach reality (strixhalo.wiki):** **NVIDIA external GPUs: "no problems reported."** So a consumer NVIDIA card in a Sonnet 750ex ($399.99) / REEEK OCuLink ($99.99) works today; a **headless Tesla over USB4/Thunderbolt is an unsupported tail — expect enumeration trouble.** If you external-attach a V100, use bare **OCuLink** and a dock that supplies EPS/PCIe power — nothing sub-$100 slot-powered.
- **Verdict: YES, but only as a *single* consumer card or a V100 in a proper powered OCuLink dock.** This is where Option 3 wins for turnkey (see below).

### Option 3 — 2× prebuilt Gigabyte 16 GB eGPU (today)
- **What it is:** AORUS RTX 5060 Ti AI Box (16 GB GDDR7, Thunderbolt) **$899.99 ea**, "50+ bought/mo." Alternative: AORUS RTX 3080 Ti Gaming Box (watercooled, TB3) **$1,552.99** (12 GB but ~912 GB/s, sm_86, FlashAttention).
- **Why it beats DIY eGPU:** the sealed AI Box is priced like a *bare* 5060 Ti — the enclosure + PSU + TB cable are effectively free. Consumer GPU **with display output is the supported configuration** on Strix Halo (NVIDIA external = no reported issues). Zero enumeration risk, current drivers, "today."
- **Ceiling:** still 448 GB/s per card; two of them = capacity, not speed (Rule 1). 16 GB each.
- **Verdict: YES as the zero-project answer.** This is the safest "works today" purchase; you pay ~$1,800 for two, or ~$900 for one, and accept the 448 GB/s speed cap. It is *slower than one V100* but has no integration risk and no pinned stack.

### Option 4 — Make an R9700 (Radeon RX 9700 XT) an eGPU for the Strix Halo
- **Blocker A (verified, strixhalo.wiki):** AMD external GPUs on Strix Halo appear **throttled to the APU's BIOS power limit** — an external Radeon can be capped near the APU budget regardless of the card's real TDP. That guts a ~240 W RX 9700's advantage. Multiple GMKtec/Frame reports; NVIDIA explicitly has no such issue.
- **Blocker B:** you don't own a spare card — it's the repo's 4-card ROCm platform (`R9700_LLAMA.md`: 4× R9700 on Threadripper, 64 GB, internal). Pulling one into an eGPU is a research detour with a known power-limit bug.
- **Verdict: NO.** Documented AMD-external power-limit bug on this exact host + no spare card + you'd be re-deriving what the repo already runs internally. Skip.

### Option 5 — My recommendation
See §3.

---

## 3. Recommendation

**The enclosure is the risk, not the card.** Everything that makes a V100 painful headless (EPS power, no-display enumeration, passive-cooling ducting, 500 W on one circuit) **disappears inside a cheap used PC** — and your dual 10GbE makes it a remote backend, not a platform change.

**Primary — "the V100 done right": used mini-ITX GPU PC + 10GbE back to the MS-S1.**
```
used office mini-ITX (ryzen/intel, PCIe x16, 450W+ PSU)   ~$200–350
1× Tesla V100 32GB PCIe (HP renewed)                       $899.90
blower/fan shroud for the passive card                      ~$25
10GbE DAC/SFP+ (ports already on both boxes)                ~$30
                                                          ─────────
total                                                       ~$1,150–1,300
```
- 900 GB/s decode, 32 GB, EPS power + enumeration solved by the PC itself, quiet enough for a garage, ~350 W total.
- Runs a **server-side `llama-server`**; the 395 is an HTTP client over 10GbE (fits your cockpit's "backend stores host/port" pattern better than per-layer RPC).
- **Pin this box:** driver 580.x · CUDA ≤12.9 · last CUDA-12 PyTorch · `TORCH_CUDA_ARCH_LIST=7.0`. No FlashAttention on sm_70 → long-context prefill is the one weakness.

**If you refuse a second box:** **AORUS RTX 5060 Ti AI Box** (Option 3), Thunderbolt, today, ~$899. Accept 448 GB/s. This is the correct fallback when turnkey matters more than the last tokens/s.

**Do not** buy the SXM2 frankenstein (Option 1) or the R9700 eGPU (Option 4) for this goal.

### Options 1 & 3 are a coin-flip on one axis
If your usage is **decode on fitting models** and you'll maintain a frozen image → V100 (faster, more GB). If it's **long-context / RAG / "just works"** → the current-stack 5060 AI Box earns its 2× decode deficit via FlashAttention + FP8 + rolling drivers.

---

## 4. Verify before buying (the checks that actually bite)

1. **V100 power edge:** confirm **EPS vs PCIe** 8-pin on the exact AIB; buy a **rated** adapter; enclosure/dock must expose that connector (not slot-power-only).
2. **Passive card cooling:** insist on return window; run 1 h load watching `nvidia-smi -q -d TEMPERATURE,POWER,ECC`; replace 8-year-old thermal pads (HBM2 gets hot).
3. **Don't buy two PCIe V100s for "unified memory"** — no NVLink on PCIe.
4. **SXM2 NVLink:** only consider if a seller shows `nvidia-smi nvlink -s` + a bandwidth test. No such public proof exists for DIY carriers.
5. **OCuLink mod:** use an **M2OC-3-class** M.2→OCuLink adapter (the wiki's recommended part) for stable Gen4 x4; ASPM off (`pcie_aspm=off`), Above-4G decoding on, `pcie=noaer` if AER resets.
6. **Prefill check:** benchmark *your* prompt lengths (llama.cpp `--prompt-np` or the bench in `scripts/`) — if prefill dominates, the Volta no-FlashAttention cliff decides the whole purchase toward the 5060.

## 5. Bottom line
Fastest-per-dollar for your stated goal is **one V100 32 GB** — but its only smart external form is **inside a ~$250 used PC on your existing 10GbE**, which erases every eGPU-integration risk. If you want zero projects today, the **AORUS 5060 Ti AI Box** is the honest answer at the known 448 GB/s cap. Skip SXM2-NVLink and the R9700 eGPU.
