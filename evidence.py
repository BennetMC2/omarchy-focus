"""Bounded evidence access for the agent: files, search, git and links.

Everything the agent may look at goes through here. The limits are enforced in this
code and by an OS sandbox, never by asking the model to behave.
"""
import fnmatch
import http.client
import ipaddress
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
from urllib.parse import urlsplit

class Refused(ValueError):
    """The request is outside what the user has allowed."""

# Never shown, even inside an approved folder. Matched against every part of the path, case-insensitively.
SECRET_NAMES = ('.env', '.env.*', '*.env', '.envrc', '*.pem', '*.key', '*.p12', '*.pfx', '*.kdbx', '*.keystore', '*.jks',
                'id_rsa*', 'id_dsa*', 'id_ecdsa*', 'id_ed25519*', '.netrc', '.npmrc', '.pypirc', '.htpasswd', '.git-credentials',
                'credentials', 'credentials.*', '*credentials*.json', 'secrets', 'secrets.*', '*.secret', '*secret*.json', '*secret*.y*ml',
                '.ssh', '.gnupg', '.aws', '.azure', '.kube', '.docker', 'service-account*.json', '*.tfstate', '*.tfvars')
SKIP_DIRS = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', 'target', 'dist', 'build', '.cache', '.next'}
MAX_TEXT = 60_000
MAX_FILE = 2_000_000

def is_secret(path):
    parts = [part.lower() for part in Path(path).parts]
    if any(fnmatch.fnmatch(part, pattern) for part in parts for pattern in SECRET_NAMES): return True
    # Repository configuration can hold tokens in remote URLs and credential helpers.
    return len(parts) >= 2 and parts[-2] == '.git' and parts[-1] == 'config'

def approved(settings):
    found = []
    for root in settings.get('roots') or []:
        try: found.append(Path(root).resolve(strict=True))
        except OSError: continue
    return found

def resolve(path, roots, kind=None):
    """An existing path inside an approved folder, after following every symlink. Refuses anything else."""
    if not roots: raise Refused('No folder has been approved yet. Ask the user with request_folder.')
    raw = Path(str(path or '.')).expanduser()
    candidates = [raw] if raw.is_absolute() else [root/raw for root in roots]
    for candidate in candidates:
        try: real = candidate.resolve(strict=True)
        except OSError: continue
        root = next((r for r in roots if real == r or r in real.parents), None)
        if root is None: continue
        if is_secret(real.relative_to(root)): raise Refused('That path is on the never-read list (credentials and keys).')
        if kind == 'dir' and not real.is_dir(): raise Refused('That is not a folder.')
        if kind == 'file' and not real.is_file(): raise Refused('That is not a file.')
        return real, root
    raise Refused('That path does not exist inside an approved folder (%s).' % ', '.join(str(r) for r in roots))

def clip(text, limit=MAX_TEXT):
    return text if len(text) <= limit else text[:limit] + '\n… cut at %d characters' % limit

def list_files(path, roots):
    folder, root = resolve(path, roots, 'dir')
    rows = []
    for entry in sorted(folder.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))[:300]:
        if is_secret(Path(entry.name)): continue
        try: rows.append(entry.name + '/' if entry.is_dir() else '%s  (%d bytes)' % (entry.name, entry.stat().st_size))
        except OSError: continue
    return '%s\n%s' % (folder, '\n'.join(rows) or '(empty)')

def read_file(path, roots, start=1, lines=400):
    target, _ = resolve(path, roots, 'file')
    if target.stat().st_size > MAX_FILE: raise Refused('That file is too large to read (over 2 MB).')
    data = target.read_bytes()
    if b'\0' in data[:8192]: raise Refused('That is a binary file.')
    text = data.decode('utf-8', errors='replace').splitlines()
    start = max(1, int(start or 1)); count = max(1, min(1000, int(lines or 400)))
    chunk = text[start - 1:start - 1 + count]
    return clip('%s (lines %d-%d of %d)\n%s' % (target, start, start + len(chunk) - 1, len(text), '\n'.join('%5d  %s' % (start + i, line) for i, line in enumerate(chunk))))

