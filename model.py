"""Local Focus state machine. All mutations are serialized by the service."""
import copy
import hashlib
import json
import datetime as dt
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit
import re
import secrets
import string
import uuid

DEFAULTS = {'reset': '04:00', 'mode': 'all', 'minutes': 15, 'sites': [], 'apps': [], 'hosts': True,
            'strictness': 'standard', 'planning': 'quick', 'borders': True, 'strip': True, 'sound': False, 'updates': True,
            # Where the agent runs, and the folders it may read. Only the user changes these, never the agent.
            # provider "auto" follows the agent chosen for Omarchy itself (omarchy default agent).
            'provider': 'auto', 'model': '', 'endpoint': 'http://127.0.0.1:11434', 'roots': []}
PROVIDERS = ('auto', 'claude', 'codex', 'grok', 'opencode', 'ollama')

def endpoint(value):
    """A plain http(s) address for a model server: no credentials, no query, nothing surprising."""
    parts = urlsplit(str(value or '').strip())
    if parts.scheme not in ('http', 'https') or not parts.hostname: raise ValueError('The endpoint must be an http or https address.')
    if parts.username or parts.password: raise ValueError('Do not put credentials in the endpoint address.')
    if parts.query or parts.fragment or parts.path not in ('', '/'): raise ValueError('Give just the server address, such as http://127.0.0.1:11434.')
    return '%s://%s' % (parts.scheme, parts.netloc)

def loopback(value):
    host = urlsplit(value).hostname or ''
    if host == 'localhost': return True
    try: return ipaddress.ip_address(host).is_loopback
    except ValueError: return False

def folder(value):
    path = Path(str(value or '')).expanduser()
    if not path.is_absolute(): raise ValueError('Give the full path of the folder.')
    try: real = path.resolve(strict=True)
    except OSError: raise ValueError('That folder does not exist.')
    if not real.is_dir(): raise ValueError('That is not a folder.')
    if real == Path(real.anchor) or real == Path.home().resolve() or real in Path.home().resolve().parents:
        raise ValueError('Pick a folder inside your home directory, not all of it.')
    return str(real)
# How much proof a pass takes and how far the rules bend, from loosest to tightest.
LEVELS = ('honor', 'standard', 'hard', 'lockdown')

def task(text, main=False, check=''):
    text = clean(text)
    return {'id': uuid.uuid4().hex[:12], 'text': text, 'check': clean(check) if check else '', 'status': 'open', 'main': main,
            'verdict': None, 'note': '', 'revision': 1, 'verdicts': [], 'credited': False}

def clean(value):
    if not isinstance(value, str) or not value.strip() or '\n' in value or '\r' in value or len(value) > 500:
        raise ValueError('Use one line, 1–500 characters.')
    return value.strip()

def domain(value):
    value = value.strip().lower().removeprefix('https://').removeprefix('http://').split('/')[0].removeprefix('www.').rstrip('.')
    if len(value) > 249 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', value):
        raise ValueError('Enter a domain such as youtube.com.')
    return value

