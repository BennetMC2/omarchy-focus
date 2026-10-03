"""Paths and small helpers shared by the Focus service, CLI and tool server. Standard library only."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tomllib

STATE = Path(os.environ.get('FOCUS_STATE_HOME') or Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'local.focus')
SOCKET = STATE/'control.sock'
PLUGIN = Path(__file__).resolve().parent
# Tests and scratch runs set FOCUS_STATE_HOME; they must not raise desktop toasts.
TOASTS = 'FOCUS_STATE_HOME' not in os.environ

def read(path, default=None):
    try: return json.loads(path.read_text())
    except FileNotFoundError: return {} if default is None else default

def write(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    tmp.chmod(0o600)
    with tmp.open('rb') as f: os.fsync(f.fileno())
    tmp.replace(path)

def run(args, **kwargs):
    r = subprocess.run(args, capture_output=True, text=True, timeout=kwargs.pop('timeout', 5), **kwargs)
    if r.returncode: raise RuntimeError((r.stderr or r.stdout or 'Command failed').strip()[:500])
    return r.stdout

def one_line(value, limit=500):
    return ' '.join(str(value or '').split())[:limit]

def request(command, timeout=15):
    """One command, one reply. Returns the whole reply; raises ValueError on a refused command."""
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(timeout)
        sock.connect(str(SOCKET))
        sock.sendall(json.dumps(command).encode() + b'\n')
        with sock.makefile('rb') as stream: reply = json.loads(stream.readline(4_000_000))
    if not reply['ok']: raise ValueError(reply['error'])
    return reply

def rpc(command):
    return request(command)['state']

def theme():
    for p in [Path.home()/'.config/omarchy/current/theme/colors.toml', Path.home()/'.local/state/omarchy/current/theme/colors.toml']:
        try:
            values = tomllib.loads(p.read_text())
            return {k: values[k] for k in ('background','foreground','accent','muted') if re.fullmatch(r'#[a-fA-F0-9]{6}', str(values.get(k, '')))}
        except (OSError, ValueError): pass
    return {}

def colour(name, fallback):
    for p in [Path.home()/'.config/omarchy/current/theme/colors.toml', Path.home()/'.local/state/omarchy/current/theme/colors.toml']:
        try:
            value = str(tomllib.loads(p.read_text()).get(name, ''))
            if re.fullmatch(r'#[a-fA-F0-9]{6}', value): return value
        except (OSError, ValueError): pass
    return fallback

def sound(name):
    if not TOASTS: return
    try: subprocess.Popen(['pw-play', '/usr/share/sounds/freedesktop/stereo/' + name + '.oga'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError: pass

def toast(headline, body=''):
    if not TOASTS: return
    try: subprocess.Popen(['omarchy-notification-send', '-g', '󰄬', headline, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError: pass