def search_files(query, path, roots, glob=''):
    folder, root = resolve(path, roots, 'dir')
    if not query or len(str(query)) > 200: raise Refused('Give something to search for, up to 200 characters.')
    try: pattern = re.compile(str(query), re.IGNORECASE)
    except re.error: pattern = re.compile(re.escape(str(query)), re.IGNORECASE)
    hits, scanned = [], 0
    for current, folders, files in os.walk(folder, followlinks=False):
        folders[:] = sorted(d for d in folders if d not in SKIP_DIRS and not is_secret(Path(d)))
        for name in sorted(files):
            if is_secret(Path(name)) or (glob and not fnmatch.fnmatch(name, glob)): continue
            scanned += 1
            if scanned > 5000 or len(hits) >= 100: return clip('\n'.join(hits) + '\n… search stopped at its limit')
            try:
                # A symlink inside the folder may point anywhere; only follow it if it stays inside.
                real, _ = resolve(Path(current)/name, roots, 'file')
                if real.stat().st_size > MAX_FILE: continue
                data = real.read_bytes()
            except (Refused, OSError): continue
            if b'\0' in data[:8192]: continue
            for number, line in enumerate(data.decode('utf-8', errors='replace').splitlines(), 1):
                if pattern.search(line):
                    hits.append('%s:%d: %s' % (Path(current, name).relative_to(folder), number, line.strip()[:240]))
                    if len(hits) >= 100: break
    return clip('\n'.join(hits)) if hits else 'No matches.'

# --- git -------------------------------------------------------------------------------------------

REF = re.compile(r'[A-Za-z0-9_][A-Za-z0-9._/~^@{}-]{0,119}')
GIT_ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/tmp', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_SYSTEM': '/dev/null',
           'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0', 'GIT_PAGER': 'cat', 'PAGER': 'cat', 'GIT_ATTR_NOSYSTEM': '1', 'LC_ALL': 'C.UTF-8'}
# Command-line configuration outranks the repository's own, so these hold whatever .git/config says.
GIT_CONFIG = ('safe.directory=*', 'core.fsmonitor=false', 'core.hooksPath=/dev/null', 'core.pager=cat', 'diff.external=', 'core.sshCommand=false',
              'protocol.allow=never', 'credential.helper=', 'core.askPass=', 'gc.auto=0', 'maintenance.auto=false', 'submodule.recurse=false')
SECRET_PATHSPECS = [':(exclude,glob,icase)**/.env', ':(exclude,glob,icase)**/.env.*', ':(exclude,glob,icase)**/*.pem', ':(exclude,glob,icase)**/*.key',
                    ':(exclude,glob,icase)**/id_rsa*', ':(exclude,glob,icase)**/id_ed25519*', ':(exclude,glob,icase)**/.netrc', ':(exclude,glob,icase)**/.npmrc',
                    ':(exclude,glob,icase)**/*credentials*', ':(exclude,glob,icase)**/*secret*', ':(exclude,glob,icase)**/*.tfstate', ':(exclude,glob,icase)**/*.tfvars']

def sandbox(root):
    """Read-only view of one approved folder, no network, nothing else of the home directory. Callbacks that slip through can do no harm."""
    bwrap = shutil.which('bwrap')
    if not bwrap: raise Refused('Git evidence needs bubblewrap (the bwrap command), which is not installed.')
    command = [bwrap, '--unshare-all', '--die-with-parent', '--new-session', '--clearenv', '--ro-bind', '/usr', '/usr',
               '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
               '--dev', '/dev', '--proc', '/proc', '--tmpfs', '/tmp', '--ro-bind', str(root), str(root)]
    for key, value in GIT_ENV.items(): command += ['--setenv', key, value]
    return command

