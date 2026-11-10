# Research Plan: R9700 32 GB eGPU + Strix Halo (Minisforum MS-S1 Max)

**Deliverable:** a single Markdown report + practical guide — [r9700-egpu-report.md](./r9700-egpu-report.md)
**Author context:** personal hardware project. Treat as a scratch note (precedent:
`v100-egpu-decision.md`), and note that the R9700 material
already in `docs/` describes the project's own multi-card machine, not this box.

---

## 1. What I own / what is coming

| Item | Details | Constraints it imposes |
| --- | --- | --- |
| **Host** | Minisforum MS-S1 Max, Ryzen AI Max+ 395, **128 GB unified**, stock | Internal M.2 slot is electrical **PCIe 4.0 x4**; 320 W PSU behind a 160 W APU → external attach is forced |
| **GPU** | AMD **Radeon AI PRO R9700 32 GB** (RDNA4, `gfx1201`, ~640 GB/s/card, 300 W) — Micro Center, pickup tomorrow. A second card makes this **64 GB VRAM / ~1280 GB/s aggregate** | Not a 9070 XT: 32 GB VRAM, pro SKU, 300 W sustained. Community posts routinely conflate the two — separate them. Note that capacity doubles cleanly with a 2nd card but per-stream bandwidth does not — see report §2 |
| **Dock** | Minisforum **Degu 2** (OCuLink SFF-8612 **and** Thunderbolt 4 / USB4 in one enclosure) | One box, two interconnects → a natural A/B test. Assess whether it feeds and cools 300 W |
| **Software goal** | **Agentic coding**: GitHub Copilot + free/open harnesses (Continue, Cline, Aider, llama.cpp server, LM Studio, Open WebUI) | I want a capable **free open-weight model working alongside Copilot**, with tool calling |
| **Budget** | **No new RAM, CPUs, or GPUs** in the near future | Every recommendation must work with 128 GB unified + 32 GB VRAM + wires I already own. Anything needing a purchase = "FYI" only |

**Core question:** how much faster can agentic coding get by adding one (later maybe two) R9700 32 GB to this box, what will surprise me, and how do I extract the most from what I have?

---

## 2. Report questions (the research)

### 2.1 What to expect — the physics
- Real-world Strix Halo 395 unified bandwidth (measured ~200–250 GB/s vs 256 theoretical) and what it means for **prefill vs decode** on realistic coding models.
- R9700 640 GB/s vs Strix ~230 GB/s: expected tokens/s multiplier for models that **fit in 32 GB**, and the opposite story for models that **don't** (hybrid CPU/GPU layer split is usually a trap — show the numbers).
- Does the wire change *decode* speed? Establish that USB4 (~32–40 Gbps) ≈ OCuLink (PCIe 4.0 x4) after model load, and quantify the cases where link speed does matter: model load time, hybrid inference across the link, KV-cache-heavy long contexts, multi-card traffic.
- ROCm reality on this pair: `gfx1201` (R9700) + `gfx1151` (Strix iGPU) coexistence, 64-bit ROCm, kernel driver vs `amdgpu` options, HSA overrides, llama.cpp **ROCm vs Vulkan** backend maturity on RDNA4.

