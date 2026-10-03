"""Which model Focus talks to, where it runs, and what it can do. Checked, not assumed."""
import json
import threading
import time
import urllib.request

from model import loopback

def describe_claude(settings):
    name = settings.get('model') or 'sonnet'
    return {'provider': 'claude', 'model': name, 'where': 'remote', 'ok': True, 'tools': True, 'vision': True, 'error': '',
            'label': 'Claude (%s), on Anthropic\'s servers' % name}

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
    if not info['tools']: info['error'] = '%s cannot call tools, which Focus needs. Pick a model that supports tool calling.' % name
    else: info['ok'] = True
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
        key = self.signature(settings)
        if settings['provider'] == 'claude':
            self.key, self.info = key, describe_claude(settings)
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
