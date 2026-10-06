# Security

If you find a security problem, please report it privately through the Security tab on this repository ("Report a vulnerability"). Please don't post exploit details or credentials in a public issue.

A few things that help when judging a report:

- Bouncer changes your browser policies and `/etc/hosts` through one small root-owned helper. Installing and removing that helper are the only other things that ask for root.
- The agent can only look at what you approve, through Bouncer's own tools. Codex, Grok and OpenCode also run inside a sandbox.
- Bouncer is there to keep you honest with yourself on a machine you control. Getting around it as the owner of that machine is expected, and isn't a vulnerability.

The README's Privacy section says what stays on your machine and what goes to a model provider.
