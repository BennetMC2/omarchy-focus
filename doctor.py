"""Read-only installation checks. Never starts an agent or changes blocking."""
import shutil
from pathlib import Path
import agent
import blocking

def checks(settings):
    kind = agent.resolve(settings)
    result = []
    def add(name, ok, detail, required=True):
        result.append({'name': name, 'ok': bool(ok), 'required': required, 'detail': detail})
    add('Agent', bool(agent.binary(kind)), kind + ': installed' if agent.binary(kind) else 'Install and sign in to ' + kind + '.')
    add('Sandbox', shutil.which('bwrap'), 'Install bubblewrap (bwrap). Git evidence, Codex, Grok and OpenCode need it.',
        kind in ('codex', 'grok', 'opencode'))
    for command in ('hyprctl', 'pkexec'):
        add(command, shutil.which(command), 'Required for desktop blocking and helper setup.')
    if kind == 'grok':
        add('Stored login', (Path.home()/'.grok/auth.json').is_file(), 'Run grok login. A stored login still needs a live reply to confirm it works.')
    elif kind == 'opencode':
        add('Stored login', agent.opencode_auth().is_file(), 'Run opencode auth login. A stored login still needs a live reply to confirm it works.')
    elif kind == 'codex':
        add('Stored login', (Path.home()/'.codex/auth.json').is_file(), 'Run codex login. A stored login still needs a live reply to confirm it works.')
    else:
        add('Stored login', (Path.home()/'.claude/.credentials.json').is_file(), 'Open claude and sign in. Other credential stores may also work.', False)
    add('Browser', any(shutil.which(name) for name, _, _ in blocking.BROWSERS), 'The companion extension supports Chromium and Brave.', False)
    add('System helper', Path(blocking.HELPER).is_file() and not blocking.helper_stale(),
        'Out of date: refresh it from the card.' if blocking.helper_stale() else 'Installed during first-run setup.', False)
    for command in ('grim', 'wl-paste'):
        add(command, shutil.which(command), 'Optional: needed for screenshots or pasted images.', False)
    return result

def require_ready(settings):
    missing = [c for c in checks(settings) if c['required'] and not c['ok']]
    if missing: raise ValueError('Setup needs attention: ' + ' '.join(c['detail'] for c in missing))