def git(repo, what, roots, ref='', path='', limit=20):
    """One of four fixed read-only views of a repository. No option or command string is ever taken from the caller."""
    folder, root = resolve(repo, roots, 'dir')
    if what not in ('status', 'log', 'diff', 'show'): raise Refused('Choose status, log, diff or show.')
    refs = []
    for part in str(ref or '').split('..'):
        if not part: continue
        if not REF.fullmatch(part): raise Refused('That is not a plain commit, branch or tag name.')
        refs.append(part)
    if len(refs) > 2: raise Refused('Compare at most two revisions.')
    target = '.'
    if path:
        inside, _ = resolve(folder/str(path) if not Path(str(path)).is_absolute() else path, roots)
        if folder != inside and folder not in inside.parents: raise Refused('That path is outside the repository folder.')
        target = str(inside.relative_to(folder)) or '.'
    limit = max(1, min(200, int(limit or 20)))
    if what == 'status': args = ['status', '--porcelain=v1', '--branch', '--untracked-files=normal']
    elif what == 'log': args = ['log', '--no-color', '--date=iso', '--format=%h %ad %an: %s', '-n', str(limit)] + refs[:1]
    elif what == 'diff': args = ['diff', '--no-color', '--no-ext-diff', '--no-textconv', '--stat', '--patch'] + (['..'.join(refs)] if refs else [])
    else: args = ['show', '--no-color', '--no-ext-diff', '--no-textconv', '--stat', '--patch', '--format=%h %ad %an%n%s%n%b', '--date=iso', refs[0] if refs else 'HEAD']
    command = sandbox(root) + ['--chdir', str(folder), 'git', '--no-pager']
    for setting in GIT_CONFIG: command += ['-c', setting]
    command += args + ['--', target] + SECRET_PATHSPECS
    try: result = subprocess.run(command, capture_output=True, text=True, errors='replace', timeout=20, stdin=subprocess.DEVNULL, env={'PATH': '/usr/bin:/bin'})
    except subprocess.TimeoutExpired: raise Refused('Git took too long.')
    if result.returncode: raise Refused('Git refused: ' + (result.stderr.strip().splitlines() or ['unknown error'])[-1][:200])
    return clip(result.stdout) or '(nothing to show)'

# --- links -----------------------------------------------------------------------------------------

def public_address(host, port):
    """One address for the host that is on the public internet. Loopback, private and link-local targets are refused."""
    try: found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError: raise Refused('That address does not resolve.')
    for info in found:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global or address.is_multicast: raise Refused('That link points at a private or local address.')
    return found[0][4][0]

def check_url(url):
    parts = urlsplit(str(url or '').strip())
    if parts.scheme not in ('http', 'https') or not parts.hostname: raise Refused('Links must be http or https.')
    if parts.username or parts.password: raise Refused('Links must not carry a username or password.')
    return parts

class PinnedHTTPS(http.client.HTTPSConnection):
    """Connects to the address that was checked, so a second DNS answer cannot redirect the request."""
    def __init__(self, host, address, port):
        super().__init__(host, port, timeout=10, context=ssl.create_default_context())
        self.address = address
    def connect(self):
        raw = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)

class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, address, port):
        super().__init__(host, port, timeout=10)
        self.address = address
    def connect(self): self.sock = socket.create_connection((self.address, self.port), self.timeout)

def fetch(url, allowed):
    """Fetch a link the user approved. Redirects are followed only within the same site, and each hop is checked again."""
    parts = check_url(url)
    if not allowed(parts.geturl()): raise Refused('The user has not approved that link.')
    for _ in range(4):
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        address = public_address(parts.hostname, port)
        connection = (PinnedHTTPS if parts.scheme == 'https' else PinnedHTTP)(parts.hostname, address, port)
        try:
            connection.request('GET', (parts.path or '/') + ('?' + parts.query if parts.query else ''), headers={'User-Agent': 'omarchy-focus', 'Accept': 'text/*'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                following = check_url(response.getheader('Location') if '://' in (response.getheader('Location') or '') else
                                      '%s://%s%s' % (parts.scheme, parts.netloc, response.getheader('Location') or '/'))
                if following.hostname != parts.hostname: raise Refused('That link redirects to a different site (%s), which was not approved.' % following.hostname)
                parts = following
                continue
            body = response.read(400_000)
            kind = response.getheader('Content-Type') or ''
        except (OSError, http.client.HTTPException) as exc: raise Refused('Could not fetch it: ' + str(exc)[:120])
        finally: connection.close()
        if not kind.startswith(('text/', 'application/json', 'application/xml', 'application/xhtml')): return 'HTTP %d, %s, %d bytes (not text)' % (response.status, kind or 'unknown type', len(body))
        text = body.decode('utf-8', errors='replace')
        if 'html' in kind:
            text = re.sub(r'(?is)<(script|style|noscript)\b.*?</\1>', ' ', text)
            text = re.sub(r'(?s)<[^>]+>', ' ', text)
            text = re.sub(r'[ \t\r\f]+', ' ', re.sub(r'\n\s*\n+', '\n', text))
        return clip('HTTP %d from %s\n%s' % (response.status, parts.hostname, text.strip()), 20_000)
    raise Refused('Too many redirects.')
