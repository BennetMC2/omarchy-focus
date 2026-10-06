# Release checklist

What's left before 2.3.0 gets a tag:

- [ ] Try the screenshot flow against a real agent: capture, cancel, preview, send.
- [ ] Read the release notes once more.
- [ ] Tag the release.
- [ ] Marketplace listing approved (submitted 6 October, waiting on a maintainer).

Already done: tests passing on GitHub, a secret scan of the Git history, live runs with all four agents, a fresh install on a second machine, private vulnerability reporting switched on, and the marketplace submission.

## Checking a fresh install

Worth repeating before any big release, on a spare Omarchy install with a throwaway browser profile. Mocked tests don't replace this.

1. Install it and run `focusctl doctor`.
2. Check that a missing agent or a missing `bwrap` gives a message you can act on.
3. Sign in, finish setup, restart the browser.
4. Add two tasks, pick the main one, press Start day.
5. Block a made-up `.invalid` domain and check the blocked page appears.
6. Open a spare app window and check it gets parked, then comes back when you unlock.
7. Run through a screenshot: capture, cancel, preview, send.
8. Restart the shell and check tasks, settings and pending changes are still there.
9. Update from the previous version and check nothing is lost.
10. Run `focusctl recover` and check the browser policies, hosts entries and parked windows are all cleared.
11. Run `focusctl uninstall` and check your other browser extensions and flags are untouched.
12. Restart the browser and check Bouncer is gone.

Note down the Omarchy, Quickshell, browser, Python and agent versions you used.
