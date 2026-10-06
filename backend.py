"""Which model Bouncer talks to, where it runs, and what it can do. Checked, not assumed."""
import json
from pathlib import Path
import threading
import time
import urllib.request

from model import loopback

def describe_claude(settings):
    name = settings.get('model') or 'sonnet'
    info = {'provider': 'claude', 'model': name, 'where': 'remote', 'ok': True, 'tools': True, 'vision': True, 'error': '',
            'label': 'Claude (%s), on Anthropic\'s servers' % name}
    import agent
    if not agent.binary('claude') and not agent.os.environ.get('FOCUS_AGENT_CMD'):
        info.update(ok=False, error='Claude Code is not installed. Install it and sign in, or choose another agent in Settings.')
    return info

def describe_ollama(settings):
    """Ask the server about the model. A local address proves nothing on its own: Ollama also relays cloud models."""
    endpoint, name = settings['endpoint'], settings.get('model') or ''
    here = loopback(endpoint)
    info = {'provider': 'ollama', 'model': name, 'where': 'unknown', 'ok': False, 'tools': False, 'vision': False, 'error': '',
            'label': 'Ollama at %s' % endpoint}
    if not name:
        info['error'] = 'Pick a model for Ollama: type /model followed by its name.'
        return info
    try:
        request = urllib.request.Request(endpoint + '/api/show', data=json.dumps({'model': name}).encode(), headers={'Content-Type': 'application/json'})
        # No proxy and no redirects: the answer has to come from the address the user chose.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=3) as response: shown = json.loads(response.read(2_000_000))
    except Exception as exc:
        info['error'] = 'Ollama is not answering at %s, or it has no model called %s. (%s)' % (endpoint, name, str(exc)[:80])
        return info
    capabilities = shown.get('capabilities') or []
    relayed = bool(shown.get('remote_host') or shown.get('remote_model')) or 'cloud' in name.lower()
    info.update(tools='tools' in capabilities, vision='vision' in capabilities,
                where='remote' if relayed or not here else 'local')
    info['label'] = ('Ollama (%s), on this machine' % name if info['where'] == 'local' else
                     'Ollama (%s), relayed to a remote server' % name if relayed else 'Ollama (%s) at %s, on another machine' % (name, endpoint))
    if not info['tools']: info['error'] = '%s cannot call tools, which Bouncer needs. Pick a model that supports tool calling.' % name
    else: info['ok'] = True
    return info

# Who reads the conversation when OpenCode is the agent: the provider of the chosen model.
OPENCODE_OWNERS = {'openai': "OpenAI's servers", 'anthropic': "Anthropic's servers", 'google': "Google's servers", 'xai': "xAI's servers",
                   'openrouter': "OpenRouter, which passes it to the model's provider", 'opencode': "OpenCode's servers"}

def describe_agent(kind, settings):
    """Codex, Grok or OpenCode: an installed coding agent Bouncer drives inside a jail, with a gate as its only way out."""
    import agent, shutil
    name = settings.get('model') or 'its default model'
    info = {'provider': kind, 'model': settings.get('model') or '', 'where': 'remote', 'ok': True, 'tools': True, 'vision': True, 'error': '',
            'label': ("Grok (%s), on xAI's servers" if kind == 'grok' else "Codex (%s), on OpenAI's servers") % name}
    if kind == 'opencode':
        # Screenshots are not passed through OpenCode yet.
        info.update(vision=False, label='OpenCode')
        try: info['label'] = 'OpenCode (%s), on %s' % (name, OPENCODE_OWNERS[agent.opencode_provider(settings)])
        except ValueError as exc: info.update(ok=False, error=str(exc))
        if not agent.opencode_auth().is_file(): info.update(ok=False, error='Sign in with opencode auth login first.')
    if kind == 'grok':
        info['vision'] = False
        if not (Path.home()/'.grok/auth.json').is_file(): info.update(ok=False, error='Sign in with grok login first.')
    if not agent.binary(kind): info.update(ok=False, error='%s is not installed. Type /provider auto to use the agent Omarchy is set to.' % kind)
    elif not shutil.which('bwrap'): info.update(ok=False, error='%s keeps tools of its own, so Bouncer only runs it inside a sandbox, and bubblewrap (bwrap) is not installed.' % kind)
    return info

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

class Backend:
    """The current answer, refreshed off the service loop so a dead server never stalls it."""
    def __init__(self):
        self.key = None
        self.info = None
        self.at = 0
        self.checking = False

    def signature(self, settings): return (settings['provider'], settings.get('model') or '', settings['endpoint'])

    def describe(self, settings):
        import agent
        key = self.signature(settings)
        kind = settings['provider'] if settings['provider'] == 'ollama' else agent.resolve(settings)
        if kind != 'ollama':
            self.key, self.info = key, describe_claude(settings) if kind == 'claude' else describe_agent(kind, settings)
            self.info['auto'] = settings['provider'] == 'auto'
            # If Omarchy is set to an agent Bouncer cannot drive, say which one it is using instead and why.
            try: preferred = (Path.home()/'.config/omarchy/defaults/agent').read_text().strip()
            except OSError: preferred = ''
            self.info['note'] = ('Omarchy is set to %s, which Bouncer cannot drive yet, so it is using %s.' % (preferred, kind)
                                 if self.info['auto'] and preferred and preferred != kind else '')
            return self.info
        if key != self.key:
            self.key, self.at = key, 0
            self.info = {'provider': 'ollama', 'model': key[1], 'where': 'unknown', 'ok': False, 'tools': False, 'vision': False,
                         'error': 'Checking Ollama…', 'label': 'Ollama at %s' % key[2]}
        if not self.checking and time.time() - self.at > 15:
            self.checking = True
            def work(snapshot=dict(settings), key=key):
                info = describe_ollama(snapshot)
                if key == self.key: self.info, self.at = info, time.time()
                self.checking = False
            threading.Thread(target=work, daemon=True).start()
        return self.info
