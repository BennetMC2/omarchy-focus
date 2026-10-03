"""What Focus does to the machine: parks blocked windows, drives the root helper, wires up the browser."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

import common
from common import read, write, run

HELPER = '/usr/local/bin/focus-root-helper'
PARKING = 'special:omarchy-focus'
NATIVE_HOST = 'local.omarchy.focus'
# name, flags file, native-messaging host folder (both relative to the home directory)
BROWSERS = (('chromium', '.config/chromium-flags.conf', '.config/chromium/NativeMessagingHosts'),
            ('brave', '.config/brave-flags.conf', '.config/BraveSoftware/Brave-Browser/NativeMessagingHosts'))

def clients(): return json.loads(run(['hyprctl','-j','clients']))

def dispatch(address, workspace=None, pin=False):
    if not re.fullmatch(r'0x[0-9a-fA-F]+', address): raise ValueError('Invalid window address.')
    selector = json.dumps('address:' + address)
    lua = 'hl.dsp.window.pin({window=%s})' % selector if pin else 'hl.dsp.window.move({window=%s,workspace=%s,follow=false})' % (selector, json.dumps(workspace))
    if run(['hyprctl','dispatch',lua]).strip() != 'ok': raise RuntimeError('Window move failed.')

def matches(client, settings):
    classes = [str(client.get(k, '')).lower() for k in ('class','initialClass')]
    selected = {a.lower() for a in settings['apps']}
    if selected.intersection(classes): return True
    for cls in classes:
        m = re.match(r'^(?:chrome|chromium|brave)-(.+?)__-', cls)
        if m:
            host = m[1].split('_')[0]
            if any(host == s or host.endswith('.' + s) for s in settings['sites']): return True
    return False

def open_apps():
    return sorted({c.get('initialClass') or c.get('class') for c in clients()} - {None, ''})

def installed_apps():
    """Installed desktop apps as (name, window class or site). Web apps are named by the site they open."""
    found = {}
    for folder in (Path('/usr/share/applications'), Path.home()/'.local/share/applications'):
        for entry in sorted(folder.glob('*.desktop')):
            try: text = entry.read_text(errors='replace')
            except OSError: continue
            fields = dict(line.split('=', 1) for line in text.splitlines() if '=' in line and not line.startswith('#'))
            if fields.get('NoDisplay', '').lower() == 'true' or fields.get('Type', 'Application') != 'Application' or not fields.get('Name'): continue
            site = re.search(r'https?://([a-z0-9.-]+)', fields.get('Exec', ''))
            found[fields['Name']] = 'site ' + site[1].removeprefix('www.') if site else fields.get('StartupWMClass') or entry.stem
    return sorted(found.items())

def extension_id(path):
    # Chromium derives an unpacked extension's id from its absolute path.
    return ''.join(chr(97 + int(c, 16)) for c in hashlib.sha256(str(path).encode()).hexdigest()[:32])

def browser_status():
    extension = str(common.PLUGIN/'browser')
    def has(path, needle):
        try: return needle in (Path.home()/path).read_text()
        except OSError: return False
    return {'extension': any(has(flags, extension) for _, flags, _ in BROWSERS),
            'host': any(has(hosts + '/' + NATIVE_HOST + '.json', extension_id(extension)) for _, _, hosts in BROWSERS)}

def browser_connect():
    """Load the companion extension through the browser flags file and register its native host."""
    extension = str(common.PLUGIN/'browser')
    done = []
    for name, flags, hosts in BROWSERS:
        flags, hosts = Path.home()/flags, Path.home()/hosts
        if not flags.exists() and not shutil.which(name): continue
        lines = flags.read_text().splitlines() if flags.exists() else []
        if not any(extension in line for line in lines):
            if flags.exists() and not flags.with_name(flags.name + '.before-focus').exists(): shutil.copy2(flags, flags.with_name(flags.name + '.before-focus'))
            index = next((i for i, line in enumerate(lines) if line.startswith('--load-extension=')), None)
            if index is None: lines.append('--load-extension=' + extension)
            else: lines[index] += ',' + extension
            flags.write_text('\n'.join(lines) + '\n')
        hosts.mkdir(parents=True, exist_ok=True)
        (hosts/(NATIVE_HOST + '.json')).write_text(json.dumps({'name': NATIVE_HOST, 'description': 'Local Focus state bridge', 'path': str(common.PLUGIN/'focus.py'),
            'type': 'stdio', 'allowed_origins': ['chrome-extension://' + extension_id(extension) + '/']}, indent=2) + '\n')
        done.append(name)
    if not done: raise ValueError('No Chromium or Brave installation found.')
    return done

def screenshot():
    """Capture the focused monitor for the agent to look at. Keeps the last few."""
    folder = common.STATE/'proof'
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    monitor = next((m['name'] for m in json.loads(run(['hyprctl', '-j', 'monitors'])) if m.get('focused')), None)
    path = folder/('screen-%d.png' % int(time.time()))
    run(['grim'] + (['-o', monitor] if monitor else []) + [str(path)], timeout=10)
    for old in sorted(folder.glob('screen-*.png'))[:-5]: old.unlink()
    return str(path)

class Borders:
    """Turns the active window border the theme's red while locked, and puts it back exactly as it was."""
    def __init__(self):
        self.saved = common.STATE/'borders.json'
        self.on = False
        # A leftover file means we went down while the border was red.
        if self.saved.exists(): self.set(False)

    def lua(self, colours, angle):
        return 'hl.config({ general = { col = { active_border = { colors = { %s }, angle = %d } } } })' % (', '.join(json.dumps(c) for c in colours), angle)

    def set(self, on):
        # Tests and scratch runs never touch the real desktop.
        if not common.TOASTS or (on == self.on and not (not on and self.saved.exists())): return
        try:
            if on:
                # "gradient data: ff7aa2f7 ff00ff99 45deg": remember it before replacing it.
                parts = run(['hyprctl', 'getoption', 'general:col.active_border']).splitlines()[0].split(':', 1)[1].split()
                colours = ['rgba(%s%s)' % (c[2:], c[:2]) for c in parts if re.fullmatch(r'[0-9a-fA-F]{8}', c)]
                angle = next((int(p[:-3]) for p in parts if re.fullmatch(r'\d+deg', p)), 0)
                if not colours: return
                if not self.saved.exists(): write(self.saved, {'colours': colours, 'angle': angle})
                run(['hyprctl', 'eval', self.lua(['rgba(%sff)' % common.colour('red', '#f7768e').lstrip('#')], 0)])
            else:
                original = read(self.saved)
                if original.get('colours'): run(['hyprctl', 'eval', self.lua(original['colours'], original.get('angle', 0))])
                self.saved.unlink(missing_ok=True)
            self.on = on
        except Exception: pass

