"""The Bouncer service: one loop owning the state, the blocking, the agent and every connected client."""
import copy
import difflib
import fcntl
import json
import os
import queue
import selectors
import signal
import socket
import struct
import subprocess
import threading
import time
import traceback

import agent
import blocking
import common
import update
from common import one_line, read, write, toast
import base64
from pathlib import Path

from backend import Backend
from model import Model, folder
from tools import Tools

# The very first thing Bouncer says is fixed: instant, and never an experiment in phrasing.
FIRST_RUN = "I'm Bouncer. Each morning you tell me what you need to get done, and I keep your time-wasting sites and apps locked until it's done. Which ones waste your time? Pick any below, or type your own."
# Offered as clickable picks with the first question; anything else can be typed.
COMMON_SITES = ['youtube.com', 'x.com', 'reddit.com', 'instagram.com', 'facebook.com', 'tiktok.com', 'twitch.tv', 'netflix.com', 'linkedin.com', 'news.ycombinator.com']
HELP = ('/planning quick|guided · /config shows planning style, the agent and approved folders · /folder PATH approves a folder (/folder remove PATH) · /provider auto|claude|codex|grok|opencode · '
        '/model NAME (/models lists them; for Claude: haiku is the low-cost one) · /endpoint URL · /update installs a newer Bouncer (/update check, /update on|off) · '
        '/forget deletes the conversation and any stored screenshot')
YES, NO = ('y', 'yes', 'allow', 'ok', 'okay', 'sure', 'do it'), ('n', 'no', 'deny', 'cancel', 'not now', 'stop')
NO_AGENT = "Install and sign in to Claude Code, Codex, Grok Build or OpenCode, then choose it in Settings. You can still capture tasks directly."
EVENTS = {
    'morning': 'A new day. The card just opened for the morning check-in. Greet them in one line and get to what today holds.',
}

class Chat:
    """The visible conversation. Only messages persist; the rest is live."""
    KEEP = 40

    def __init__(self):
        saved = read(common.STATE/'chat.json')
        self.day = saved.get('day', '')
        self.greeted = saved.get('greeted', '')
        self.messages = saved.get('messages', [])
        self.choices = saved.get('choices')
        # Something only the user can approve: a folder, a link, a screenshot. Never granted by the agent.
        self.consent = None
        self.streaming = self.activity = self.suggestion = ''
        self.busy = False

    def add(self, role, text):
        self.messages = (self.messages + [{'role': role, 'text': text, 'at': time.time()}])[-self.KEEP:]
        self.save()

    def save(self): write(common.STATE/'chat.json', {'day': self.day, 'greeted': self.greeted, 'messages': self.messages, 'choices': self.choices})

    def public(self):
        return {'messages': self.messages, 'streaming': self.streaming, 'activity': self.activity,
                'suggestion': self.suggestion, 'choices': self.choices, 'consent': self.consent, 'busy': self.busy}

