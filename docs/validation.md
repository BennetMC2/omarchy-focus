# Local validation — 5 October 2026

Candidate: 2.3.0-beta.1. Source changes are prepared locally; the installed plugin has not been replaced pending the agreed UI review.

## Environment

- Omarchy 4.0.4-1
- Quickshell 0.3.1 (Arch package)
- Python 3.14.7
- Node 26.7.0
- Claude Code 2.1.286
- Codex CLI 0.154.0
- Grok Build 1.0.46

## Results

- Python: 83 tests passed. The final command-help refinement also passed its targeted service test.
- Browser extension: six tests passed against mocked browser APIs.
- QML: actual card rendered offscreen. Submission checks passed for disconnected input, refusal, retry identity, multiline capture and acknowledgement. Settings also rendered at 420px window width.
- Plugin manifest: validation passed.
- Python compilation and Git whitespace checks: passed.
- Live provider smoke checks: Claude Haiku, Codex gpt-reserve, and Grok each passed four disposable scenarios. Initial failures and limits are documented in compatibility.md.
- Gitleaks 8.30.1: all reachable history (18 commits) and the final working tree scanned with no findings. The downloaded scanner matched its official release checksum. This is a secret scan, not a complete security audit.
- Sample screenshots and a 14-second demo rendered from the actual card with synthetic data.

## Not yet validated

- The replacement card connected to the user's live service; approval is pending.
- Real screenshot capture/share with a live provider for this candidate.
- Full install/upgrade/recovery/uninstall on a separate, fresh Omarchy desktop.
- GitHub CI execution, public repository visibility, release publication, and marketplace listing.

No real task verdicts, browser blocks, or desktop configuration were changed during these checks. See release-checklist.md for the remaining release gates.
