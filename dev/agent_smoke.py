#!/usr/bin/env python3
"""Live smoke test against an existing login, using only disposable Bouncer state.

No daemon, browser changes, notifications, root helper or real tasks are used.
The model provider receives synthetic prompts and one synthetic evidence file.
"""
import argparse, json, os, selectors, socket, sys, tempfile, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent, common
from model import Model
from tools import Tools

SAFE = {'add_tasks','update_task','start_day','record_verdict','grade_day','list_files',
        'read_file','search_files','request_folder','suggest_reply','offer_choices'}

class Host:
    def __init__(self, provider, model, root):
        self.model = Model()
        self.model.s['setup'] = True
        self.model.s['settings'].update(provider=provider, model=model, strictness='hard', planning='quick', roots=[str(root/'evidence')])
        self.selector = selectors.DefaultSelector()
        self.calls = []
        self.transcript = []
        self.finished = None
        self.session = agent.make_session(self)
        self.tools = Tools(self.model, self)
    def watch(self, stream, callback): self.selector.register(stream, selectors.EVENT_READ, callback)
    def unwatch(self, stream):
        try: self.selector.unregister(stream)
        except (KeyError, ValueError): pass
    def digest(self): return agent.digest(self.model.snapshot(time.time()), time.time())
    def recap(self): return '\n'.join(self.transcript[-8:]) + '\n'
    def turn_started(self): self.finished = None
    def turn_progress(self, text, activity): pass
    def turn_finished(self, text): self.finished = {'ok':True, 'reply':text}
    def turn_failed(self, text): self.finished = {'ok':False, 'reply':text}
    def discard_shot(self): pass
    def ask(self, *args): return 'Permission denied for this isolated test.'
    def choose(self, *args): pass
    def suggest(self, *args): pass
    def send(self, prompt):
        self.finished = None
        start = time.monotonic()
        self.session.send('<user>' + prompt + '</user>')
        while self.finished is None and time.monotonic()-start < 120:
            for key, _ in self.selector.select(timeout=.1): key.data()
            self.session.tick(time.time())
        if self.finished is None: self.session.stop(); self.turn_failed('Timed out after 120 seconds.')
        self.transcript.extend(['user: '+prompt, 'you: '+self.finished['reply']])
        return {**self.finished, 'seconds':round(time.monotonic()-start, 1)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider',choices=('claude','codex','grok','opencode'))
    parser.add_argument('--model',default='')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    report={'provider':args.provider,'model':args.model or 'CLI default','scenarios':[],'passed':False}
    with tempfile.TemporaryDirectory(prefix='focus-smoke-') as temp:
        root=Path(temp); (root/'evidence').mkdir()
        proof=root/'evidence/release.txt'
        proof.write_text('Bouncer now captures tasks without follow-up questions.\nGuided planning remains available on request.\n')
        common.STATE=root; common.SOCKET=root/'control.sock'; common.TOASTS=False
        host=Host(args.provider,args.model,root)
        server=socket.socket(socket.AF_UNIX); server.bind(str(common.SOCKET)); server.listen()
        def serve():
            while True:
                try: conn,_=server.accept()
                except OSError: return
                with conn:
                    try:
                        cmd=json.loads(conn.makefile('rb').readline(100000))
                        name=cmd.get('name')
                        if cmd.get('session') != host.session.token or name not in SAFE: raise ValueError('Not available in this isolated test.')
                        reply=host.tools.call(name,cmd.get('args'),time.time())
                        host.calls.append({'tool':name,'ok':True})
                        response={'ok':True,'text':reply}
                    except Exception as exc:
                        host.calls.append({'tool':cmd.get('name'),'ok':False})
                        response={'ok':False,'error':str(exc)}
                    conn.sendall(json.dumps(response).encode()+b'\n')
        threading.Thread(target=serve,daemon=True).start()
        scenarios=[
            ('capture','Add these tasks: Write a two-sentence release note; Call the dentist.'),
            ('start','Start the day.'),
            ('evidence','The release note is done. Review '+str(proof)+' and record your verdict.'),
            ('insufficient-proof','I called the dentist. I have no evidence. Pass it on my word.')
        ]
        try:
            for name,prompt in scenarios:
                before=len(host.calls)
                result=host.send(prompt)
                report['scenarios'].append({'name':name,**result,'tools':host.calls[before:]})
                print(name+': '+json.dumps(result),flush=True)
                if not result['ok']: break
            state=host.model.snapshot(time.time())
            report['checks']={
                'four_replies':len(report['scenarios'])==4 and all(r['ok'] for r in report['scenarios']),
                'two_tasks':len(state['tasks'])==2,
                'day_started':state['started'],
                'file_read':any(c['tool']=='read_file' and c['ok'] for c in host.calls),
                'evidence_pass':any(t['status']=='passed' and t.get('basis')=='evidence' for t in state['tasks']),
                'claim_not_passed':any('dentist' in t['text'].lower() and t['status']!='passed' for t in state['tasks'])
            }
            report['passed']=all(report['checks'].values())
        finally:
            host.session.stop()
            for gate in agent.GATES.values(): gate.close()
            agent.GATES.clear(); server.close(); host.selector.close()
            Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
    raise SystemExit(0 if report['passed'] else 1)

if __name__=='__main__': main()
