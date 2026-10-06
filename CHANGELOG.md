# Changelog

## 2.3.0-beta.1 — unreleased

- Put tasks first in the card. Move agent settings and the full blocklist into Settings.
- Keep the input visible while scrolling. Add a separate conversation history view.
- Add direct task capture, morning edits, and an explicit Start day button.
- Default to quick capture. Guided planning remains available.
- Add Grok Build alongside Claude Code and Codex.
- Add OpenCode: an isolated profile, its own tools off, and a network route only to the chosen model's provider.
- Add whole-batch validation and persistent receipts for direct task submissions.
- Refuse additions after a lockdown day starts, matching the documented rule.
- Add dependency checks and uninstall cleanup for browser flags and native hosts.
- Add a repeatable live-provider smoke test and CI.
- Notice newer published versions and install them on request (card, `/update`, `focusctl update`). Offer to refresh the root helper when a version changes it.
- First-run setup says that it adds the browser extension to the launch flags before it does so.
- Fix: changing the reset time, or a clock set backwards, could reopen a finished day and unlock without any task passing.
- Fix: rewording a task no longer discards its check.
- Fix: the idle service no longer looks up the agent binary several times a second.