class Model:
    def __init__(self, state=None):
        self.s = state or {'version': 3, 'settings': copy.deepcopy(DEFAULTS), 'days': {}, 'current': '', 'recovered': False, 'setup': False}
        if self.s.get('version') != 3:
            raise ValueError('Unsupported state version. Recover or restore the backup.')
        self.s['settings'] = {**DEFAULTS, **self.s['settings']}
        # The single implicit evidence folder became an explicit list the user approves.
        old = self.s['settings'].pop('evidence', '')
        if old and not self.s['settings']['roots']:
            try: self.s['settings']['roots'] = [folder(old)]
            except ValueError: pass
        self.s['settings'].pop('agent', None)
        # An agent Focus no longer drives falls back to following Omarchy's choice.
        if self.s['settings']['provider'] not in PROVIDERS: self.s['settings'].update(provider='auto', model='')
        # States from before first-run setup existed are already set up.
        self.s.setdefault('setup', True)

    def day_key(self, now):
        hour, minute = map(int, self.s['settings']['reset'].split(':'))
        local = dt.datetime.fromtimestamp(now)
        return (local - dt.timedelta(hours=hour, minutes=minute)).date().isoformat()

    def tick(self, now):
        key = self.day_key(now)
        # A day never comes back: a later reset time or a clock set backwards cannot reopen a finished day.
        if key < self.s['current']: key = self.s['current']
        if key != self.s['current']:
            previous = self.s['days'].get(self.s['current'], {})
            unfinished = [copy.deepcopy(t) for t in previous.get('tasks', []) if t['status'] != 'passed']
            # Unresolved carryovers survive skipped days too.
            unfinished += copy.deepcopy(previous.get('carry', []))
            self.s['days'].setdefault(key, {'date': key, 'started': False, 'startedAt': None, 'tasks': [],
                'carry': unfinished, 'decisions': [], 'pending': {}, 'overrides': [], 'challenge': None,
                'earnedUntil': 0, 'overrideUntil': 0, 'grade': '', 'events': []})
            self.s['current'] = key
        return self.s['days'][key]

    def settle(self, now):
        """Apply what only time was holding back: cooled-off task changes and a ripe emergency unlock."""
        d = self.tick(now)
        for ident, change in list(d['pending'].items()):
            if now < change['readyAt']: continue
            try: self.apply({'op': 'commit', 'id': ident}, now)
            except ValueError:
                d = self.tick(now)
                d['pending'].pop(ident, None)
        challenge = d['challenge']
        if challenge and challenge['readyAt'] is not None and now >= challenge['readyAt']:
            self.apply({'op': 'override'}, now)
        finished = [t for t in d['tasks'] if t.get('timer') and not t['timer']['done'] and now >= t['timer']['until']]
        for t in finished: t['timer']['done'] = True
        return finished

    def snapshot(self, now):
        day = self.tick(now)
        tasks = day['tasks']
        main = next((t for t in tasks if t['main']), None)
        all_done = bool(tasks) and all(t['status'] == 'passed' for t in tasks) and bool(main and main['status'] == 'passed')
        full = day['started'] and all_done
        until = max(day['overrideUntil'], day['earnedUntil'] if self.s['settings']['mode'] == 'earn' else 0)
        # Nothing blocks until first-run setup is finished.
        locked = self.s['setup'] and not self.s['recovered'] and not (day['started'] and (full or now < until))
        streak = 0
        date = dt.date.fromisoformat(day['date'])
        for offset in range(36600):
            candidate = self.s['days'].get((date - dt.timedelta(days=offset)).isoformat())
            # Verdicts recorded from outside Focus's own reviewer unlock, but never build a streak.
            passed = candidate and candidate['started'] and candidate['tasks'] and all(t['status'] == 'passed' and t.get('by') != 'external' for t in candidate['tasks']) and any(t['main'] for t in candidate['tasks']) and not candidate['overrides']
            if offset == 0 and not passed:
                continue
            if not passed:
                break
            streak += 1
        earlier = max((k for k in self.s['days'] if k < day['date'] and self.s['days'][k]['started']), default=None)
        yesterday = self.s['days'][earlier] if earlier else None
        return {**copy.deepcopy(day), 'settings': copy.deepcopy(self.s['settings']), 'locked': locked,
                'yesterday': yesterday and {'date': earlier, 'completed': sum(t['status'] == 'passed' for t in yesterday['tasks']),
                                            'total': len(yesterday['tasks']), 'grade': yesterday.get('grade', '')},
                'fullUnlock': full, 'remainingSeconds': max(0, int(until - now)) if not full else 0, 'until': until,
                'completed': sum(t['status'] == 'passed' for t in tasks), 'total': len(tasks),
                'streak': streak, 'recovered': self.s['recovered'], 'setup': self.s['setup'], 'now': now}

    def apply(self, cmd, now):
        # Capture retries survive a lost response or service restart. Store the
        # receipt in the same state write as its tasks, never in a separate file.
        receipt = cmd.get('requestId') if cmd.get('op') == 'capture' else None
        signature = hashlib.sha256(json.dumps(cmd, sort_keys=True).encode()).hexdigest() if receipt else ''
        receipts = self.s.get('captureReceipts', {})
        if receipt and receipt in receipts:
            if receipts[receipt] != signature: raise ValueError('This submission id was already used for different text.')
            return self.snapshot(now)
        before = copy.deepcopy(self.s)
        try:
            result = self._apply(cmd, now)
            if receipt:
                if not isinstance(receipt, str) or len(receipt) > 100: raise ValueError('Invalid submission id.')
                receipts = self.s.setdefault('captureReceipts', {})
                receipts[receipt] = signature
                while len(receipts) > 200: receipts.pop(next(iter(receipts)))
            return result
        except Exception:
            self.s.clear(); self.s.update(before)
            raise

    def _apply(self, cmd, now):
        d = self.tick(now)
        op = cmd.get('op')
        level = self.s['settings']['strictness']
        def find(ident):
            return next((t for t in d['tasks'] if t['id'] == ident), None)
        def require(ident):
            t = find(ident)
            if t is None: raise ValueError('Task no longer exists in today’s list.')
            return t
        def record(kind, **data):
            d['events'].append({'at': now, 'kind': kind, **data})
        if d['started'] and level == 'lockdown' and op in ('add', 'capture', 'plan-accept'):
            raise ValueError('Lockdown: the list is fixed once the day starts.')
        if op in ('snapshot', 'window', 'unlock'):
            pass
        elif op == 'add':
            t = task(cmd.get('text'), check=cmd.get('check') or '')
            d['tasks'].append(t)
            record('add', id=t['id'])
        elif op in ('plan-accept', 'capture'):
            if op == 'capture':
                text = cmd.get('text')
                if not isinstance(text, str) or len(text) > 15000: raise ValueError('Add up to 30 tasks, one per line.')
                proposed = [{'text': line.strip()} for line in text.splitlines() if line.strip()]
            else: proposed = cmd.get('tasks')
            if not isinstance(proposed, list) or not 1 <= len(proposed) <= 30: raise ValueError('Nothing to add.')
            if any(not isinstance(p, dict) for p in proposed): raise ValueError('Each task needs text.')
            new = [task(p.get('text'), check=p.get('check') or '') for p in proposed]
            if op == 'capture' and not d['started'] and not any(t['main'] for t in d['tasks']):
                new[0]['main'] = True
            # After Start, changing the main task keeps its countdown; a plan cannot skip it.
            if not d['started'] and type(cmd.get('main')) is int and 0 <= cmd['main'] < len(new):
                for other in d['tasks']: other['main'] = False
                new[cmd['main']]['main'] = True
            d['tasks'] += new
            for t in new: record('add', id=t['id'])
        elif op == 'carry':
            t = next((t for t in d['carry'] if t['id'] == cmd.get('id')), None)
            if not t or d['started']: raise ValueError('Carryover decision is no longer available.')
            action = cmd.get('action')
            if action not in ('carry', 'drop'): raise ValueError('Choose carry or drop.')
            if action == 'carry':
                new = task(t['text'], check=t.get('check') or '')
                new['carriedFrom'] = t['id']
                d['tasks'].append(new)
            d['carry'].remove(t)
            d['decisions'].append({'id': t['id'], 'text': t['text'], 'action': action, 'at': now})
        elif op == 'start':
            if d['carry']: raise ValueError('Carry or drop each unfinished task first.')
            if not d['tasks'] or sum(t['main'] for t in d['tasks']) != 1: raise ValueError('Add tasks and choose one main task.')
            if not d['started']:
                d['started'] = True
                d['startedAt'] = now
                record('start')
            self.s['recovered'] = False
        elif op == 'change':
            t = require(cmd.get('id'))
            action = cmd.get('action')
            if action not in ('delete', 'edit', 'main'): raise ValueError('Unknown task change.')
            text = clean(cmd.get('text')) if action == 'edit' else ''
            if action == 'delete' and t['main'] and d['started']: raise ValueError('Choose a replacement main task first.')
            if d['started'] and level == 'lockdown': raise ValueError('Lockdown: the list is fixed once the day starts.')
            change = {'id': t['id'], 'action': action, 'text': text, 'revision': t['revision'],
                      'readyAt': now + ((120 if level == 'hard' else 30) if d['started'] else 0)}
            d['pending'][t['id']] = change
            if not d['started']: self.apply({'op': 'commit', 'id': t['id']}, now)
        elif op == 'trust':
            # Agreeing in the morning that a task passes on their word is a decision; doing it mid-day is a loophole.
            t = require(cmd.get('id'))
            if d['started']: raise ValueError('Decide what passes on your word before the day starts.')
            if level == 'lockdown' and cmd.get('value'): raise ValueError('Lockdown takes evidence for everything.')
            t['onWord'] = bool(cmd.get('value'))
        elif op == 'timer':
            t = require(cmd.get('id'))
            minutes = cmd.get('minutes')
            if not d['started']: raise ValueError('Start the day first.')
            if type(minutes) is not int or not 1 <= minutes <= 600: raise ValueError('A timer runs 1 to 600 minutes.')
            t['timer'] = {'minutes': minutes, 'until': now + minutes * 60, 'done': False}
            record('timer', id=t['id'], minutes=minutes)
        elif op == 'check':
            # How a task will be checked is a note for the reviewer; changing it costs nothing.
            require(cmd.get('id'))['check'] = clean(cmd['check']) if cmd.get('check') else ''
        elif op == 'cancel':
            d['pending'].pop(cmd.get('id'), None)
        elif op == 'commit':
            t = require(cmd.get('id'))
            p = d['pending'].get(t['id'])
            if not p: raise ValueError('Request the change first.')
            if now < p['readyAt']: raise ValueError('Wait for the countdown.')
            if t['revision'] != p['revision']: raise ValueError('Task changed. Request the edit again.')
            previous = copy.deepcopy(t)
            if p['action'] == 'delete':
                if d['started'] and t['main']: raise ValueError('Choose a replacement main task first.')
                d['tasks'].remove(t)
            elif p['action'] == 'main':
                for other in d['tasks']: other['main'] = other['id'] == t['id']
            else:
                t.update(text=p['text'], revision=t['revision'] + 1, status='open', verdict=None, note='')
            record(p['action'], id=t['id'], previous=previous, text=p['text'])
            d['pending'].pop(t['id'], None)
        elif op == 'verdict':
            if not d['started']: raise ValueError('Start the day before reviewing tasks.')
            t = require(cmd.get('id'))
            verdict = cmd.get('verdict')
            if verdict not in ('pass', 'fail'): raise ValueError('Choose pass or fail.')
            note = clean(cmd.get('note'))
            if cmd.get('revision') is not None and cmd['revision'] != t['revision']: raise ValueError('Task was edited during review. Review it again.')
            basis = cmd.get('basis') or 'evidence'
            if basis not in ('evidence', 'claim'): raise ValueError('Basis must be evidence or claim.')
            if verdict == 'pass' and level in ('hard', 'lockdown'):
                if basis == 'claim' and not t.get('onWord'): raise ValueError('This mode needs evidence: a file, a screenshot, a link or a finished timer. Their word alone does not pass.')
                if level == 'lockdown' and not t['main'] and not any(o['main'] and o['status'] == 'passed' for o in d['tasks']):
                    raise ValueError('Lockdown: the main task has to pass first.')
            by = 'agent' if cmd.get('by') == 'agent' else 'external'
            entry = {'verdict': verdict, 'note': note, 'at': now, 'revision': t['revision'], 'text': t['text'], 'basis': basis, 'by': by}
            t['verdicts'].append(entry)
            t.update(verdict=verdict, note=note, basis=basis, by=by, status='passed' if verdict == 'pass' else 'open')
            if verdict == 'pass' and not t['credited']:
                if self.s['settings']['mode'] == 'earn':
                    d['earnedUntil'] = max(now, d['earnedUntil']) + self.s['settings']['minutes'] * 60
                t['credited'] = True
            record('verdict', id=t['id'], **entry)
        elif op == 'grade':
            word = clean(cmd.get('word'))
            if len(word.split()) != 1 or len(word) > 40: raise ValueError('Use one word, at most 40 characters.')
            d['grade'] = word
            d['gradeNote'] = clean(cmd['note']) if cmd.get('note') else ''
            record('grade', word=word, note=d['gradeNote'])
        elif op == 'challenge':
            if not d['started']: raise ValueError('Start the day first.')
            if level == 'lockdown': raise ValueError('Lockdown has no emergency unlock.')
            if level == 'hard' and d['overrides']: raise ValueError('Hard mode allows one emergency unlock a day, and it is used.')
            if not d['challenge']:
                d['challenge'] = {'code': ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32)), 'readyAt': None}
        elif op == 'challenge-submit':
            c = d['challenge']
            if not c or not secrets.compare_digest(str(cmd.get('code', '')), c['code']): raise ValueError('Code does not match.')
            if c['readyAt'] is None: c['readyAt'] = now + 60
        elif op == 'override':
            c = d['challenge']
            if not d['started'] or not c or c['readyAt'] is None or now < c['readyAt']: raise ValueError('Type the code, then wait 60 seconds.')
            d['overrideUntil'] = now + 900
            d['overrides'].append({'at': now, 'until': now + 900})
            d['challenge'] = None
            record('override', until=now + 900)
        elif op == 'settings':
            values = cmd.get('values', {})
            new = copy.deepcopy(self.s['settings'])
            for key, value in values.items():
                if key == 'reset':
                    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value): raise ValueError('Reset time must be HH:MM.')
                    if d['started']: raise ValueError('Change reset time before starting a day.')
                elif key == 'mode':
                    if value not in ('all', 'earn'): raise ValueError('Choose all or earn.')
                    if d['started']: raise ValueError('Change unlock mode before starting a day.')
                elif key == 'minutes':
                    if type(value) is not int or not 1 <= value <= 240: raise ValueError('Minutes must be 1–240.')
                    if d['started']: raise ValueError('Change earned minutes before starting a day.')
                elif key == 'sites':
                    if not isinstance(value, list) or len(value) > 500: raise ValueError('Maximum 500 sites.')
                    value = sorted(set(domain(v) for v in value))
                elif key == 'apps':
                    if not isinstance(value, list) or len(value) > 500: raise ValueError('Maximum 500 apps.')
                    value = sorted(set(clean(v) for v in value))
                elif key == 'hosts':
                    if type(value) is not bool: raise ValueError('Hosts setting must be boolean.')
                elif key == 'planning':
                    if value not in ('quick', 'guided'): raise ValueError('Choose quick or guided planning.')
                elif key == 'strictness':
                    if value not in LEVELS: raise ValueError('Choose honor, standard, hard or lockdown.')
                    if d['started'] and LEVELS.index(value) < LEVELS.index(new['strictness']): raise ValueError('You can raise the mode today, but only lower it from tomorrow.')
                elif key in ('borders', 'strip', 'sound', 'updates'):
                    if type(value) is not bool: raise ValueError('That setting is on or off.')
                elif key == 'provider':
                    if value not in PROVIDERS: raise ValueError('Choose auto, claude, codex, grok or opencode.')
                elif key == 'model':
                    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{0,100}', value): raise ValueError('A model id is letters, digits and . _ : / - only.')
                elif key == 'endpoint':
                    value = endpoint(value)
                elif key == 'roots':
                    if not isinstance(value, list) or len(value) > 10: raise ValueError('At most 10 folders.')
                    value = sorted(set(folder(v) for v in value))
                else: raise ValueError('Unknown setting.')
                # Blocklists remain adjustable, but relaxing them is part of the morning ritual.
                if d['started'] and ((key in ('sites','apps') and not set(new[key]).issubset(value)) or (key == 'hosts' and new[key] and not value)):
                    raise ValueError('Remove blocks before starting a day, or use the emergency override.')
                new[key] = value
            # A model name belongs to the agent it was chosen for; a different agent starts on its own default.
            if new['provider'] != self.s['settings']['provider'] and 'model' not in values: new['model'] = ''
            self.s['settings'] = new
            record('settings', values=values)
        elif op == 'setup-done':
            self.s['setup'] = True
            record('setup')
        elif op == 'recover':
            self.s['recovered'] = True
            record('recover')
        else:
            raise ValueError('Unknown command.')
        return self.snapshot(now)