class Runtime:
    def __init__(self):
        self.session = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
        old = read(common.STATE/'held.json')
        self.held = old.get('windows', {}) if old.get('session') == self.session else {}
        self.desired = None
        self.policy_at = 0
        self.error = ''
        self.blocked_at = 0
        self.blocked_name = ''
        self.last_guard = 0
        self.last_locked = None

    def save_held(self): write(common.STATE/'held.json', {'session': self.session, 'windows': self.held})

    def restore(self, window_map, selected=None):
        for address, origin in list(self.held.items()):
            c = window_map.get(address)
            if c and c.get('pid') == origin['pid']:
                if selected is not None and matches(c, selected): continue
                dispatch(address, origin['workspace'])
                if origin.get('pinned') and not c.get('pinned'): dispatch(address, pin=True)
            del self.held[address]
            self.save_held()

    def reconcile(self, state, force=False, quiet=False):
        now = time.time()
        errors = []
        changed = self.last_locked != state['locked']
        if force or changed or now - self.last_guard > 5:
            self.last_guard = now
            try:
                windows = clients()
                self.restore({c['address']: c for c in windows}, state['settings'] if state['locked'] else None)
                if state['locked']:
                    for c in windows:
                        if not matches(c, state['settings']): continue
                        a = c['address']
                        if c['workspace']['name'] == PARKING: continue
                        if a not in self.held:
                            self.held[a] = {'pid': c['pid'], 'workspace': c['workspace']['name'], 'pinned': c.get('pinned',False)}
                            self.save_held()
                        if c.get('pinned'): dispatch(a, pin=True)
                        dispatch(a, PARKING)
                        # Announce only a fresh attempt: not windows swept up as the lock begins, nor while they are talking to Focus.
                        if now - self.blocked_at > 2 and not changed and not quiet:
                            self.blocked_at = now
                            self.blocked_name = c.get('initialClass') or c.get('class') or 'App'
            except Exception as exc: errors.append('Apps: ' + str(exc))
        desired = {'locked': state['locked'], 'sites': state['settings']['sites'], 'hosts': state['settings']['hosts']}
        if Path(HELPER).exists():
            if desired != self.desired or now - self.policy_at > 30:
                try:
                    run(['pkexec', HELPER, 'apply'], input=json.dumps(desired), timeout=8)
                    self.desired = desired
                    self.policy_at = now
                except Exception as exc:
                    errors.append('System blocking: ' + str(exc))
                    self.policy_at = now
                    # Do not repeatedly launch authentication dialogs.
                    self.desired = desired
        self.last_locked = state['locked']
        if errors: self.error = ' · '.join(errors)
        elif force or changed: self.error = ''

    def enrich(self, state):
        return {**state, 'theme': common.theme(), 'held': len(self.held), 'blockingError': self.error,
                'blockedAt': self.blocked_at, 'blockedName': self.blocked_name,
                'helperInstalled': Path(HELPER).exists(), 'browser': browser_status()}
