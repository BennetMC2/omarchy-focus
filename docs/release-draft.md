# Bouncer 2.3.0 beta

Bouncer keeps your distracting sites and apps blocked until you've done what you said you'd do today. You tell it your tasks, it checks your work, and you get YouTube back when the list is done.

It runs on a coding agent you already have. This version works with Claude Code, Codex, Grok Build and OpenCode. Your tasks stay on your machine; what you say to the agent, and anything you let it look at, goes to whichever provider you picked.

What's new in this one:

- The card is shorter and puts your tasks first. Settings and History have their own pages.
- You can add tasks straight to the list without waiting for the agent, and edit them before the day starts.
- The day starts when you press Start day, not by accident.
- By default it just takes your tasks down without quizzing you. Guided planning is still there if you want the help.
- Grok Build and OpenCode join Claude Code and Codex.
- Bouncer tells you when there's a newer version and installs it when you say so.
- `focusctl doctor` tells you what's missing, and `focusctl uninstall` cleans up after itself properly.

It's still a beta. Grok and OpenCode can't look at screenshots yet, and [what's been tested](compatibility.md) spells out the rest. Install and recovery steps are in the README.
