# Omarchy Focus

A plugin for the Omarchy shell that blocks the sites and apps that distract you until you've done what you said you'd do today.

There's one small card with an agent on it. Tell it your tasks, or use **Add task** to put them straight on the list. It manages the blocklist and checks your work before it lets you back on YouTube.

Your tasks, history and settings are stored on your machine. Focus uses Claude, OpenAI through Codex, Grok through Grok Build, or whichever provider you pick in OpenCode. What you type, plus any files or screenshots you let it see, goes to the provider you've chosen. More in [Privacy](#privacy).

If this plug-in helps you stay focused and productive, please give it a star and pass it on. https://ko-fi.com/bennetmc 

![The Focus card with sample tasks](docs/images/card.png)

## Using it

Open the card from the bar icon, or run `omarchy-shell local.focus toggle`. Enter sends, Shift+Enter adds a line, Esc closes. **Start day** starts the day; an empty Enter doesn't.

- **First run:** it asks what usually distracts you and sets up system-wide blocking. You'll get a password prompt. Blocking starts when setup finishes.
- **Morning:** say something like "emails, call mum, ship the importer". Quick capture adds the tasks without follow-up questions. It keeps your main task, or picks the first if none is set. Press **Start day** when you're ready.
- **Add tasks directly:** choose **Add task**, type one per line, and send. No model call is needed. Before starting, click a task to edit it, use ★ to choose the main task, or × to remove a mistake.
- **During the day:** "done with the importer, it's in ~/Projects/importer". It asks permission to read the folder, checks the code and passes or fails it with a one-line note. Where your mode allows it, things it can't inspect can pass "on your word".
- **Changes:** "block reddit too", "drop the dentist one", "let me on youtube". Just ask. Once the day has started, the rules below apply.
- **Settings:** choose the agent, planning style and mode. See the full blocklist and approved folders there. **History** shows the recent conversation.
- **From a terminal or another agent:** `focusctl say "..."`

Quick capture is the default. If you want help turning a vague list into a plan, choose **Guided** in Settings or type `/planning guided`. `/planning quick` switches back. Planning style doesn't change how strictly your work is reviewed.

## Modes

Tell it "go hard today" or use Settings. You can move up a mode at any time, but you can only move down before the day starts.

| Mode | What counts as proof | Rules |
|---|---|---|
| honor | Your word, in one line. | Emergency unlock any time. |
| standard | It checks what it can. For everything else, you tell it exactly what you did. | 30-second wait on task changes. |
| hard | Evidence for everything: files, a screenshot where supported, a link, or a timer. | One emergency unlock a day. 2-minute wait on task changes. |
| lockdown | Same as hard, and the main task has to pass first. | No emergency unlock. The list is fixed once the day starts. |

An emergency unlock means typing a 32-character code and waiting a minute. That gets you 15 minutes and records the override. Blocks can't be loosened after starting the day.

Before starting, you can agree that a task passes on your word, except in lockdown. Time-based tasks like "read for 30 minutes" can use a timer on the card.

Focus is an accountability tool. You own the machine and can remove it. It isn't a tamper-proof parental control.

## How it looks

- Opening something blocked triggers a full-screen takeover: rain in your theme's colours, ACCESS DENIED, a short nudge, then the card.
- Passing your last task plays ACCESS GRANTED. Each new day opens with a short briefing.
- While you're locked, window borders turn your theme's red and a thin strip under the bar shows your main task.
- Sound is off by default. To change borders, the strip or sound, just ask: "turn the strip off".
- Completed tasks fold away. Your input stays visible while you scroll the list.

Preview the effects without touching your state:

```sh
omarchy-shell local.focus preview denied    # also: granted, morning, strip, honor, hard, lockdown
```

## Install

You need Omarchy 4 with the Quickshell plugin system, Python 3.11+, and one supported agent already signed in:

- Claude Code
- Codex
- Grok Build
- OpenCode, signed in to a provider (its free models refuse headless use)

Focus follows `omarchy default agent` when that agent is supported. You can choose another in Settings.

Codex, Grok, OpenCode and Git evidence need `bubblewrap` (`bwrap`). Screenshots need `grim`; clipboard images need `wl-paste`. The companion browser extension supports Chromium and Brave. Other browsers may get hosts-based blocking, but don't get the custom blocked page.