class Daemon:
    def __init__(self):
        path = common.STATE/'state.json'
        self.model = Model(read(path)) if path.exists() else Model()
        self.runtime = blocking.Runtime()
        self.borders = blocking.Borders()
        self.capture = False
        self.passed = None
        self.backend = Backend()
        self.updates = update.Watcher()
        self.helper_stale = blocking.helper_stale()
        self.moved = False
        # The extension's folder changed in 2.3: follow it, so an updated install keeps its blocked page.
        if common.TOASTS and blocking.browser_moved():
            try: blocking.browser_connect(); self.moved = True
            except (OSError, ValueError): pass
        self.refreshing = False
        self.links = set()
        self.shot = None
        settings = self.model.s['settings']
        self.config = (settings['provider'], settings['model'], settings['endpoint'], tuple(settings['roots']))
        self.chat = Chat()
        if self.moved: self.chat.add('system', 'This version moved the Bouncer browser extension. Restart your browser to load it again.')
        self.session = agent.make_session(self)
        self.tools = Tools(self.model, self)
        self.selector = selectors.DefaultSelector()
        self.clients = {}
        self.done = queue.Queue()
        self.auth = False
        self.visible = False
        self.saved = self.sent_state = self.sent_chat = ''
        self.submissions = {}
        self.chat_at = 0
        self.running = True

    # --- what the agent session and the tools need from their host -------------------------------

    def watch(self, stream, callback): self.selector.register(stream, selectors.EVENT_READ, callback)
    def unwatch(self, stream):
        try: self.selector.unregister(stream)
        except (KeyError, ValueError): pass

    def digest(self): return agent.digest(self.state(), time.time())
    def recap(self):
        lines = ['%s: %s' % ('user' if m['role'] == 'user' else 'you', m['text']) for m in self.chat.messages[-12:]]
        return '<earlier_today>\n' + '\n'.join(lines) + '\n</earlier_today>\n' if lines else ''

    def turn_started(self): self.chat.busy, self.chat.streaming, self.chat.activity = True, '', ''
    def turn_progress(self, text, activity):
        self.chat.streaming = text
        if activity is not None: self.chat.activity = activity
        elif text: self.chat.activity = ''
    def turn_finished(self, text):
        self.chat.busy, self.chat.streaming, self.chat.activity = self.session.busy, '', ''
        if text:
            self.chat.add('agent', text)
            if not self.visible: toast('Bouncer', text)
    def turn_failed(self, text):
        self.chat.busy, self.chat.streaming, self.chat.activity = False, '', ''
        self.chat.add('system', text)

    # --- consent: the user approves folders, links and screenshots; the agent can only ask ----------

    def info(self): return self.backend.describe(self.model.s['settings'])
    def link_allowed(self, url): return url in self.links
    def shared_screenshot(self): raise ValueError('There is no approved screenshot to view.')

    def ask(self, kind, value):
        if self.chat.consent: raise ValueError('Already waiting for the user to answer another request.')
        info = self.info()
        if kind == 'screen' and not info['vision']: raise ValueError('This model cannot see images, so a screenshot would not help. Use another kind of evidence.')
        text = {'folder': 'Let Bouncer read files in %s? Keys and credentials inside it are never read.' % value,
                'link': 'Let Bouncer open this link? %s' % value,
                'screen': 'Take a screenshot of this monitor? You will see it before anything is sent.'}[kind]
        self.chat.consent = {'kind': kind, 'value': value, 'text': text, 'preview': '', 'goes': info['label']}
        return 'Asked the user. Say in a few words what you asked for and stop; their answer arrives as an event.'

    def discard_consent(self):
        if self.chat.consent and self.chat.consent['kind'] == 'share': self.discard_shot()
        self.chat.consent = None

    def discard_shot(self):
        for old in (common.STATE/'proof').glob('screen-*'): old.unlink()
        self.shot = None

    def decide(self, yes):
        consent, self.chat.consent = self.chat.consent, None
        if not consent: return
        kind, value = consent['kind'], consent['value']
        if kind == 'folder':
            if yes: self.model.apply({'op': 'settings', 'values': {'roots': self.model.s['settings']['roots'] + [value]}}, time.time())
            self.resume('The user %s the folder %s.' % ('approved' if yes else 'declined', value))
        elif kind == 'link':
            if yes: self.links.add(value)
            self.resume('The user approved the link; call open_link again.' if yes else 'The user declined the link.')
        elif kind == 'screen':
            if not yes: return self.resume('The user declined the screenshot.')
            self.capture = True  # the card steps aside while the picture is taken
            def work():
                time.sleep(0.7)
                try: self.done.put(('captured', blocking.screenshot(), ''))
                except Exception as exc: self.done.put(('captured', '', one_line(exc, 200) or 'failed'))
            threading.Thread(target=work, daemon=True).start()
        elif kind == 'share':
            if not yes:
                self.discard_shot()
                return self.resume('The user looked at the image and chose not to share it.')
            self.reconfigure()
            if isinstance(self.session, agent.ExecSession):
                # This agent cannot take an image from a tool, so it travels with the message itself.
                self.session.attach = value
                self.event('The user has shared an image as evidence. It is attached to this very message as an image you can already see. '
                           'Do not call view_screenshot or look_at_screen: look at the attached image and judge the task from it.')
            else:
                self.shot = value
                self.event('The user has shared an image as evidence; call view_screenshot now to see it.')

    def resume(self, text):
        """Tell the agent what the user decided. After a settings change the old session is gone; the new one hears it."""
        self.reconfigure()
        self.event(text)

    def reconfigure(self):
        """A change of model, server or approved folders ends the running session; nothing from it can land afterwards."""
        settings = self.model.s['settings']
        config = (settings['provider'], settings['model'], settings['endpoint'], tuple(settings['roots']))
        if config == self.config: return
        changed_backend = self.config is not None and config[:3] != self.config[:3]
        was_busy, self.config = self.session.busy, config
        self.session.stop()
        # A different agent may need a different kind of session altogether.
        self.session = agent.make_session(self)
        if changed_backend:
            # A different model is a different recipient: it does not inherit pending approvals or the earlier conversation.
            self.chat.consent = None
            self.links.clear()
            self.discard_shot()
            self.session.forget = True
            self.chat.add('system', 'Now on %s. Fresh start: the earlier conversation was not passed on.' % self.info()['label'])
        if was_busy: self.turn_failed('Settings changed mid-reply, so that reply was dropped. Say it again.')

    def models(self):
        """What the current agent can run, cheapest first where Bouncer knows the order."""
        kind = self.info()['provider']
        try:
            if kind == 'claude': return 'Claude models: haiku (lowest cost, fastest) · sonnet (default) · opus (most capable). Set one with /model NAME.'
            if kind == 'grok': return 'Grok uses its CLI default model. Run grok models in a terminal, then /model NAME here.'
            if kind == 'opencode':
                # Only models of providers it is signed in to and Bouncer can route to.
                signed = set(read(agent.opencode_auth())) & set(agent.netgate.OPENCODE_HOSTS)
                listed = [m for m in common.run([agent.binary('opencode'), 'models'], timeout=20).split() if m.partition('/')[0] in signed]
                return 'OpenCode models: ' + (' · '.join(listed[:40]) or 'none; sign in with opencode auth login') + '. Set one with /model PROVIDER/NAME.'
            if kind == 'codex':
                listed = read(Path.home()/'.codex/models_cache.json').get('models') or []
                rows = ['%s (%s)' % (m['slug'], one_line(m.get('description'), 60).rstrip('.')) for m in listed if isinstance(m, dict) and m.get('slug')]
                return 'Codex models: ' + (' · '.join(rows) or 'none cached; run codex once') + '. Set one with /model NAME; the ones described as fast or affordable cost least.'
            listed = json.loads(common.run(['curl', '-s', '--max-time', '3', self.model.s['settings']['endpoint'] + '/api/tags'])).get('models') or []
            return 'Ollama models: ' + (' · '.join(m.get('name', '') for m in listed) or 'none pulled') + '. Set one with /model NAME.'
        except Exception as exc: return 'Could not list models: ' + one_line(exc, 120)

    def command(self, text):
        """Typed by the user, handled here: configuration never depends on the model being reachable or willing."""
        words = text[1:].split()
        name, rest = (words[0].lower() if words else 'help'), ' '.join(words[1:])
        now, settings = time.time(), self.model.s['settings']
        change = lambda **values: self.model.apply({'op': 'settings', 'values': values}, now)
        if name == 'models': return self.models()
        if name == 'update':
            if rest in ('on', 'off'):
                change(updates=rest == 'on')
                return 'Checking for updates is %s. Nothing installs until you say so.' % rest
            found = self.updates.public()
            if rest == 'check' or not found['available']:
                if not found['managed']: return 'This copy was not installed with omarchy plugin add, so it updates by hand.'
                self.updates.look()
                return 'Bouncer %s. Checking for a newer one; it shows on the card if there is.' % found['current']
            self.start_update()
            return 'Updating to %s. Bouncer restarts when it is done.' % (found['version'] or 'the newest version')
        if name == 'folder':
            if rest.startswith('remove '):
                target = str(Path(rest[7:].strip()).expanduser())
                change(roots=[r for r in settings['roots'] if r != target])
            elif rest: change(roots=settings['roots'] + [folder(rest)])
        elif name == 'provider':
            if not rest: return 'Agent: %s. Choose in Settings, or /provider claude, codex, grok, opencode or auto.' % agent.resolve(settings)
            change(provider=rest.lower())
        elif name == 'planning':
            if rest:
                change(planning=rest.lower())
                self.chat.suggestion, self.chat.choices = '', None
            return 'Planning: %s. Use /planning quick or /planning guided. Completion review rules are unchanged.' % self.model.s['settings']['planning']
        elif name == 'model':
            if not rest: return 'Model: %s. Use /models for options, then /model NAME.' % (settings['model'] or 'provider default')
            change(model=rest)
        elif name == 'endpoint' and rest: change(endpoint=rest)
        elif name == 'forget':
            self.chat.messages, self.chat.choices, self.chat.consent, self.chat.suggestion = [], None, None, ''
            self.links.clear(); self.discard_shot()
            self.session.stop()
            self.chat.save()
            return 'Forgotten: the conversation, approved links and any stored screenshot. Tasks and history are kept.'
        elif name not in ('config', 'help'):
            match = difflib.get_close_matches(name, ('planning','provider','model','models','config','folder','forget','update','help'), n=1, cutoff=0.6)
            return ('Unknown command. Did you mean /%s?' % match[0]) if match else 'Unknown command. Open Settings or type /help.'
        if name == 'help': return HELP
        self.reconfigure()
        settings, info = self.model.s['settings'], self.backend.describe(self.model.s['settings'])
        return 'Planning: %s · Model: %s%s%s · Folders I may read: %s' % (settings['planning'], info['label'], '' if info['ok'] else ' (' + info['error'] + ')',
                                                          ' · ' + info['note'] if info.get('note') else '', ', '.join(settings['roots']) or 'none')

    def open_apps(self): return blocking.open_apps()
    def installed_apps(self): return blocking.installed_apps()
    def connect_browser(self): return blocking.browser_connect()
    def suggest(self, text): self.chat.suggestion = one_line(text, 80)
    def choose(self, options, multiple):
        self.chat.choices = {'options': [one_line(o, 40) for o in options][:12], 'multiple': bool(multiple)}
        self.chat.save()
    def validate_setup(self):
        import doctor
        doctor.require_ready(self.model.s['settings'])
        if not Path(blocking.HELPER).is_file(): raise ValueError('Install the blocking helper before finishing setup.')

    def install_helper(self):
        import doctor
        doctor.require_ready(self.model.s['settings'])
        if self.auth: raise ValueError('A password prompt is already showing.')
        self.auth = True
        def work():
            try: common.run([str(common.PLUGIN/'setup.sh'), '--passwordless'], timeout=180, stdin=subprocess.DEVNULL); self.done.put(('helper', ''))
            except Exception as exc: self.done.put(('helper', one_line(exc, 200) or 'failed'))
        threading.Thread(target=work, daemon=True).start()
        return 'The password prompt is on screen. Tell them so in a few words and stop; the result arrives as an event.'

    def start_update(self):
        if not self.updates.install(lambda error: self.done.put(('updated', error))): raise ValueError('Bouncer is already checking or updating.')

    def refresh_helper(self):
        """A new version shipped a new root helper: put it in place, with the same single password prompt as setup."""
        if not self.helper_stale: raise ValueError('The blocking helper is already current.')
        self.install_helper()
        self.refreshing = True

    # --- state ------------------------------------------------------------------------------------

    def state(self):
        return {**self.runtime.enrich(self.model.snapshot(time.time())), 'agent': agent.available(), 'auth': self.auth, 'capture': self.capture,
                'backend': self.info(), 'update': self.updates.public(), 'helperStale': self.helper_stale,
                'introduced': self.chat.greeted.startswith('first_run')}

    def event(self, text): self.session.send('<event>' + text + '</event>')

    def say(self, text):
        text = one_line(text, 4000)
        if not text: return
        now = time.time()
        challenge = self.model.tick(now)['challenge']
        if challenge and challenge['readyAt'] is None and text == challenge['code']:
            self.model.apply({'op': 'challenge-submit', 'code': text}, now)
            self.chat.add('system', 'Code accepted. Unlocking in 60 seconds.')
            return
        if text.startswith('/'):
            try: self.chat.add('system', self.command(text))
            except ValueError as exc: self.chat.add('system', str(exc))
            return
        if self.chat.consent and text.lower().rstrip('.!') in YES + NO:
            return self.decide(text.lower().rstrip('.!') in YES)
        self.chat.suggestion, self.chat.choices = '', None
        self.chat.add('user', text)
        if not agent.available(): return self.without_agent(text, now)
        info = self.info()
        # No fallback: if the chosen model cannot be reached, say so and change nothing.
        if not info['ok']: return self.chat.add('system', info['error'] + ' Type /config to see the setup, or /provider claude to switch.')
        self.session.send('<user>' + text + '</user>')

    def without_agent(self, text, now):
        """No agent installed: lines become tasks and "start" starts, so the day still works."""
        if not self.model.s['setup']:
            self.chat.add('system', NO_AGENT)
            return
        try:
            if text.lower() in ('start', 'start the day'):
                self.model.apply({'op': 'start'}, now)
                self.chat.add('system', 'Started. Without an agent, verdicts come from `focusctl verdict`.')
                return
            if not self.model.s['setup']: self.model.apply({'op': 'setup-done'}, now)
            state = self.model.apply({'op': 'add', 'text': text}, now)
            if not any(t['main'] for t in state['tasks']): self.model.apply({'op': 'change', 'id': state['tasks'][0]['id'], 'action': 'main'}, now)
            self.chat.add('system', 'Added. No agent found (install Claude Code for the real thing). Type "start" when the list is right.')
        except ValueError as exc: self.chat.add('system', str(exc))

    def opened(self):
        self.visible = True
        if not agent.available():
            if not self.model.s['setup'] and (not self.chat.messages or self.chat.messages[-1]['text'] != NO_AGENT): self.chat.add('system', NO_AGENT)
            return
        if self.session.busy or self.session.queue or not self.info()['ok']: return
        state, greeting = self.model.snapshot(time.time()), ''
        if not state['setup']: greeting = 'first_run'
        elif not state['started'] and not state['recovered']: greeting = 'morning'
        if greeting and self.chat.greeted != greeting + state['date']:
            self.chat.greeted = greeting + state['date']
            if greeting == 'first_run':
                self.chat.choices = {'options': COMMON_SITES, 'multiple': True}
                # Said before anything is typed: where the words go.
                self.chat.add('system', 'Before you start: I run on %s. What you type here, and any file, link or screenshot you let me look at, is %s. Your tasks and history stay on this machine. /config shows or changes this.'
                              % (self.info()['label'], 'read there' if self.info()['where'] != 'local' else 'read on this machine'))
                self.chat.add('agent', FIRST_RUN)
            else:
                self.chat.save()
                self.event(EVENTS[greeting])
        else:
            try: self.session.ensure()  # warm, so the first reply is quick
            except OSError: pass

    def blocked(self, name=''):
        state = self.model.snapshot(time.time())
        left = state['total'] - state['completed']
        if not state['locked']: text = 'Nothing is locked right now.'
        else: text = (name + ' is locked. ' if name else 'That one is locked. ') + (
            'I keep you focused: get %s done and it is yours again.' % ('your last task' if left == 1 else 'your %d tasks' % left) if state['started']
            else 'Tell me what you are getting done today and we can start.')
        if not self.chat.messages or self.chat.messages[-1]['text'] != text: self.chat.add('system', text)
        if state['locked'] and state['settings']['sound']: common.sound('dialog-error')

    def handle(self, cmd, client):
        now, op = time.time(), cmd.get('op')
        reply = {'ok': True}
        receipt = cmd.get('requestId') if op == 'say' else None
        if receipt and receipt in self.submissions:
            if self.submissions[receipt] != cmd.get('text'): raise ValueError('Submission id already used.')
            return {'ok': True, 'state': self.state(), 'chat': self.chat.public()}
        if op == 'ping': return reply
        if op == 'subscribe': client['subscribed'] = True
        elif op == 'say':
            if cmd.get('requestId') and not str(cmd.get('text') or '').startswith('/') and agent.available() and not self.info()['ok']:
                raise ValueError(self.info()['error'] + ' Your text is kept. Open Settings to fix the connection.')
            self.say(cmd.get('text'))
        elif op == 'opened': self.opened()
        elif op == 'closed': self.visible = False
        elif op == 'blocked': self.blocked(one_line(cmd.get('name'), 80))
        elif op == 'consent': self.decide(bool(cmd.get('answer')))
        elif op == 'paste':
            # The user pasted a picture as evidence. It is theirs to offer, and they still see it and confirm before it is sent.
            if not self.info()['vision']: raise ValueError('This model cannot see images.')
            path = blocking.clipboard_image()
            if path:
                self.discard_consent()
                self.chat.consent = {'kind': 'share', 'value': path, 'text': 'Send this pasted image to be read?', 'preview': path, 'goes': self.info()['label']}
        elif op == 'doctor':
            import doctor
            reply['checks'] = doctor.checks(self.model.s['settings'])
        elif op == 'forget': self.command('/forget')
        elif op == 'update': self.start_update()
        elif op == 'update-check': self.updates.look()
        elif op == 'helper-refresh': self.refresh_helper()
        elif op == 'tool':
            # A tool call from a session that has since been replaced must not land.
            if cmd.get('session') is not None and cmd.get('session') != self.session.token: raise ValueError('That session has ended.')
            if cmd.get('name') == 'view_screenshot' and getattr(self.session, 'attached', False):
                reply['text'] = 'The approved image is attached to the message you are answering. Look at it there.'
            elif cmd.get('name') == 'view_screenshot':
                if not self.shot: raise ValueError('There is no approved screenshot to view.')
                reply['text'] = 'The screenshot the user approved.'
                reply['image'] = {'data': base64.b64encode(Path(self.shot).read_bytes()).decode(), 'mime': 'image/png' if self.shot.endswith('.png') else 'image/jpeg'}
                self.discard_shot()  # seen once, then gone
            else: reply['text'] = self.tools.call(cmd.get('name'), cmd.get('args'), now)
        else:
            if op == 'setup-done': self.validate_setup()
            self.model.apply(cmd, now)
        if op == 'settings': self.reconfigure()
        self.settle(force=op not in ('snapshot', 'subscribe', 'say', 'opened', 'closed'))
        reply['state'] = self.state()
        if op in ('subscribe', 'say'): reply['chat'] = self.chat.public()
        if op == 'snapshot' and cmd.get('history'):
            reply['state']['history'] = sorted(copy.deepcopy(list(self.model.s['days'].values())), key=lambda d: d['date'], reverse=True)[:max(1, min(365, int(cmd['history'])))]
        if receipt:
            self.submissions[receipt] = cmd.get('text')
            while len(self.submissions) > 200: self.submissions.pop(next(iter(self.submissions)))
        return reply

    def settle(self, force=False):
        """Let time-based rules land, save, and bring the machine in line with the state."""
        now = time.time()
        for t in self.model.settle(now):
            toast('Timer finished', t['text'])
            self.event('The timer on [%s] "%s" has finished: %d minutes on the clock. Record the verdict.' % (t['id'], t['text'], t['timer']['minutes']))
        state = self.model.snapshot(now)
        if self.chat.day != state['date']:
            self.chat.day, self.chat.messages, self.chat.consent = state['date'], [], None
            self.links.clear(); self.discard_shot()
            self.chat.save()
        serialized = json.dumps(self.model.s)
        if serialized != self.saved:
            write(common.STATE/'state.json', self.model.s)
            self.saved = serialized
        blocked_before = self.runtime.blocked_at
        self.runtime.reconcile(state, force=force, quiet=self.visible)
        if self.runtime.blocked_at != blocked_before: self.blocked(self.runtime.blocked_name)
        self.borders.set(state['locked'] and state['settings']['borders'])
        if self.passed is not None and state['settings']['sound'] and state['completed'] > self.passed:
            common.sound('service-login' if state['fullUnlock'] else 'complete')
        self.passed = state['completed']

    # --- clients ----------------------------------------------------------------------------------

    def accept(self, server):
        conn, _ = server.accept()
        try:
            if struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1] != os.getuid(): raise OSError('Wrong local user.')
        except OSError:
            conn.close(); return
        conn.settimeout(1)
        client = {'conn': conn, 'buffer': b'', 'subscribed': False}
        self.clients[conn] = client
        self.selector.register(conn, selectors.EVENT_READ, lambda: self.receive(client))

    def drop(self, client):
        self.unwatch(client['conn'])
        self.clients.pop(client['conn'], None)
        client['conn'].close()

    def send(self, client, message):
        try: client['conn'].sendall(json.dumps(message, ensure_ascii=False).encode() + b'\n')
        except OSError: self.drop(client)

    def receive(self, client):
        try: data = client['conn'].recv(65536)
        except OSError: data = b''
        if not data: return self.drop(client)
        client['buffer'] += data
        if len(client['buffer']) > 262144: return self.drop(client)
        while b'\n' in client['buffer']:
            raw, client['buffer'] = client['buffer'].split(b'\n', 1)
            before = copy.deepcopy(self.model.s)
            command = {}
            try:
                command = json.loads(raw)
                reply = self.handle(command, client)
            except Exception as exc:
                self.model.s.clear(); self.model.s.update(before)
                reply = {'ok': False, 'error': str(exc) or 'Refused.'}
            if reply is not None:
                if isinstance(command, dict) and command.get('requestId'): reply['requestId'] = command['requestId']
                self.send(client, reply)
        self.publish()

    def publish(self, chat_only=False):
        """Push state and conversation to subscribers when they change."""
        subscribers = [c for c in self.clients.values() if c['subscribed']]
        if not chat_only:
            state = self.state()
            signature = json.dumps({k: v for k, v in state.items() if k not in ('now', 'remainingSeconds')}, sort_keys=True)
            if signature != self.sent_state:
                for client in subscribers: self.send(client, {'push': 'state', 'state': state})
                self.sent_state = signature
        chat = self.chat.public()
        signature = json.dumps(chat, sort_keys=True)
        if signature != self.sent_chat:
            for client in subscribers: self.send(client, {'push': 'chat', 'chat': chat})
            self.sent_chat = signature

    def tick(self):
        now = time.time()
        while True:
            try: finished = self.done.get_nowait()
            except queue.Empty: break
            if finished[0] == 'captured':
                self.capture = False
                if finished[2]: self.resume('The screenshot could not be taken: ' + finished[2])
                else: self.chat.consent = {'kind': 'share', 'value': finished[1], 'text': 'Send this screenshot to be read?', 'preview': finished[1], 'goes': self.info()['label']}
                continue
            if finished[0] == 'updated':
                if finished[1]: self.chat.add('system', 'The update did not install: ' + finished[1])
                else:
                    self.chat.add('system', 'Updated. Bouncer is restarting to load it.')
                    self.publish()
                    # Without the shell's own restart, at least the service comes back on the new code.
                    if not update.restart(): self.running = False
                continue
            self.auth, self.helper_stale = False, blocking.helper_stale()
            if self.refreshing:
                self.refreshing = False
                self.chat.add('system', 'The blocking helper could not be refreshed: ' + finished[1] if finished[1] else 'Blocking helper refreshed.')
            else: self.event('The system helper install ' + ('failed: ' + finished[1] if finished[1] else 'finished: it is installed.') + ' Carry on with setup.')
        self.updates.poll(now, self.model.s['settings']['updates'])
        self.session.tick(now)
        self.settle()
        self.publish()

    def serve(self):
        common.STATE.mkdir(parents=True, mode=0o700, exist_ok=True)
        lock = (common.STATE/'service.lock').open('w')
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        os.chmod(common.STATE, 0o700)
        def stop(*_): self.running = False
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        common.SOCKET.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(common.SOCKET))
            common.SOCKET.chmod(0o600)
            server.listen(16)
            self.selector.register(server, selectors.EVENT_READ, lambda: self.accept(server))
            try:
                last = 0
                while self.running:
                    # While the agent is talking, wake often enough that no streamed text waits on the throttle.
                    for key, _ in self.selector.select(timeout=0.04 if self.chat.busy else 0.25):
                        # One misbehaving client or agent must never take the service, and the blocking with it, down.
                        try: key.data()
                        except Exception:
                            traceback.print_exc()
                            self.session.stop()
                            self.turn_failed('Something went wrong talking to the agent. Say it again.')
                    # Streaming text publishes as it arrives; everything else on the half-second tick.
                    if self.chat.busy and time.time() - self.chat_at > 0.04:
                        self.chat_at = time.time()
                        self.publish(chat_only=True)
                    if time.time() - last >= 0.5:
                        last = time.time()
                        self.tick()
            finally:
                self.session.stop()
                for way_out in agent.GATES.values(): way_out.close()
                self.borders.set(False)
                try: self.runtime.restore({c['address']: c for c in blocking.clients()})
                except Exception: pass
                common.SOCKET.unlink(missing_ok=True)

def serve(): Daemon().serve()
