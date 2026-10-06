"""Notices when a newer Bouncer has been published, and installs it when the user says so. Nothing updates on its own."""
import json
import os
import shutil
import subprocess
import threading
import time

import common

INTERVAL = 6 * 3600
# The first look waits a minute, so starting the desktop is never held up by the network.
FIRST = 60

def git(*args, timeout=10):
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_SSH_COMMAND': os.environ.get('GIT_SSH_COMMAND') or 'ssh -oBatchMode=yes'}
    return common.run(['git', '-C', str(common.PLUGIN)] + list(args), timeout=timeout, env=env).strip()

def managed():
    """Installed with omarchy plugin add, so there is somewhere to update from."""
    return (common.PLUGIN/'.git').exists()

def current():
    try: return str(common.read(common.PLUGIN/'manifest.json').get('version') or '')
    except ValueError: return ''

def check():
    """Ask where this copy was installed from whether it has moved on. Fetches the new commits; changes no files."""
    if not managed(): raise ValueError('This copy was not installed with omarchy plugin add, so it cannot update itself.')
    git('fetch', '--quiet', 'origin', 'HEAD', timeout=45)
    changes = int(git('rev-list', '--count', 'HEAD..FETCH_HEAD') or 0)
    version = ''
    if changes:
        try: version = str(json.loads(git('show', 'FETCH_HEAD:manifest.json')).get('version') or '')
        except (RuntimeError, ValueError): pass
    return {'available': changes > 0, 'version': version, 'changes': changes}

def install():
    """Omarchy's own updater does the work: fast-forward only, validated, and rolled back if the new copy is not a valid plugin."""
    if not managed(): raise ValueError('This copy was not installed with omarchy plugin add, so it cannot update itself.')
    try: common.run(['omarchy', 'plugin', 'update', common.PLUGIN.name, '--yes'], timeout=120, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired: raise RuntimeError('The update took too long.')

def restart():
    """Load the new code: the shell restarts and brings the service back with it. False if that has to be done by hand."""
    program = shutil.which('omarchy-restart-shell')
    if not program: return False
    # Its own session, so it outlives the service it is about to replace.
    subprocess.Popen([program], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return True

class Watcher:
    """The current answer, looked up off the service loop so a slow network never stalls it."""
    def __init__(self):
        self.info = {'available': False, 'version': '', 'changes': 0}
        self.managed, self.current = managed(), current()
        self.at = time.time() - INTERVAL + FIRST
        self.busy = self.error = ''
        self.checked = False

    def public(self):
        return {**self.info, 'current': self.current, 'managed': self.managed, 'busy': self.busy, 'error': self.error, 'checked': self.checked}

    def start(self, kind, work, done=None):
        if self.busy: return False
        self.busy = kind
        def run():
            error = ''
            try: work()
            except Exception as exc: error = common.one_line(exc, 200) or 'failed'
            self.error, self.busy = error, ''
            if done: done(error)
        threading.Thread(target=run, daemon=True).start()
        return True

    def look(self):
        def work(): self.info, self.checked = check(), True
        self.at = time.time()
        return self.start('checking', work)

    def poll(self, now, enabled):
        # Tests and scratch runs never reach for the network.
        if enabled and self.managed and common.TOASTS and now - self.at > INTERVAL: self.look()

    def install(self, done): return self.start('installing', install, done)
