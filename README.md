# Omarchy Focus

Tell it your day. Earn your distractions back.

Omarchy Focus is an Omarchy shell plugin. Each morning you say what has to get done; until those tasks pass review, the websites and apps that pull you off course stay blocked. There are no forms or buttons. You talk to one agent on one small card, and it runs everything through tools: the task list, the blocklist, the reviews, the rules.

Your tasks, history and settings stay in files on your machine. The agent does not: by default it is Claude, running on Anthropic's servers, so what you type and any evidence you let it look at is sent there. See [Privacy](#privacy).

## Using it

Open the card from the bar icon or `omarchy-shell local.focus toggle`. Type or dictate; Enter sends, Esc closes. When Focus asks something with an obvious answer it offers it as ghost text: Enter accepts.

- First run: it asks what distracts you, blocks it, and sets up system blocking (one password prompt).
- Morning: "emails, call mum, ship the importer". It splits that into checkable tasks, asks about anything vague, picks the main one, and starts when you agree.
- During the day: "done with the importer, it's in ~/Projects/importer". It looks at the code and passes or fails it with a one-line note. For things it cannot see it questions you, and marks the pass "on your word".
- "block reddit too", "drop the dentist one", "let me on youtube": all by asking. Rules still apply: after the day starts, changes to tasks take 30 seconds to land, blocks cannot be loosened, and an emergency unlock means typing a 32-character code and waiting a minute for 15 minutes of access.

From a terminal or another agent: `focusctl say "..."`.

## Modes

Say "go hard today" and it switches. A mode can be raised any time, but lowered only before the day starts.

| Mode | Proof it takes | Rules |
|---|---|---|
| honor | Your word, one line. | Emergency unlock any time. |
| standard | It checks what it can see; a specific account for the rest. | 30-second cooling-off on task changes. |
| hard | Evidence for everything: files, a screenshot it looks at, a link it opens, or a timer it runs. | One emergency unlock a day; two-minute cooling-off. |
| lockdown | As hard, and the main task must pass first. | No emergency unlock; the list is fixed once the day starts. |

In the morning you can agree that one task "passes on my word" (not in lockdown). Tasks about spending time ("read for 30 minutes") get a timer on the card.

## Look

- Hitting something blocked plays a takeover: rain in your theme's colours, `ACCESS DENIED`, a line to get you moving, then the card. The last pass plays `ACCESS GRANTED`; a new day opens with a short briefing.
- While locked, window borders turn the theme's red and a thin strip under the bar shows the main task.
- Hard and lockdown add scanlines; lockdown runs in red.
- Streaks earn a rank, shown in the card header.
- Sound is off by default. Borders, the strip and sound are switched by asking ("turn the strip off").

Preview any of it without changing state:

```sh
omarchy-shell local.focus preview denied    # or granted, morning, strip, honor, hard, lockdown
```

## Install

Needs Omarchy 4 (Quickshell shell), Python 3.11+, and one coding agent you are already signed in to: Claude Code, Codex or OpenCode. Focus uses whichever one Omarchy is set to (`omarchy default agent`). So far this has only run on its author's machine.

```sh
omarchy plugin add https://github.com/BennetMC2/omarchy-focus --enable
ln -sf ~/.config/omarchy/plugins/local.focus/focusctl ~/.local/bin/focusctl
omarchy restart shell
```

`omarchy plugin add` shows what it is about to clone and asks before enabling it.

Then click the Focus icon in the bar. It walks you through the rest, including the one password prompt for system-wide website blocking.

## Privacy

- **On this machine:** tasks, verdicts, history, settings and the blocklist (`~/.local/state/local.focus/`).
- **Sent to the model:** everything in the conversation. That means what you type, your task list, and the contents of any file, git view, link or screenshot you let the agent look at. With the default provider that goes to Anthropic. Focus tells you this before your first message.
- **What the agent can reach:** nothing by default. It has no shell, no file access and no network of its own; its only tools are Focus's.
  - Files and git: only inside folders you approve, one at a time. Keys and credentials (`.env`, `*.pem`, `id_rsa`, `.git/config` and similar) are never readable, even inside an approved folder. Git runs in a read-only sandbox with no network (needs `bwrap`).
  - Links: only the exact link you approve, only on the public internet, with redirects kept to the same site.
  - Screenshots: you approve the capture, see the image, and approve sending it. It is shown to the agent once and deleted.
