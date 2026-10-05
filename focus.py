#!/usr/bin/python3
"""Focus entry point: the service, the CLI, the agent's tool server and the browser's native bridge."""
import argparse
import codecs
import fcntl
import json
import os
from pathlib import Path
import re
import select
import shutil
import socket
import struct
import subprocess
import sys
import time
sys.dont_write_bytecode = True
import blocking
import common
from common import read, write, run, rpc, theme
from model import Model

STATE = common.STATE

def effect(text):
    """Render real ttfx ANSI frames into plain-text grids for QML and Chromium."""
    palette = theme()
    args = ['ttfx','--no-color','--canvas-width','72','--canvas-height','14','--ignore-terminal-dimensions',
            '--frame-rate','24','--anchor-text','c','--no-eol','matrix','--rain-time','1','--resolve-delay','1']
    try:
        p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        yield {'frame': text, 'done': True}; return
    p.stdin.write(text.encode()); p.stdin.close()
    grid = [[' ']*72 for _ in range(14)]
    row = col = 0
    buf = ''
    decoder = codecs.getincrementaldecoder('utf-8')('replace')
    last = 0
    deadline = time.monotonic() + 12
    try:
        while time.monotonic() < deadline:
            ready,_,_ = select.select([p.stdout],[],[],0.05)
            if ready:
                chunk = os.read(p.stdout.fileno(), 65536)
                if not chunk: break
                buf += decoder.decode(chunk)
                while buf:
                    if buf.startswith('\x1b['):
                        m = re.match(r'\x1b\[([0-9;?]*)([A-Za-z])', buf)
                        if not m: break
                        nums = [int(n) if n.isdigit() else 0 for n in m[1].split(';')]
                        op = m[2]
                        n = nums[0] or 1
                        if op in ('H','f'): row,col = max(0,n-1), max(0,(nums[1] if len(nums)>1 else 1)-1)
                        elif op == 'A': row=max(0,row-n)
                        elif op == 'B': row+=n
                        elif op == 'C': col+=n
                        elif op == 'D': col=max(0,col-n)
                        elif op == 'G': col=n-1
                        elif op == 'J' and nums[0] == 2: grid=[[' ']*72 for _ in range(14)]; row=col=0
                        elif op == 'K' and 0<=row<14:
                            for x in range(min(col,72),72): grid[row][x]=' '
                        buf=buf[m.end():]
                    elif buf == '\x1b': break
                    else:
                        ch,buf=buf[0],buf[1:]
                        if ch=='\n': row+=1; col=0
                        elif ch=='\r': col=0
                        elif ord(ch)>=32:
                            if 0<=row<14 and 0<=col<72: grid[row][col]=ch
                            col+=1
            if time.monotonic()-last>1/24:
                yield {'frame':'\n'.join(''.join(r) for r in grid), 'done':False}
                last=time.monotonic()
    finally:
        if p.poll() is None: p.terminate()
        try: p.wait(timeout=1)
        except subprocess.TimeoutExpired: p.kill(); p.wait()
    yield {'frame':text, 'done':True}

def remaining_text(state):
    lines = ['TODAY', '']
    for t in state['tasks']:
        if t['status'] != 'passed':
            lines.append(('★ ' if t['main'] else '• ') + t['text'])
            if t['note']: lines.append('  ' + t['note'])
    return '\n'.join(lines)[:2500]