```sh
omarchy plugin add https://github.com/BennetMC2/omarchy-focus --enable
ln -sf ~/.config/omarchy/plugins/local.focus/focusctl ~/.local/bin/focusctl
focusctl doctor
omarchy restart shell
```

`omarchy plugin add` shows you what it's going to clone and asks before enabling it. `focusctl doctor` checks dependencies without changing anything. A stored login isn't proof that the account can make a request; send a message to confirm that.

Click the Focus icon in the bar. It walks you through setup, including the password prompt. Restart your browser after the extension is added.

## Updating

Focus looks for a newer version about four times a day by fetching from the repository it was installed from. When there is one, the card says so. Nothing installs until you choose **Update** on the card, type `/update`, or run:

```sh
focusctl update            # --check only reports
```

The install is `omarchy plugin update local.focus`: fast-forward only, validated, and rolled back if the new copy isn't a valid plugin. Focus then restarts the shell so the new Python and QML load. Tasks and history are kept. A copy with local edits won't fast-forward; Focus reports that instead of overwriting them.

If a version ships a new root helper, the card offers **Refresh**, which asks for your password once. Until then the installed helper keeps working.

To stop the check, turn off **Check automatically** in Settings or type `/update off`. The check contacts the Git host (GitHub by default) and sends nothing about your tasks.

## Privacy

**Stored locally:** tasks, verdicts, history, settings and the blocklist, in `~/.local/state/local.focus/`.

**Sent to the model:** the conversation context, your task list, and anything you let the agent look at: files, Git views, links and screenshots. That goes to Anthropic for Claude, OpenAI for Codex, xAI for Grok, or the provider of the model you chose for OpenCode. Focus identifies the provider before your first message.

**What the agent can access:** Focus supplies tools for task management and approved evidence. Claude's built-in tools are disabled. Codex, Grok and OpenCode also run inside a filesystem and network sandbox; their configuration is described below.

- **Files and Git:** only in folders you approve. Secrets such as `.env`, `*.pem`, `id_rsa`, agent sign-in folders and `.git/config` stay off-limits even inside an approved folder. These checks reduce exposure; they cannot recognise every secret in an otherwise ordinary file. Git runs read-only in a sandbox with no network.
- **Links:** only the exact URL you approve, only on the public internet, with redirects kept to the same site.
- **Screenshots:** you approve the capture, see the image, then approve sending it. Focus deletes its saved image after handing it to the agent once. Pasted images also need approval before sending. Grok and OpenCode screenshot review is not enabled in this beta.

Only you can approve access. The agent can ask, but it has no tool to give itself a folder, link, provider or model.

`/forget` (or `focusctl forget`) deletes Focus's conversation, approved links and any saved screenshot. The conversation also resets each day. This doesn't delete data already sent to a provider. Provider retention and account terms still apply.

## Which agent it uses

Focus has no login of its own. It runs a coding agent you already have.

| Agent | How it runs | Evidence |
|---|---|---|
| Claude Code | A long-running session with its built-in tools turned off. | Files, Git, links and approved screenshots |
| Codex (OpenAI) | A new sandboxed process for each reply. | Files, Git, links and approved screenshots |
| Grok Build | A new sandboxed process for each reply, with an isolated profile. | Files, Git and links; screenshots are deferred |
| OpenCode | A new sandboxed process for each reply, with an isolated profile. | Files, Git and links; screenshots are deferred |

Reply times depend on the model and provider. The [compatibility notes](docs/compatibility.md) record the local tests rather than promising a fixed speed.

Choose in Settings or type `/provider claude`, `/provider codex`, `/provider grok`, `/provider opencode` or `/provider auto`. Auto follows Omarchy where possible; otherwise Focus names the supported agent it uses instead. An explicit choice never silently switches providers when it fails.

For Codex, Grok and OpenCode:

- No `bwrap`, no agent.
- The sandbox exposes the agent runtime, Focus's code and tool socket, and scratch storage.
- Codex can access its own sign-in directory. Grok receives a private copy of its login, without the user's plugins or hooks. Grok's temporary profile is removed at the end of the turn. OpenCode gets the same treatment: a copy of its sign-in and nothing else, so your OpenCode sessions, plugins and configuration stay out of the sandbox. If OpenCode renews the sign-in during a turn, the renewed copy is written back.
- There is no direct network access. A local gate allows HTTPS connections only to that provider's configured hosts.
- Codex receives an approved screenshot as an attachment for that turn.

For a smaller Claude model, choose **haiku** in Settings or type `/model haiku`. Codex runs at low reasoning effort. Grok uses its CLI default unless you select a model.

OpenCode needs a model chosen, because the model's provider decides where the sandbox may connect: `/models` lists what your sign-ins offer, then `/model openai/MODEL`. Focus routes OpenCode to OpenAI, Anthropic, Google, xAI, OpenRouter and OpenCode's own service; other providers are refused rather than given an open route. Only the OpenAI route has been run live. A listed model can still be refused by your plan; the provider's message is shown when that happens.

This beta's supported list is Claude, Codex, Grok and OpenCode.

## Choosing the model

These commands work even when the model isn't reachable:

```text
/config                       show planning style, model and approved folders
/planning quick               capture without planning questions
/planning guided              help clarify tasks
/provider grok                choose Grok (or claude, codex, opencode, auto)
/models                       list models, or show how to find them
/model haiku                  choose a model for the current provider
/folder ~/Projects/importer   approve a folder
/folder remove ~/Projects/importer
/update                       install a newer Focus (/update check, /update on|off)
/help
```

From the terminal: `focusctl config provider grok`, `focusctl config model MODEL`, or `focusctl config planning quick`.

## How it fits together

| File | What it does |
|---|---|
| `model.py` | Tasks, verdicts, wait times, unlock rules and streaks. State changes go through here. |
| `tools.py` | The agent's tools. Thin wrappers over the model and evidence checks. |
| `evidence.py` | Approved folders, sandboxed Git and approved links. |
| `backend.py`, `agent.py`, `netgate.py` | Provider details, agent sessions and the network gate. |
| `daemon.py` | Owns state, blocking, agent sessions and clients over a user-only Unix socket. |
| `mcp.py` | Passes the agent's tool calls to the service. |
| `blocking.py` | Parks blocked windows, calls the root helper and connects the browser. |
| `focus.py`, `doctor.py` | CLI, browser bridge, recovery, uninstall and dependency checks. |
| `update.py` | Notices a newer published version and hands the install to Omarchy's plugin updater. |
| `FocusCard.qml`, `Service.qml`, `FocusOverlay.qml`, `Focus.qml` | The card, service connection, takeovers and bar icon. |
| `setup/focus-root-helper` | Writes Focus's browser policy files and a marked block in `/etc/hosts`. |
| `browser/extension/` | Companion extension for the blocked page. |

## Uninstall

```sh
focusctl uninstall
```

It recovers first, removes Focus's extension path and native-host registrations, removes the plugin through Omarchy, and removes the system helper and its policy files. Other browser flags and extensions are kept. You may get a password prompt. Restart your browser afterward.

Your tasks and history stay in `~/.local/state/local.focus/`. Browser flag backups are kept too. Uninstall stops if recovery fails, so it doesn't remove the service while leaving its blocks behind.

## Recovery

`focusctl recover` removes every Focus block and keeps blocking off until you explicitly start the day again.

If the service is down:

```sh
pkexec /usr/local/bin/focus-root-helper recover
```

That clears system website blocks. Use `focusctl recover` as well to persist recovery mode and restore parked windows.

## Tests

```sh
python3 -m unittest discover -s tests
node --test --test-isolation=none tests/browser.test.cjs
omarchy plugin validate .
```

These tests use temporary state, mock desktop integration and scripted agents. They don't touch your real tasks or system blocking.

Live provider checks are separate and use your existing login:

```sh
python3 dev/agent_smoke.py grok --output /tmp/focus-grok.json
```

That sends synthetic tasks and a synthetic file to the provider. It can use your account quota. It doesn't start desktop blocking.

To render the actual card with sample data:

```sh
python3 dev/preview.py --output /tmp/focus-card.png
```
