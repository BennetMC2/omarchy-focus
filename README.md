# Omarchy Focus

Tell it your day. Earn your distractions back.

Omarchy Focus is an Omarchy shell plugin. Each morning you say what has to get done; until those tasks pass review, the websites and apps that pull you off course stay blocked. There are no forms or buttons. You talk to one agent on one small card, and it runs everything through tools: the task list, the blocklist, the reviews, the rules.

Everything is local. The agent is your own Claude Code, run in the background with read-only access to your projects folder so it can check work for itself.

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

Needs Omarchy 4 (Quickshell shell), Python 3.11+, and Claude Code signed in. So far this has only run on its author's machine.

```sh
git clone https://github.com/BennetMC2/omarchy-focus ~/.config/omarchy/plugins/local.focus
omarchy plugin enable local.focus
ln -sf ~/.config/omarchy/plugins/local.focus/focusctl ~/.local/bin/focusctl
omarchy restart shell
```

Then click the Focus icon in the bar. It walks you through the rest, including the one password prompt for system-wide website blocking.

## How it fits together

| File | Role |
|---|---|
| `model.py` | The day: tasks, verdicts, cooling-off, unlock rules, streaks. Every change goes through it. |
| `tools.py` | The agent's tools. Thin wrappers over the model, so the agent cannot do what the rules forbid. |
| `agent.py` | The agent's instructions and its long-running streaming session. |
| `daemon.py` | The service: one loop owning state, blocking, the agent and all clients over a user-only Unix socket. Pushes updates; nothing polls. |
| `mcp.py` | Tool server the agent process talks to; forwards tool calls to the service. |
| `blocking.py` | Parks blocked windows, drives the root helper, connects the browser. |
| `focus.py` | Entry point: service, `focusctl` commands, browser native bridge. |
| `Service.qml`, `FocusOverlay.qml`, `Focus.qml`, `TaskPanel.qml` | Shell service, the card, the bar icon, the panel host. |
| `setup/focus-root-helper` | Root-owned helper: writes only Focus's own browser policy files and a marked block in `/etc/hosts`. |
| `browser/` | Companion extension: redirects blocked sites to a local page. |

State lives in `~/.local/state/local.focus/` (`state.json`, `chat.json`).

## Recovery

`focusctl recover` removes every block and keeps blocking off until the day is started again. If the service is down: `pkexec /usr/local/bin/focus-root-helper recover`.

## Tests

```sh
python3 -m unittest discover -s tests
node --test --test-isolation=none tests/browser.test.cjs
```

The tests run against temporary state with a scripted stand-in for the agent; they never touch real tasks or system blocking.
