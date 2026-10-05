# What has been tested

Release candidate: 2.3.0-beta.1. Local checks: 5 October 2026.

The supported providers for this beta are Claude Code, Codex (OpenAI), and Grok Build. Gemini is deferred. Older experimental Ollama code remains for compatibility, but it is not part of the supported release.

## Live providers

Each run used a temporary Focus state directory, synthetic tasks, and a synthetic evidence file. No real tasks or desktop blocks were changed. The test used the actual session adapters, MCP server, task model, and evidence tools.

| Agent | Model | Result | Observed reply times |
|---|---|---|---|
| Claude Code | haiku | Four scenarios passed on the retry | 6–9 seconds |
| Codex | gpt-reserve | Four scenarios passed | 11–17 seconds |
| Grok Build 1.0.46 | CLI default (Grok 4.7 in the earlier probe) | Four scenarios passed | 9–31 seconds |

The scenarios were: capture two tasks without planning questions; start on request; read a file and pass the completed task; refuse a bare claim in hard mode.

These are smoke tests, not reliability percentages. The first Haiku run misread a one-line, two-sentence file as one sentence. The review instruction now distinguishes line counts from content counts; the retry fixture also put each sentence on its own line. The original Codex default-model run stopped on a provider-capacity error. Selecting gpt-reserve passed the same scenarios.

Haiku also suggested a verbal account as one possible next step in hard mode, although it did not record a pass. Model judgment and wording still need broader testing. Do not treat an agent verdict as a guarantee that work is correct.

Grok screenshot review is disabled until tested. Its file-based review, login reuse, isolated profile, tool calls, and provider-only network route have been exercised. Claude/Codex screenshot transport has automated coverage; a fresh live screenshot-consent test is still on the release checklist.

Reproduce a live check (uses account quota):

```sh
python3 dev/agent_smoke.py claude --model haiku --output /tmp/focus-claude.json
python3 dev/agent_smoke.py codex --model gpt-reserve --output /tmp/focus-codex.json
python3 dev/agent_smoke.py grok --output /tmp/focus-grok.json
```

Full local results and runtime versions are in [validation.md](validation.md).

## Automated and UI coverage

- Task state, review rules, cooling-off, timers and recovery.
- Atomic batches; rejected batches leave existing tasks intact.
- Capture receipts survive restart and prevent duplicate retries.
- Provider selection, Grok stream parsing, sandbox configuration and profile cleanup.
- File/path/credential exclusions, Git callback and write guards, URL boundaries, and consent.
- Fresh browser configuration, removal, and preservation of unrelated flags and extensions.
- Six mocked browser-extension tests.
- Actual QML card rendered offscreen, including a narrow Settings view.
- Actual card submission handlers checked for disconnected input, refused input, retry identity, multiline capture and acknowledgement.
- Plugin manifest validation.

CI has been added for Python 3.11/3.13 and Node 24. It has not run on GitHub yet.

## Still needs a separate desktop

A fresh Omarchy installation must exercise the real password prompt, browser restart, blocked navigation, parked-window restoration, upgrade, and full uninstall. Temporary-home tests cover file handling, not that entire desktop lifecycle.

This work did not start a clean VM or change the author's live blocking state to simulate one. There is no claim of multi-machine validation yet.
