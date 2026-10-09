# What's been tested

The original checks below cover version 2.3.0-beta.1 on 5 and 6 October 2026. I've tried to be straight here about what has been run for real and what hasn't.

On 9 October, version 2.3.0-beta.2 changed Grok/OpenCode prompt delivery to standard input. OpenCode 1.18.31 with `openai/gpt-5.6-luna` passed all four live smoke scenarios: task capture, starting the day, reading synthetic evidence and refusing an unsupported claim in hard mode. Grok 1.0.46 accepted the new launch options but reported "Not signed in", so a successful live Grok turn remains unverified for this change. Automated subprocess tests cover complete UTF-8 delivery and check that private history, tasks and messages are absent from backend and bridge process arguments and environment for Grok, OpenCode and Codex.

## Where it's been used

I use Bouncer on my own machine, and it has been installed from scratch and used on a second one. Both are Omarchy 4. That is the whole sample so far, so if it misbehaves on yours, please open an issue.

My setup, for reference: Omarchy 4.0.4, Quickshell 0.3.1, Python 3.14, Node 26, Claude Code 2.1.286, Codex 0.154.0, Grok Build 1.0.46 and OpenCode 1.18.31.

## The agents

Each agent was put through the same four steps with throwaway tasks and a made-up file, well away from my real list: add two tasks without being asked follow-up questions, start the day when told to, read a file and pass the task it proves, and refuse to pass a task on a bare "trust me" in hard mode.

| Agent | Model | How it went | Reply time |
|---|---|---|---|
| Claude Code | haiku | Passed on the second try | 6–9 seconds |
| Codex | gpt-reserve | Passed | 11–17 seconds |
| Grok Build | its default (Grok 4.7 when I looked) | Passed | 9–31 seconds |
| OpenCode | openai/gpt-5.6-luna on a ChatGPT sign-in | Passed | 9–17 seconds |

A few things worth knowing from those runs:

- Haiku's first attempt failed because it read a one-line file containing two sentences as one sentence. I changed the instructions so it counts content and not lines, and it passed after that. It also once suggested I could "just describe" a task in hard mode, though it didn't pass it.
- Codex stopped with a capacity error on its default model. Picking gpt-reserve fixed that.
- With OpenCode on a ChatGPT sign-in, OpenAI refused gpt-5.4 and gpt-5.4-mini even though OpenCode lists them. Bouncer shows you the provider's message when that happens, so try another model.
- I asked OpenCode, from inside the sandbox, to list every tool it had. It listed Bouncer's and nothing else.

Four steps passing once is not a reliability figure. The agent is a judge with opinions, and it will sometimes be wrong about your work in both directions.

## Not tested yet

- **Screenshots with a real agent.** The plumbing has automated tests for Claude and Codex, but I haven't yet done the full capture, preview and send against a live one on this version. Grok and OpenCode have screenshots switched off until I do.
- **OpenCode with anything but OpenAI.** The routes for Anthropic, Google, xAI, OpenRouter and OpenCode's own models are there, and none of them has carried a real request.
- **OpenCode renewing its sign-in mid-reply.** Bouncer copies the renewed sign-in back so your own OpenCode login doesn't go stale. That is covered by an automated test only.
- **Browsers other than Chromium and Brave.** They get the hosts-file block but not the Bouncer blocked page.

## Automated tests

There are 94 Python tests and 6 browser-extension tests, and they run on GitHub for every change on Python 3.11 and 3.13. They cover the rules (modes, waits, timers, carry-over, recovery), what the agent is and isn't allowed to read, the sandbox and network setup for each agent, the browser set-up and clean removal, and the updater.

The card itself is rendered off-screen and its send and retry behaviour checked. A secret scan (Gitleaks) of the whole Git history found nothing on 5 October. That is a scan for leaked keys and nothing more.

## Try an agent yourself

These use a little of your own quota and don't touch your real tasks or blocks:

```sh
python3 dev/agent_smoke.py claude --model haiku --output /tmp/focus-claude.json
python3 dev/agent_smoke.py codex --model gpt-reserve --output /tmp/focus-codex.json
python3 dev/agent_smoke.py grok --output /tmp/focus-grok.json
python3 dev/agent_smoke.py opencode --model openai/gpt-5.6-luna --output /tmp/focus-opencode.json
```
