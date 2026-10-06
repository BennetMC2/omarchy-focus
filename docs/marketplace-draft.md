# Marketplace submission

Submitted on 6 October 2026: https://github.com/omacom/omarchy-plugin-marketplace/issues/10210

For later versions, use the marketplace's Plugin verification form with the new commit SHA. Otherwise the listing shows "Update unverified".

What was sent:

Name: Bouncer: Focus To-Do List
Repository: https://github.com/BennetMC2/omarchy-focus
Plugin ID: local.focus
Version: 2.3.0-beta.1
Category: Productivity
Tags: ai, quickshell, hyprland
Suggested tag: focus

Maintainer notes:

Needs an already signed-in coding agent (Claude Code, Codex, Grok Build or OpenCode); Codex, Grok, OpenCode and Git evidence need bubblewrap. First-run setup asks before it changes anything outside the plugin: one password prompt installs a small root-owned helper (/usr/local/bin/focus-root-helper) and a polkit rule limited to that helper, which only writes Bouncer's own browser policy files and one marked block in /etc/hosts. The same step adds the companion extension to the Chromium/Brave flags files, keeping a backup. `focusctl recover` removes all blocking and `focusctl uninstall` removes everything.
