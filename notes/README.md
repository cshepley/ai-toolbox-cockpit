# Fork notes

Everything in this folder is **fork-only**. Nothing here is intended for upstream
(`kyuz0/ai-toolbox-cockpit`), and nothing here changes how the cockpit behaves.

Upstream packaging (`MANIFEST.in`) ships `docs/*.md`, `scripts/*.py`, and `tests/*.py`.
It does **not** ship `notes/`, which is exactly why personal material lives here:
pulling upstream changes never collides with these files, and a published
distribution stays clean.

## Layout

| Path | What it holds |
| --- | --- |
| [`hardware/`](hardware/README.md) | Personal hardware purchase + performance research (V100, R9700 eGPU on the Strix Halo box). Not project content. |
| [`hardware/proxmox/`](hardware/proxmox/README.md) | The Proxmox host running this cockpit on Ubuntu Server + Ubuntu Desktop VMs. |

## Rules for this folder

- **Never propose these files in a PR to upstream.** They reference my hardware, my
  street prices, and my purchasing history.
- **Real project documentation belongs in [`../docs/`](../docs),** not here. If a
  note here turns into something another maintainer needs, promote it to `docs/`
  and strip the personal context.
- **Real tooling belongs in [`../scripts/`](../scripts)** with a matching test in
  `tests/`. Notes are prose, not code.

## Where the fork's actual code changes live

The fork's substantive contribution is the model-independent Halogen chat stack,
which is *not* in this folder:

- `scripts/halogen_chat.sh`, `scripts/halogen_open_webui.py`, `scripts/open_webui_proxy.py`
- `tests/test_halogen_open_webui.py`, `tests/test_open_webui_proxy.py`
- [`../docs/HALOGEN_CHAT_UI.md`](../docs/HALOGEN_CHAT_UI.md),
  [`../docs/HALOGEN_REBOOT_RUNBOOK.md`](../docs/HALOGEN_REBOOT_RUNBOOK.md)

See also [`../TODO.md`](../TODO.md) and [`../IMPLEMENTATION_NOTES.md`](../IMPLEMENTATION_NOTES.md)
(upstream-owned, still tracked at the repo root).
