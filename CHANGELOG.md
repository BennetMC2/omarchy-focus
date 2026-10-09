# Changelog

## 2.3.0-beta.2

- Private prompts, conversation history and task state now reach Grok Build and OpenCode through standard input, instead of process arguments visible to other local users. Grok uses `--prompt-file /dev/stdin`; OpenCode reads the pipe directly. The shared launcher no longer supports passing prompts as arguments.
- Regression tests check the backend and bridge process arguments and environment, and verify complete delivery of a large UTF-8 prompt.

## 2.3.0-beta.1

Renamed from Omarchy Focus to Bouncer. The plugin ID, the `focusctl` command, your tasks and your history are unchanged.

New:

- The card puts your tasks first. Agent settings and the full blocklist moved to a Settings page, and the conversation has its own History page.
- The input stays put while you scroll the list.
- You can add tasks directly, edit them in the morning, and start the day with a button.
- Quick capture is the default: it writes your tasks down without asking questions. Guided planning is still available.
- Grok Build and OpenCode work alongside Claude Code and Codex. OpenCode runs with a throwaway profile, its own tools off, and a network route only to the provider of the model you chose.
- Bouncer notices when a newer version is out and installs it when you ask, from the card, with `/update`, or with `focusctl update`. If a version changes the root helper, the card offers to refresh it.
- `focusctl doctor` checks what's installed, and uninstalling now cleans up the browser flags and native hosts.
- Setup tells you it's adding the browser extension to your launch flags before it does.
- A repeatable live test for each agent, and tests running on GitHub.

Changed:

- Adding several tasks at once is all-or-nothing, and a retried submission can't add them twice.
- Lockdown now refuses new tasks once the day has started, which is what the docs always said.
- The browser extension moved to `browser/extension/` to fit the marketplace's layout. Existing installs are pointed at the new folder the first time they start; restart your browser afterwards.

Fixed:

- Changing the reset time, or the clock going backwards, could put you back in yesterday's finished day and unlock everything with no task passed.
- Rewording a task threw away its check.
- The service was looking up the agent program several times a second while idle.