def native():
    last = ''
    def send(data):
        raw = json.dumps(data).encode()
        sys.stdout.buffer.write(struct.pack('<I',len(raw))+raw); sys.stdout.buffer.flush()
    buffer=b''
    while True:
        try:
            state=rpc({'op':'snapshot'})
            state.update(sites=state['settings']['sites'], connected=True)
            # Strip volatile timestamps to avoid unnecessary browser rule updates.
            encoded=json.dumps({k:v for k,v in state.items() if k not in ('now',)})
            if encoded!=last: send(state); last=encoded
        except (OSError,ValueError) as exc:
            # Offline recovery must clear persistent extension rules too.
            saved = read(STATE/'state.json')
            if saved.get('recovered'):
                state = Model(saved).snapshot(time.time())
                send({**state, 'theme': theme(), 'connected': True})
            else:
                send({'connected':False,'error':str(exc)})
        readable,_,_=select.select([sys.stdin.buffer],[],[],1)
        if not readable: continue
        chunk=os.read(sys.stdin.fileno(),65536)
        if not chunk: break
        buffer+=chunk
        while len(buffer)>=4:
            size=struct.unpack('<I',buffer[:4])[0]
            if size>65536: return
            if len(buffer)<size+4: break
            message=json.loads(buffer[4:4+size]); buffer=buffer[4+size:]
            if message.get('action') in ('open','blocked'):
                host = str(message.get('host') or '').removeprefix('www.')
                if not re.fullmatch(r'[a-z0-9.-]{1,253}', host): host = ''
                try: run(['omarchy-shell','local.focus','blocked',host] if message['action']=='blocked' else ['omarchy-shell','local.focus','open'])
                except Exception: pass
            elif message.get('action')=='back':
                try: run(['omarchy-shell','local.focus','close'])
                except Exception: pass
            elif message.get('action')=='effect':
                try:
                    effect_poll=time.monotonic()
                    for frame in effect(remaining_text(rpc({'op':'snapshot'}))):
                        send({'effect':frame})
                        if time.monotonic() - effect_poll > 1:
                            fresh=rpc({'op':'snapshot'}); fresh['connected']=True
                            send(fresh); effect_poll=time.monotonic()
                except Exception: pass
            elif message.get('action')=='refresh': last=''

