# Proxmox host — cockpit deployment

> **Scaffold.** Written before the install was finished, so hardware specifics are
> placeholders. Fill in each `TBD` as the host comes up and delete this banner once
> the tables are real. Everything below marked *(verify)* is a general requirement,
> not something confirmed on this machine.

## 1. Host inventory

| Item | Value |
| --- | --- |
| Proxmox VE version | TBD (`pveversion`) |
| Node name | TBD (`hostname`) |
| Machine | TBD — see [`../`](../README.md) for MS-S1 Max constraints if this is the Strix Halo box |
| Storage pools | TBD (local-lvm / ZFS / NFS) |
| Bridge / VLAN | TBD (`cat /etc/network/interfaces`) |
| GPU(s) passed through | TBD |

## 2. VM roles

| VM | OS | Role | GPU? |
| --- | --- | --- | --- |
| `TBD` | Ubuntu Server (LTS) | **Primary cockpit host.** Runs `ai-toolbox-cockpit` and the toolbox containers. Needs real GPU access. | yes *(verify)* |
| `TBD` | Ubuntu Desktop | Interactive clients: Open WebUI browser, ComfyUI, model management GUIs. | optional |

Rule of thumb: the cockpit drives `podman`/`docker` and expects a usable GPU
(`nvidia-smi` / `rocm-smi` inside the container). Under Proxmox that means the GPU
must be **passed through** to the Server VM — the cockpit cannot share a GPU the
PVE host has claimed. Do not leave the card bound to the host driver.

## 3. GPU passthrough checklist

1. Enable IOMMU in firmware, then on the host:
   - AMD → `amd_iommu=on iommu=pt`
   - Intel → `intel_iommu=on iommu=pt`
   Verify: `dmesg | grep -i -e DMAR -e IOMMU` and that `vfio_pci` loads.
2. Confirm the GPU is in a usable IOMMU group:
   `find /sys/kernel/iommu_groups/ -type l | sort -V`
   An audio function usually rides with the card — pass both, or the group is
   incomplete.
3. Bind the card to `vfio-pci` (PCI IDs + `pcie_acs_override` only as a last
   resort, and note it in this file if used).
4. NVIDIA *(verify)*: single-GPU setups can hit the code-43 / vBIOS display-attach
   issue. Headless compute cards (Tesla-class) generally avoid it; consumer cards
   may need the vendor/IDs hidden or a patched vBIOS.
5. Give the VM `hostperf`/`host` CPU type and huge pages — ROCm and CUDA workloads
   are sensitive to synthetic CPUID.
6. Record the working config here rather than trusting memory across reinstalls.

## 4. Cockpit on the Server VM

```bash
git clone https://github.com/cshepley/ai-toolbox-cockpit.git
cd ai-toolbox-cockpit
python -m venv .venv && . .venv/bin/activate
pip install -e .
ai-toolbox-cockpit
```

- Per [`../../../AGENTS.md`](../../../AGENTS.md): **never** start containers, GPU
  servers, or model downloads on a dev laptop. Runtime behaviour is validated on
  the real GPU host — which, under Proxmox, is this VM. One backend and one
  known-good model at a time.
- Remotes reach the cockpit's backends over the bridge network, not `localhost`.
  Backends bound to `127.0.0.1` (Halogen is `127.0.0.1:8731` by design) need an
  explicit relay to be reachable from another VM — see
  [`../../../docs/HALOGEN_CHAT_UI.md`](../../../docs/HALOGEN_CHAT_UI.md).
- Container mounts need `:z` under SELinux, and secrets go through `--env-file`
  (0600), never `-e KEY=value`.

## 5. Snapshot / restore policy

The reason to keep these notes: a snapshot plus this file should reproduce the
environment from scratch.

- Snapshot **before** any driver, kernel, or Proxmox package upgrade.
- Snapshot the Server VM after each working model is confirmed, with the toolbox
  catalogue state noted in the snapshot message.
- Record anywhere a `pcie_acs_override`, patched vBIOS, or held-back kernel pin is
  load-bearing — those are the things that silently break on restore.

## 6. Open questions

- [ ] Which VM owns the GPU when both are running, and what is the failover plan?
- [ ] Is the cockpit driven from the Desktop VM over the network, or at the console
      of the Server VM?
- [ ] Where do downloaded models live — VM-local disk or a shared mount? Local is
      simpler for passthrough performance; shared saves re-downloading.
- [ ] Backup job covering the VMs plus the model store.