- **Approving is yours alone.** The agent can ask; it has no tool to grant itself a folder, a link, a provider or a model.
- `/forget` (or `focusctl forget`) deletes the conversation, approved links and any stored screenshot. The conversation also clears each new day.

### Which agent it uses

Focus does not have its own login. It drives a coding agent you already have:

| Agent | How it runs | Speed |
|---|---|---|
| Claude Code | One long-running session with all of its own tools switched off. | A reply in 2 to 5 seconds, streamed. |
| OpenCode | A fresh process per reply, inside a sandbox. | About 10 to 15 seconds. |
| Codex | A fresh process per reply, inside a sandbox. | About 15 to 25 seconds. |

By default it follows `omarchy default agent`; `/provider claude|codex|opencode|ollama|auto` overrides that. Codex and OpenCode cannot have every tool of their own switched off, so Focus only runs them inside a sandbox (`bwrap`) where they can see their own sign-in files and Focus's tool socket and nothing else of your home directory; without `bwrap` they are refused. They are not shown screenshots yet.

To keep the cost down, pick a smaller model: with Claude, click **Low cost** in the card (Haiku) or type `/model haiku`; with the others, `/models` lists what they can run.

### Choosing the model

Type these in the card, or use `focusctl config`; they work even when no model is reachable.

```
/config                      show the model and approved folders
/folder ~/Projects           approve a folder   (/folder remove ~/Projects)
/provider ollama             run on an Ollama server instead of Claude
/model qwen3:14b             which model (for Claude: sonnet, opus, haiku or a full id)
/endpoint http://127.0.0.1:11434
```

With Ollama, Focus asks the server what the model is and can do. A model without tool calling is refused; one without vision cannot be shown screenshots. A server on `127.0.0.1` is only called local if the model itself runs there: Ollama can relay to cloud models, and Focus labels those as remote. If the server or model is unavailable you get an error; Focus never falls back to another provider on its own.

Ollama mode still uses the Claude Code program as the harness, pointed at your server with an empty profile (no cloud login) and its telemetry switched off. Focus does not verify that the harness makes no other network requests, so treat "runs on this machine" as a statement about where the model runs, not a guarantee of an offline workflow.

## How it fits together

| File | Role |
|---|---|
| `model.py` | The day: tasks, verdicts, cooling-off, unlock rules, streaks. Every change goes through it. |
| `tools.py` | The agent's tools. Thin wrappers over the model, so the agent cannot do what the rules forbid. |
| `evidence.py` | Everything the agent may look at: approved folders, sandboxed git, approved links. Enforced in code. |
| `backend.py` | Which model is in use, where it actually runs, and what it can do. |
| `agent.py` | The agent's instructions and its long-running streaming session. |
| `daemon.py` | The service: one loop owning state, blocking, the agent and all clients over a user-only Unix socket. Pushes updates; nothing polls. |
| `mcp.py` | Tool server the agent process talks to; forwards tool calls to the service. |
| `blocking.py` | Parks blocked windows, drives the root helper, connects the browser. |
| `focus.py` | Entry point: service, `focusctl` commands, browser native bridge. |
| `Service.qml`, `FocusOverlay.qml`, `Focus.qml`, `TaskPanel.qml` | Shell service, the card, the bar icon, the panel host. |
| `setup/focus-root-helper` | Root-owned helper: writes only Focus's own browser policy files and a marked block in `/etc/hosts`. |
| `browser/` | Companion extension: redirects blocked sites to a local page. |

State lives in `~/.local/state/local.focus/` (`state.json`, `chat.json`).

## Uninstall

```sh
focusctl recover                      # remove every block first
omarchy plugin remove local.focus
rm ~/.local/bin/focusctl
sudo rm /usr/local/bin/focus-root-helper /usr/share/polkit-1/actions/local.focus.policy /etc/polkit-1/rules.d/49-local.focus.rules
```

It also added its extension to `~/.config/chromium-flags.conf` (and Brave's), keeping the original as `chromium-flags.conf.before-focus`, and a `local.omarchy.focus.json` under each browser's `NativeMessagingHosts`. State is in `~/.local/state/local.focus/`.

## Recovery

`focusctl recover` removes every block and keeps blocking off until the day is started again. If the service is down: `pkexec /usr/local/bin/focus-root-helper recover`.

## Tests

```sh
python3 -m unittest discover -s tests
node --test --test-isolation=none tests/browser.test.cjs
```

The tests run against temporary state with a scripted stand-in for the agent; they never touch real tasks or system blocking.
