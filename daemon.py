"""The Focus service: one loop owning the state, the blocking, the agent and every connected client."""
import copy
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

import agent
import blocking
import common
from common import one_line, read, write, toast
from model import Model
from tools import Tools

# The very first thing Focus says is fixed: instant, and never an experiment in phrasing.
FIRST_RUN = "I'm Focus. Each morning you tell me what you need to get done, and I keep your time-wasting sites and apps locked until it's done. Which ones waste your time? Pick any below, or type your own."
# Offered as clickable picks with the first question; anything else can be typed.
COMMON_SITES = ['youtube.com', 'x.com', 'reddit.com', 'instagram.com', 'facebook.com', 'tiktok.com', 'twitch.tv', 'netflix.com', 'linkedin.com', 'news.ycombinator.com']
NO_AGENT = "I need Claude Code to work, and I can't find it. Install it with `omarchy default agent claude`, sign in, then open me again."
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
        self.streaming = self.activity = self.suggestion = ''
        self.busy = False

    def add(self, role, text):
        self.messages = (self.messages + [{'role': role, 'text': text, 'at': time.time()}])[-self.KEEP:]
        self.save()

    def save(self): write(common.STATE/'chat.json', {'day': self.day, 'greeted': self.greeted, 'messages': self.messages, 'choices': self.choices})

    def public(self):
        return {'messages': self.messages[-12:], 'streaming': self.streaming, 'activity': self.activity,
                'suggestion': self.suggestion, 'choices': self.choices, 'busy': self.busy}

class Daemon:
    def __init__(self):
        path = common.STATE/'state.json'
        self.model = Model(read(path)) if path.exists() else Model()
        self.runtime = blocking.Runtime()
        self.borders = blocking.Borders()
        self.capture = False
        self.passed = None
        self.chat = Chat()
        self.session = agent.Session(self)
        self.tools = Tools(self.model, self)
        self.selector = selectors.DefaultSelector()
        self.clients = {}
        self.done = queue.Queue()
        self.auth = False
        self.visible = False
        self.saved = self.sent_state = self.sent_chat = ''
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
            if not self.visible: toast('Focus', text)
    def turn_failed(self, text):
        self.chat.busy, self.chat.streaming, self.chat.activity = False, '', ''
        self.chat.add('system', text)

    def look(self): return blocking.screenshot()
    def open_apps(self): return blocking.open_apps()
    def installed_apps(self): return blocking.installed_apps()
    def connect_browser(self): return blocking.browser_connect()
    def suggest(self, text): self.chat.suggestion = one_line(text, 80)
    def choose(self, options, multiple):
        self.chat.choices = {'options': [one_line(o, 40) for o in options][:12], 'multiple': bool(multiple)}
        self.chat.save()
    def install_helper(self):
        if self.auth: raise ValueError('A password prompt is already showing.')
        self.auth = True
        def work():
            try: common.run([str(common.PLUGIN/'setup.sh'), '--passwordless'], timeout=180, stdin=subprocess.DEVNULL); self.done.put(('helper', ''))
            except Exception as exc: self.done.put(('helper', one_line(exc, 200) or 'failed'))
        threading.Thread(target=work, daemon=True).start()
        return 'The password prompt is on screen. Tell them so in a few words and stop; the result arrives as an event.'

    # --- state ------------------------------------------------------------------------------------

    def state(self):
        return {**self.runtime.enrich(self.model.snapshot(time.time())), 'agent': agent.available(), 'auth': self.auth, 'capture': self.capture,
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
        self.chat.suggestion, self.chat.choices = '', None
        self.chat.add('user', text)
        if agent.available(): self.session.send('<user>' + text + '</user>')
        else: self.without_agent(text, now)

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
        if self.session.busy or self.session.queue: return
        state, greeting = self.model.snapshot(time.time()), ''
        if not state['setup']: greeting = 'first_run'
        elif not state['started'] and not state['recovered']: greeting = 'morning'
        if greeting and self.chat.greeted != greeting + state['date']:
            self.chat.greeted = greeting + state['date']
            if greeting == 'first_run':
                self.chat.choices = {'options': COMMON_SITES, 'multiple': True}
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
        if op == 'ping': return reply
        if op == 'subscribe': client['subscribed'] = True
        elif op == 'say': self.say(cmd.get('text'))
        elif op == 'opened': self.opened()
        elif op == 'closed': self.visible = False
        elif op == 'blocked': self.blocked(one_line(cmd.get('name'), 80))
        elif op == 'tool' and cmd.get('name') == 'look_at_screen':
            # The card has to get out of the way first, so the answer comes later, from a thread.
            if self.capture: raise ValueError('Already looking.')
            self.capture = True
            def work():
                time.sleep(0.7)
                try: self.done.put(('capture', client, {'ok': True, 'text': self.tools.call('look_at_screen', {}, time.time())}))
                except Exception as exc: self.done.put(('capture', client, {'ok': False, 'error': one_line(exc, 200) or 'Could not capture the screen.'}))
            threading.Thread(target=work, daemon=True).start()
            return None
        elif op == 'tool': reply['text'] = self.tools.call(cmd.get('name'), cmd.get('args'), now)
        else: self.model.apply(cmd, now)
        self.settle(force=op not in ('snapshot', 'subscribe', 'say', 'opened', 'closed'))
        reply['state'] = self.state()
        if op in ('subscribe', 'say'): reply['chat'] = self.chat.public()
        if op == 'snapshot' and cmd.get('history'):
            reply['state']['history'] = sorted(copy.deepcopy(list(self.model.s['days'].values())), key=lambda d: d['date'], reverse=True)[:max(1, min(365, int(cmd['history'])))]
        return reply

    def settle(self, force=False):
        """Let time-based rules land, save, and bring the machine in line with the state."""
        now = time.time()
        for t in self.model.settle(now):
            toast('Timer finished', t['text'])
            self.event('The timer on [%s] "%s" has finished: %d minutes on the clock. Record the verdict.' % (t['id'], t['text'], t['timer']['minutes']))
        state = self.model.snapshot(now)
        if self.chat.day != state['date']:
            self.chat.day, self.chat.messages = state['date'], []
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
            try: reply = self.handle(json.loads(raw), client)
            except Exception as exc:
                self.model.s.clear(); self.model.s.update(before)
                reply = {'ok': False, 'error': str(exc) or 'Refused.'}
            if reply is not None: self.send(client, reply)
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
            if finished[0] == 'capture':
                self.capture = False
                if finished[1]['conn'] in self.clients: self.send(finished[1], finished[2])
                continue
            self.auth = False
            self.event('The system helper install ' + ('failed: ' + finished[1] if finished[1] else 'finished: it is installed.') + ' Carry on with setup.')
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
                        key.data()
                    # Streaming text publishes as it arrives; everything else on the half-second tick.
                    if self.chat.busy and time.time() - self.chat_at > 0.04:
                        self.chat_at = time.time()
                        self.publish(chat_only=True)
                    if time.time() - last >= 0.5:
                        last = time.time()
                        self.tick()
            finally:
                self.session.stop()
                self.borders.set(False)
                try: self.runtime.restore({c['address']: c for c in blocking.clients()})
                except Exception: pass
                common.SOCKET.unlink(missing_ok=True)

def serve(): Daemon().serve()
