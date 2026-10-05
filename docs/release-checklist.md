# Public beta checklist

## Prepared locally

- [x] Task-first card, separate Settings and History.
- [x] Direct task capture, morning edits, explicit Start day.
- [x] Atomic batches and capture retry receipts.
- [x] Claude, Codex and Grok session support.
- [x] Dependency checks and browser uninstall cleanup.
- [x] Automated regression tests and live provider smoke checks.
- [x] README, changelog and compatibility notes.
- [x] CI workflow, sample screenshots and a 14-second UI demo.
- [x] Gitleaks scan of all reachable Git history and the working tree: no findings.

## Before publication

- [x] User approves the card preview.
- [x] Install the approved candidate locally and test the real card connection.
- [ ] Exercise screenshot consent with a live supported provider.
- [ ] Fresh-machine install, upgrade, browser blocking, recovery and uninstall.
- [ ] Review the release notes and demo.
- [ ] Run CI on GitHub.
- [ ] Confirm repository visibility, release tag and marketplace submission.
- [ ] Enable GitHub private vulnerability reporting.

## Fresh-machine run

Use a disposable Omarchy installation and a throwaway browser profile.

1. Install from the candidate commit; run `focusctl doctor`.
2. Verify a missing agent or missing bwrap gives an actionable message.
3. Sign in, finish setup, restart the browser.
4. Add two tasks; choose the main task; start explicitly.
5. Block a reserved `.invalid` domain and verify the extension's blocked page.
6. Use a disposable app window to verify parking and restoration.
7. Exercise screenshot capture, cancel, preview and share with synthetic content.
8. Restart the shell; confirm tasks, settings and pending changes survive.
9. Upgrade from the previous version without losing state.
10. Recover; check browser policies, hosts entries and parked windows.
11. Run `focusctl uninstall`; check that other browser extensions and flags remain.
12. Restart the browser and confirm Focus is gone.

Record Omarchy, Quickshell, browser, Python and agent versions. Don't substitute mocked tests for this run.
