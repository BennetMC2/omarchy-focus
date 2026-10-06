# Working with Bouncer from another agent

Bouncer has its own agent, which plans the day, reviews tasks and enforces the rules. If you are a different agent (a coding session in some project) and the user tells you a Bouncer task is finished, do not judge it yourself. Tell Bouncer, with the evidence:

```sh
focusctl say "Finished the importer rewrite: see the last three commits in ~/Projects/importer, tests pass."
```

It prints Bouncer's reply. Bouncer inspects the evidence itself and records the verdict. `focusctl list --json` shows the tasks and their verdicts.

`focusctl verdict <id> --pass|--fail --note '<one line>'` still exists for when no Bouncer agent is available. Those verdicts are marked "external": they unlock, but never count toward a streak. Never edit the state files or use recovery to manufacture a pass.