### 2.2 Community experience — the receipts (every claim linked)
Mine and cross-reference, with a link table grouped by topic:
- **lucebox.com** — R9700 + Strix Halo builds, OCuLink experience, Mellanox ConnectX-5 and 10/25/40 GbE networking workarounds.
- **Level1Techs video + forum thread** for [2x R9700s + 128 GB Strix Halo](https://www.youtube.com/watch?v=RfkeZ0HciA0): the diagram I screenshotted is Framework Desktop (PCIe **4.0 x4** bottleneck) → **PEX89xxx** switch → 2× PCIe **5.0 x8** R9700s. Also their "we have 192 GB Strix Halo at home" note → Gorgon vs Strix comparison. Find the linked forum thread for measured numbers.
- **vuln.dev** — local LLM GPU writeups; pull any R9700 / RDNA4 / Strix Halo benchmarks.
- **strixhalo.wiki** eGPU compatibility matrix; **r/LocalLLaMA**, **r/AMD**; **Minisforum official forum** threads specifically about the **MS-S1 Max 395 128 GB** and Degu/DESeries docks; **Phoronix** for ROCm kernel status.
- **Gorgon Halo vs Strix Halo**: PCIe generation and lane count available to an eGPU, memory bandwidth, dGPU-in-chassis options, firmware maturity — state plainly which community findings transfer and which don't.
- **MS-S1-specific** issues: BIOS settings, firmware updates, thunderbolt/USB4 security level, ASPM, hot-plug behavior, known dock enumeration bugs.
- **Networking side-quest**: is a ConnectX-5 / 10 GbE+ card worth anything here given the host's x4 Gen 4 ceiling? Yes/no with reasoning.
- Specifically flag whether anyone is running **exactly this combo** (MS-S1 Max + Degu 2 + R9700) and what they report.

### 2.3 The guide — staged bring-up runbook
Copy-pasteable, one checkpoint per stage ("how do I know this worked"):
- **Stage 0 — USB4 / Thunderbolt 4 (tonight).** Distro + kernel choice (Ubuntu 24.04 LTS, 6.11+ HWE), `amdgpu` + ROCm install covering `gfx1201` **and** `gfx1151`, enumeration checks (`rocm-smi`, `lspci`, `/sys/class/drm`), llama.cpp backend choice, first benchmark (`pp512` / `tg32` on a Qwen3-Coder-class model). Known USB4 eGPU pitfalls on Strix Halo; power-on sequencing (dock before host).
- **Stage 1 — OCuLink (the real win).** Cable/keying SFF-8612 vs SFF-TA-1002, **power-off hot-plug warning**, MS-S1 BIOS settings (Above-4G decoding, ASPM), expected vs measured delta vs USB4 (mostly load time + stability).
- **Stage 2 — PCIe Gen5 switch (PEX89xxx pattern).** When the Level1Techs switch topology pays off, and why on the MS-S1 the host's **x4 Gen 4 ceiling** makes a switch nearly pointless for one card. Include a "if I ever go internal" note.
- **Stage 3 — a second R9700 (hypothetical).** What the community actually gets from tensor-parallel vs layer-split pairs, RDNA4 **P2P status**, and why "one card active per token" makes the speed case weak — capacity yes, speed mostly no.

### 2.4 Squeezing the box: ideas for the hardware I'm keeping
Ranked by expected real-world tokens/s or task-time gain, no spend required:
- **Layer placement between VRAM and unified memory** — `--n-cpu-layer`, `--override-tensor`, `--tensor-split`; which layers belong where; how the community handles 100B-class MoE (Qwen3-Coder-30B/480B-A3B, GLM-4.5-Air class, distilled DeepSeek) that won't fit in 32 GB.
- **Split-engine strategy (my favorite idea)** — R9700 runs a fast code model for tight agent/edit loops while Strix unified holds a big slow planner model; route between them with llama-swap / LiteLLM / a proxy. Document latency and context-length tradeoffs.
- **Prefill & cache reuse ("my prefetch idea")** — `--cache-prompt`, prefix reuse across agent turns, system-prompt stability for cache hits, `--mmap`, F16 vs Q8 KV cache, keeping KV on the R9700, `--no-kv-offload` style options; speculative decoding (MTP / lookahead / eagle) support status on ROCm.
- **Quantization thresholds** that keep a model *entirely* in 32 GB at my working context lengths (fits-beats-faster), IQ4 / Q4_K_XL / Q5 guidance.
- **Strix-side tuning** — RAM clock / UMCTL tuning (BIOS/AGESA) if available on MS-S1, UMA vs split GPU memory allotment, `numactl`, hugepages, power/TDP profile on the 395.
- **Batching & concurrency** for agent workloads: multiple sequences, parallel tool calls, `--parallel`, when a second model instance beats one big one.
- **Harness fit** — which open coding models + harnesses actually work well against local servers (tool-calling quality, context needs), and a concrete "start here" model list for someone moving from Copilot-only to Copilot + local.

### 2.5 Surprise list (what bites at week two)
ROCm/amdgpu update regressions and how to pin; thunderbolt security level; dock firmware; card sleep/resume recovery; 300 W sustained thermals and airflow in the Degu 2; kernel 6.x amdgpu regressions; Windows vs Linux gap (assume Linux, report what Windows users see); Vulkan occasionally more stable than ROCm on RDNA4; `rocm-smi` vs vendor tools; the "it was the prompt cache all along" cases; PSU/fan noise expectations.

---

## 3. Report format

One Markdown file with **visuals** (I like visuals), using things that render natively on GitHub and in VS Code preview:
- **Mermaid** topology diagrams for Stages 0–3: host → wire → GPU, labeled with real lane width + generation + usable GB/s.
- **ASCII bandwidth ladder** and a prefill-vs-decode comparison table built only from cited numbers.
- **Community benchmark tables**, each row carrying its source link; no unsourced numbers.
- **Runbook sidebars**: fenced code blocks per stage, copy-paste ready, with "verify" commands.
- **Link appendix** grouped by stage/topic so others with this combo can find support fast.
- Explicitly label each claim as **[measured]**, **[vendor]**, or **[folklore]**.

Suggested structure: TL;DR → what I expected vs what happened → physics → community findings → staged guide → tuning ideas ranked → surprises → reference links.

---

## 4. Guards

- **Time-box research to 30 minutes.** Stop and report what's solid; don't chase.
- **Local model only.** No cloud models; no sub-agents on a different model.
- **If one research tool struggles, use another** (`web_search`, `web_fetch`, `curl`). Note: `curl` fetches content but is poor at capturing page *design* — different tools for different jobs.
- **No purchase recommendations.** Anything requiring new hardware = clearly labeled FYI.
- Separate **measured facts** from **community folklore** everywhere.
- Keep both files out of git.