def recover():
    if Path(blocking.HELPER).exists(): run(['pkexec', blocking.HELPER, 'recover'], timeout=90)
    try: return rpc({'op': 'recover'})
    except OSError:
        common.STATE.mkdir(parents=True, exist_ok=True)
        with (common.STATE/'service.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            path = common.STATE/'state.json'
            try: model = Model(read(path)) if path.exists() else Model()
            except (ValueError, KeyError, TypeError):
                if path.exists(): shutil.copy2(path, common.STATE/('state-corrupt-' + str(int(time.time())) + '.json'))
                model = Model()
                model.s['setup'] = True
            result = model.apply({'op': 'recover'}, time.time())
            write(path, model.s)
            runtime = blocking.Runtime()
            runtime.restore({c['address']: c for c in blocking.clients()})
            return result

def uninstall():
    """Recover first; never leave blocks behind after removing the service."""
    recover()
    blocking.browser_disconnect()
    # Let Omarchy disable and remove its own plugin. A failure stops the cleanup.
    run(['omarchy', 'plugin', 'remove', 'local.focus', '--yes'], timeout=90)
    owned = ['/usr/local/bin/focus-root-helper', '/usr/share/polkit-1/actions/local.focus.policy',
             '/etc/polkit-1/rules.d/49-local.focus.rules']
    if any(Path(path).exists() for path in owned):
        run(['pkexec', '/usr/bin/rm', '-f', '--'] + owned, timeout=90)
    link = Path.home()/'.local/bin/focusctl'
    if link.is_symlink() and link.resolve() == common.PLUGIN/'focusctl': link.unlink()
    return 'Focus removed. Restart your browser. Tasks and history are kept in ' + str(common.STATE) + '.'

def say(text):
    """Say one thing to the Focus agent and print its reply."""
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(330)
        sock.connect(str(common.SOCKET))
        stream = sock.makefile('rwb')
        def send(command):
            stream.write(json.dumps(command).encode() + b'\n'); stream.flush()
        send({'op': 'subscribe'}); json.loads(stream.readline())
        send({'op': 'say', 'text': text})
        reply = json.loads(stream.readline())
        if not reply['ok']: raise ValueError(reply['error'])
        chat = reply['chat']
        while chat['busy']:
            message = json.loads(stream.readline())
            if message.get('push') == 'chat': chat = message['chat']
        last = chat['messages'][-1] if chat['messages'] else {'role': 'user', 'text': ''}
        return last['text'] if last['role'] != 'user' else ''

def main():
    if len(sys.argv) == 1 or sys.argv[1].startswith('chrome-extension://'):
        native(); return
    p = argparse.ArgumentParser(description='Focus: tell it your day, earn your distractions back')
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('serve', 'mcp', 'status', 'apps', 'recover', 'effect'): sub.add_parser(name)
    s = sub.add_parser('say', help='say something to the Focus agent'); s.add_argument('text', nargs='+')
    c = sub.add_parser('config', help='show or change where the agent runs and what it may read')
    c.add_argument('key', nargs='?', choices=['provider', 'model', 'endpoint', 'folder', 'unfolder', 'planning']); c.add_argument('value', nargs='?', default='')
    sub.add_parser('doctor', help='check dependencies without changing anything')
    sub.add_parser('uninstall', help='recover, remove browser integration, plugin and system helper; keep history')
    sub.add_parser('forget', help='delete the conversation and any stored screenshot')
    r = sub.add_parser('rpc'); r.add_argument('payload')
    l = sub.add_parser('list'); l.add_argument('--json', action='store_true')
    v = sub.add_parser('verdict'); v.add_argument('id'); group = v.add_mutually_exclusive_group(required=True); group.add_argument('--pass', dest='passed', action='store_true'); group.add_argument('--fail', action='store_true'); v.add_argument('--note', required=True); v.add_argument('--revision', type=int)
    g = sub.add_parser('grade'); g.add_argument('word')
    h = sub.add_parser('history'); h.add_argument('--days', type=int, default=7); h.add_argument('--json', action='store_true')
    args = p.parse_args()
    if args.command == 'doctor':
        import doctor
        try: settings = rpc({'op': 'snapshot'})['settings']
        except (OSError, ValueError): settings = Model(read(common.STATE/'state.json') or None).s['settings']
        checks = doctor.checks(settings)
        for check in checks:
            print(('%s %s: %s' % ('OK' if check['ok'] else 'NEEDED' if check['required'] else 'OPTIONAL', check['name'], check['detail'])))
        if any(c['required'] and not c['ok'] for c in checks): raise SystemExit(1)
        return
    if args.command == 'uninstall':
        print(uninstall()); return
    if args.command == 'serve':
        import daemon; daemon.serve(); return
    if args.command == 'mcp':
        import mcp; mcp.serve(); return
    if args.command == 'effect':
        for frame in effect(remaining_text(rpc({'op': 'snapshot'}))): print(json.dumps(frame), flush=True)
        return
    if args.command == 'say':
        print(say(' '.join(args.text))); return
    if args.command == 'config':
        # Straight to the service's settings: this works whether or not any model is reachable.
        if args.key:
            roots = rpc({'op': 'snapshot'})['settings']['roots']
            target = str(Path(args.value).expanduser())
            values = {'roots': roots + [target]} if args.key == 'folder' else {'roots': [r for r in roots if r != target]} if args.key == 'unfolder' else {args.key: args.value}
            rpc({'op': 'settings', 'values': values})
            time.sleep(0.2)
        state = rpc({'op': 'snapshot'})
        result = {'planning': state['settings']['planning'], 'backend': state['backend'], 'endpoint': state['settings']['endpoint'], 'folders': state['settings']['roots']}
    elif args.command == 'forget': rpc({'op': 'forget'}); result = 'Forgotten.'
    elif args.command == 'recover': result = recover()
    elif args.command == 'rpc': result = rpc(json.loads(args.payload))
    elif args.command == 'apps': result = blocking.open_apps()
    elif args.command == 'verdict': result = rpc({'op': 'verdict', 'id': args.id, 'verdict': 'pass' if args.passed else 'fail', 'note': args.note, 'revision': args.revision})
    elif args.command == 'grade': result = rpc({'op': 'grade', 'word': args.word})
    elif args.command == 'history': result = rpc({'op': 'snapshot', 'history': args.days})['history']
    elif args.command == 'list': result = rpc({'op': 'snapshot'})['tasks']
    else: result = rpc({'op': 'snapshot'})
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    try: main()
    except (BrokenPipeError, KeyboardInterrupt): pass
    except Exception as exc:
        print(str(exc), file=sys.stderr); sys.exit(1)
