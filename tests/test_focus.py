import copy
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Model, task
import blocking
import common
import focus
from tools import Tools, TOOLS

class StateTests(unittest.TestCase):
    def setUp(self):
        self.m=Model(); self.m.s['setup']=True; self.now=time.mktime((2026,10,2,10,0,0,0,0,-1)); self.m.tick(self.now)
    def call(self,op,**kw):
        if op=='verdict': kw.setdefault('by','agent')
        return self.m.apply({'op':op,**kw},self.now)
    def start(self, count=2, mode='all'):
        self.call('settings',values={'mode':mode})
        for i in range(count): self.call('add',text='Task '+str(i))
        self.ids=[t['id'] for t in self.m.snapshot(self.now)['tasks']]
        self.call('change',id=self.ids[0],action='main'); self.call('start')
    def test_start_requires_main(self):
        self.call('add',text='Build')
        with self.assertRaises(ValueError): self.call('start')
        self.assertTrue(self.m.snapshot(self.now)['locked'])
    def test_agent_only_verdict_and_notes(self):
        self.start()
        with self.assertRaises(ValueError): self.call('done',id=self.ids[0])
        self.call('verdict',id=self.ids[0],verdict='fail',note='The diff remains unconvinced.')
        s=self.call('verdict',id=self.ids[1],verdict='pass',note='Tests pass. Acceptable.')
        self.assertTrue(s['locked']); self.assertEqual(s['completed'],1)
        s=self.call('verdict',id=self.ids[0],verdict='pass',note='The missing path is now covered.')
        self.assertFalse(s['locked']); self.assertEqual(s['streak'],1)
    def test_edit_delay_persists_and_invalidates(self):
        self.start(1); self.call('verdict',id=self.ids[0],verdict='pass',note='Checked.')
        self.call('change',id=self.ids[0],action='edit',text='New scope')
        self.m=Model(json.loads(json.dumps(self.m.s)))
        with self.assertRaises(ValueError): self.call('commit',id=self.ids[0])
        self.now+=30
        s=self.call('commit',id=self.ids[0]); self.assertTrue(s['locked']); self.assertEqual(s['tasks'][0]['revision'],2)
        self.assertEqual(len(s['tasks'][0]['verdicts']),1)
    def test_main_cannot_be_deleted_after_start(self):
        self.start()
        with self.assertRaises(ValueError): self.call('change',id=self.ids[0],action='delete')
    def test_delete_delay_and_cancel(self):
        self.start(); self.call('change',id=self.ids[1],action='delete'); self.call('cancel',id=self.ids[1]); self.now+=31
        with self.assertRaises(ValueError): self.call('commit',id=self.ids[1])
        self.call('change',id=self.ids[1],action='delete'); self.now+=30
        self.assertEqual(self.call('commit',id=self.ids[1])['total'],1)
    def test_earned_time_is_once_per_task(self):
        self.start(mode='earn')
        s=self.call('verdict',id=self.ids[1],verdict='pass',note='Verified.')
        self.assertFalse(s['locked']); deadline=s['earnedUntil']
        self.now+=10
        self.call('verdict',id=self.ids[1],verdict='fail',note='Regression found.')
        s=self.call('verdict',id=self.ids[1],verdict='pass',note='Repaired.')
        self.assertEqual(s['earnedUntil'],deadline)
        self.now=deadline+1; self.assertTrue(self.m.snapshot(self.now)['locked'])
    def test_add_after_full_unlock_relocks(self):
        self.start(1); self.call('verdict',id=self.ids[0],verdict='pass',note='Verified.')
        self.assertTrue(self.call('add',text='Another task')['locked'])
    def test_override_code_countdown_expiry_log(self):
        self.start(); s=self.call('challenge'); code=s['challenge']['code']; self.assertEqual(len(code),32)
        with self.assertRaises(ValueError): self.call('challenge-submit',code='wrong')
        self.call('challenge-submit',code=code); self.now+=59
        with self.assertRaises(ValueError): self.call('override')
        self.now+=1; s=self.call('override'); self.assertFalse(s['locked']); self.assertEqual(len(s['overrides']),1)
        self.now+=900; self.assertTrue(self.m.snapshot(self.now)['locked'])
    def test_override_does_not_reset_countdown(self):
        self.start(); s=self.call('challenge'); self.call('challenge-submit',code=s['challenge']['code']); deadline=self.m.snapshot(self.now)['challenge']['readyAt']
        self.now+=20; self.call('challenge-submit',code=s['challenge']['code']); self.assertEqual(self.m.snapshot(self.now)['challenge']['readyAt'],deadline)
    def test_boundary_carry_and_skipped_days(self):
        self.start(); old=self.m.s['current']; self.now=time.mktime((2026,10,3,3,59,59,0,0,-1))
        self.assertEqual(self.m.snapshot(self.now)['date'],old)
        self.now+=1; s=self.m.snapshot(self.now); self.assertFalse(s['started']); self.assertEqual(len(s['carry']),2)
        self.now+=86400; self.assertEqual(len(self.m.snapshot(self.now)['carry']),2)
        self.call('carry',id=self.ids[0],action='carry'); self.call('carry',id=self.ids[1],action='drop')
        s=self.m.snapshot(self.now); self.assertEqual(len(s['tasks']),1); self.assertNotEqual(s['tasks'][0]['id'],self.ids[0]); self.assertEqual(len(s['decisions']),2)
    def test_recovery_persists_until_start(self):
        self.start(); self.call('recover'); self.now+=86400
        s=self.m.snapshot(self.now); self.assertFalse(s['locked']); self.assertTrue(s['recovered'])
    def test_settings_cannot_bypass_after_start(self):
        self.call('settings',values={'sites':['youtube.com']}); self.start()
        for values in ({'sites':[]},{'mode':'earn'},{'reset':'23:00'}):
            with self.assertRaises(ValueError): self.call('settings',values=values)
    def test_invalid_inputs(self):
        for values in ({'sites':['youtube.com\n127.0.0.1']},{'reset':'24:00'},{'minutes':True}):
            with self.assertRaises(ValueError): self.call('settings',values=values)
        with self.assertRaises(ValueError): self.call('grade',word='two words')
    def test_stale_agent_review(self):
        self.start()
        with self.assertRaises(ValueError): self.call('verdict',id=self.ids[0],verdict='pass',note='Verified.',revision=8)
    def test_plan_accept_sets_main_only_before_start(self):
        s=self.call('plan-accept',tasks=[{'text':'Emails','check':'Inbox handled'},{'text':'Call mum','check':''}],main=1)
        self.assertEqual([t['main'] for t in s['tasks']],[False,True]); self.assertEqual(s['tasks'][0]['check'],'Inbox handled')
        self.call('start'); s=self.call('plan-accept',tasks=[{'text':'Bills'}],main=0)
        self.assertEqual([t['main'] for t in s['tasks']],[False,True,False])
    def test_claimed_pass_is_recorded_as_claim(self):
        self.start(1); s=self.call('verdict',id=self.ids[0],verdict='pass',note='Plausible.',basis='claim')
        self.assertEqual(s['tasks'][0]['basis'],'claim'); self.assertFalse(s['locked'])
        with self.assertRaises(ValueError): self.call('verdict',id=self.ids[0],verdict='pass',note='No.',basis='vibes')
    def test_external_verdict_unlocks_but_never_streaks(self):
        self.start(1); s=self.call('verdict',id=self.ids[0],verdict='pass',note='Said so.',by=None)
        self.assertFalse(s['locked']); self.assertEqual(s['tasks'][0]['by'],'external'); self.assertEqual(s['streak'],0)
        self.assertEqual(self.call('verdict',id=self.ids[0],verdict='pass',note='Reviewed.')['streak'],1)
    def test_nothing_blocks_before_setup(self):
        m=Model(); self.assertFalse(m.snapshot(self.now)['locked']); self.assertFalse(m.snapshot(self.now)['setup'])
        self.assertTrue(m.apply({'op':'setup-done'},self.now)['locked'])
        self.assertTrue(Model({'version':3,'settings':{},'days':{},'current':'','recovered':False}).snapshot(self.now)['setup'])
    def test_cooling_off_lands_by_itself(self):
        self.start(); self.call('change',id=self.ids[1],action='delete'); self.m.settle(self.now+29)
        self.assertEqual(self.m.snapshot(self.now)['total'],2)
        self.now+=30; self.m.settle(self.now); self.assertEqual(self.m.snapshot(self.now)['total'],1)
        # A change the rules now refuse is dropped rather than retried forever.
        self.call('change',id=self.ids[0],action='edit',text='New words'); self.m.tick(self.now)['tasks'][0]['revision']=9
        self.now+=30; self.m.settle(self.now); self.assertEqual(self.m.snapshot(self.now)['pending'],{})
    def test_emergency_unlock_opens_by_itself(self):
        self.start(); s=self.call('challenge'); self.call('challenge-submit',code=s['challenge']['code'])
        self.m.settle(self.now+59); self.assertTrue(self.m.snapshot(self.now+59)['locked'])
        self.m.settle(self.now+60); s=self.m.snapshot(self.now+60); self.assertFalse(s['locked']); self.assertEqual(len(s['overrides']),1)
    def test_modes_set_the_proof_and_the_rules(self):
        self.call('settings',values={'strictness':'hard'}); self.call('add',text='Call mum'); self.call('add',text='Ship it'); self.call('add',text='Read')
        ids=[t['id'] for t in self.m.snapshot(self.now)['tasks']]
        self.call('trust',id=ids[0],value=True); self.call('change',id=ids[1],action='main'); self.call('start')
        with self.assertRaises(ValueError): self.call('trust',id=ids[2],value=True)
        with self.assertRaises(ValueError): self.call('verdict',id=ids[2],verdict='pass',note='Said so.',basis='claim')
        self.call('verdict',id=ids[2],verdict='fail',note='Show me.',basis='claim')
        self.call('verdict',id=ids[0],verdict='pass',note='Agreed this morning.',basis='claim')
        with self.assertRaises(ValueError): self.call('settings',values={'strictness':'honor'})
        self.call('change',id=ids[2],action='edit',text='Read a chapter'); self.m.settle(self.now+119)
        self.assertEqual(self.m.snapshot(self.now)['tasks'][2]['text'],'Read'); self.m.settle(self.now+120)
        self.assertEqual(self.m.snapshot(self.now)['tasks'][2]['text'],'Read a chapter')
        s=self.call('challenge'); self.call('challenge-submit',code=s['challenge']['code']); self.m.settle(self.now+60)
        self.now+=1000
        with self.assertRaises(ValueError): self.call('challenge')
        self.call('settings',values={'strictness':'lockdown'})
        with self.assertRaises(ValueError): self.call('verdict',id=ids[2],verdict='pass',note='Read it.',basis='evidence')
        with self.assertRaises(ValueError): self.call('change',id=ids[2],action='delete')
        self.call('verdict',id=ids[1],verdict='pass',note='Shipped.',basis='evidence')
        self.assertFalse(self.call('verdict',id=ids[2],verdict='pass',note='Read it.',basis='evidence')['locked'])
    def test_timer_finishes_once_and_yesterday_is_summarised(self):
        self.start(1)
        with self.assertRaises(ValueError): self.call('timer',id=self.ids[0],minutes=0)
        self.call('timer',id=self.ids[0],minutes=30); self.assertEqual(self.m.settle(self.now+1799),[])
        done=self.m.settle(self.now+1800); self.assertEqual([t['id'] for t in done],self.ids); self.assertEqual(self.m.settle(self.now+1801),[])
        self.call('verdict',id=self.ids[0],verdict='pass',note='Thirty on the clock.'); self.call('grade',word='Solid')
        self.assertIsNone(self.m.snapshot(self.now)['yesterday'])
        self.assertEqual(self.m.snapshot(self.now+86400)['yesterday'],{'date':'2026-10-02','completed':1,'total':1,'grade':'Solid'})
    def test_override_disqualifies_streak(self):
        self.start(1); s=self.call('challenge'); self.call('challenge-submit',code=s['challenge']['code']); self.now+=60; self.call('override')
        s=self.call('verdict',id=self.ids[0],verdict='pass',note='Checked.'); self.assertEqual(s['streak'],0)

loader=importlib.machinery.SourceFileLoader('root_helper',str(Path(__file__).resolve().parents[1]/'setup/focus-root-helper'))
spec=importlib.util.spec_from_loader(loader.name,loader); helper=importlib.util.module_from_spec(spec); loader.exec_module(helper)
class HelperTests(unittest.TestCase):
    def test_preserves_other_hosts_content(self):
        original='127.0.0.1 localhost\n# another tool\n10.1.1.2 internal\n'
        updated=helper.hosts_content(original,['youtube.com'])
        self.assertIn(':: www.youtube.com',updated)
        self.assertEqual(helper.hosts_content(updated,[]),original)
        self.assertEqual(helper.hosts_content(updated,['youtube.com']),updated)
    def test_broken_markers_refused(self):
        with self.assertRaises(ValueError): helper.hosts_content(helper.BEGIN+'\nother\n',[])
    def test_injection_rejected(self):
        for site in ('a.com\n1.2.3.4 bank.com','*.com','/etc/passwd','a.com;id','-a.com'):
            with self.assertRaises(ValueError): helper.validate({'locked':True,'hosts':True,'sites':[site]})
        with self.assertRaises(ValueError): helper.validate({'locked':True,'hosts':False,'sites':[],'path':'/etc/passwd'})
    def test_recover_removes_only_owned_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); hosts=root/'hosts'; hosts.write_text('127.0.0.1 localhost\n')
            policies=tuple(root/str(i)/'local.focus.json' for i in range(3))
            for p in policies: p.parent.mkdir()
            other=policies[0].parent/'other.json'; other.write_text('{"OtherSetting":true}')
            with patch.object(helper,'HOSTS',hosts),patch.object(helper,'POLICIES',policies),patch.object(helper,'BINARIES',((sys.executable,),)*3),patch.object(helper,'safe'):
                helper.apply({'locked':True,'hosts':True,'sites':['example.com']})
                self.assertTrue(all(p.exists() for p in policies))
                helper.apply({'locked':False,'hosts':False,'sites':[]})
                self.assertFalse(any(p.exists() for p in policies)); self.assertTrue(other.exists()); self.assertEqual(hosts.read_text(),'127.0.0.1 localhost\n')
    def test_conflict_prevents_any_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/'local.focus.json'; (root/'other.json').write_text('{"URLBlocklist":["other.com"]}')
            with patch.object(helper,'POLICIES',(p,)),patch.object(helper,'BINARIES',((sys.executable,),)),patch.object(helper,'safe'):
                with self.assertRaises(ValueError): helper.apply({'locked':True,'hosts':False,'sites':['example.com']})
                self.assertFalse(p.exists())

class Host:
    def __init__(self): self.suggested=''; self.installs=0
    def open_apps(self): return ['discord','foot']
    def connect_browser(self): return ['chromium']
    def suggest(self,text): self.suggested=text
    def install_helper(self): self.installs+=1; return 'Prompt showing.'

class ToolTests(unittest.TestCase):
    def setUp(self):
        self.m=Model(); self.host=Host(); self.tools=Tools(self.m,self.host); self.now=time.mktime((2026,10,2,10,0,0,0,0,-1)); self.m.tick(self.now)
    def call(self,name,**args): return self.tools.call(name,args,self.now)
    def state(self): return self.m.snapshot(self.now)
    def test_every_tool_is_implemented(self):
        for definition in TOOLS: self.assertTrue(hasattr(self.tools,'tool_'+definition['name']),definition['name'])
    def test_setup_then_a_whole_day(self):
        self.assertIn('x.com',self.call('block',sites=['YouTube.com','https://x.com/home'],apps=['discord']))
        self.assertEqual(self.call('list_apps'),'Open window classes: discord, foot')
        self.call('set_rules',mode='earn',minutes=20); self.call('install_blocking_helper'); self.assertEqual(self.host.installs,1)
        self.assertFalse(self.state()['locked']); self.call('finish_setup'); self.assertTrue(self.state()['locked'])
        self.call('add_tasks',tasks=[{'text':'Emails','check':'Inbox handled'},{'text':'Call mum'}]); ids=[t['id'] for t in self.state()['tasks']]
        with self.assertRaises(ValueError): self.call('start_day')
        self.assertEqual(self.call('update_task',id=ids[1],main=True,check='She picked up'),'Task check updated, is now the main task.')
        self.call('start_day'); self.call('suggest_reply',text='yes'); self.assertEqual(self.host.suggested,'yes')
        with self.assertRaises(ValueError): self.call('unblock',sites=['youtube.com'])
        self.assertIn('x.com',self.call('block',sites=['reddit.com']))
        self.assertIn('30 seconds',self.call('remove_task',id=ids[0])); self.call('cancel_change',id=ids[0])
        with self.assertRaises(ValueError): self.call('cancel_change',id=ids[0])
        self.assertIn('1 left',self.call('record_verdict',id=ids[0],passed=True,note='Inbox is empty.',basis='evidence'))
        self.assertFalse(self.state()['locked'])  # earn mode: the first pass buys time
        self.assertIn('Everything has passed',self.call('record_verdict',id=ids[1],passed=True,note='Specific enough.',basis='claim'))
        s=self.state(); self.assertEqual(s['streak'],1); self.assertEqual(s['tasks'][1]['basis'],'claim'); self.assertEqual(s['tasks'][1]['by'],'agent')
        self.call('grade_day',word='Solid work',note='Two for two.'); self.assertEqual(self.state()['grade'],'Solid')
    def test_carry_over_and_emergency(self):
        self.m.s['setup']=True; self.call('add_tasks',tasks=[{'text':'Old one'},{'text':'Old two'}]); self.now+=86400
        ids=[t['id'] for t in self.state()['carry']]
        self.call('carry_over',ids=ids[:1],keep=True); self.call('carry_over',ids=ids[1:],keep=False)
        s=self.state(); self.assertEqual([t['text'] for t in s['tasks']],['Old one']); self.assertEqual(s['carry'],[])
        with self.assertRaises(ValueError): self.call('emergency_unlock')
        self.call('update_task',id=s['tasks'][0]['id'],main=True); self.call('start_day'); self.call('emergency_unlock')
        self.assertEqual(len(self.state()['challenge']['code']),32)
    def test_unknown_tool_refused(self):
        with self.assertRaises(ValueError): self.call('rm_rf')

class RuntimeTests(unittest.TestCase):
    def test_webapps_and_exact_app_classes(self):
        settings={'sites':['youtube.com'],'apps':['Discord']}
        self.assertTrue(blocking.matches({'class':'chrome-youtube.com__-Default'},settings))
        self.assertTrue(blocking.matches({'class':'chrome-m.youtube.com__-Profile_1'},settings))
        self.assertTrue(blocking.matches({'initialClass':'discord'},settings))
        self.assertFalse(blocking.matches({'class':'chrome-notyoutube.com__-Default'},settings))
    def test_restore_preserves_workspace_pin_and_pid(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(common,'STATE',Path(tmp)):
            runtime=blocking.Runtime(); runtime.held={'0xabc':{'pid':2,'workspace':'3','pinned':True}}
            with patch.object(blocking,'dispatch') as move,patch.object(runtime,'save_held'):
                runtime.restore({'0xabc':{'pid':2,'pinned':False}})
                self.assertEqual(move.call_count,2); self.assertEqual(runtime.held,{})
    def test_recovery_handles_corrupt_state_without_losing_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp); (state/'state.json').write_text('{broken')
            with patch.object(common,'STATE',state),patch.object(common,'SOCKET',state/'missing.sock'),patch.object(blocking,'HELPER','/nonexistent/focus-test'),patch.object(blocking,'clients',return_value=[]):
                result=focus.recover()
            self.assertTrue(result['recovered']); self.assertFalse(result['locked'])
            backups=list(state.glob('state-corrupt-*.json')); self.assertEqual(len(backups),1)
            self.assertEqual(backups[0].read_text(),'{broken')
    def test_browser_connect_extends_flags_and_registers_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp); (home/'.config').mkdir(); flags=home/'.config/chromium-flags.conf'
            flags.write_text('--ozone-platform=wayland\n--load-extension=/usr/share/other\n')
            with patch.object(blocking.Path,'home',return_value=home),patch.object(blocking.shutil,'which',return_value=None):
                self.assertEqual(blocking.browser_status(),{'extension':False,'host':False})
                blocking.browser_connect(); self.assertEqual(blocking.browser_connect(),['chromium'])
                self.assertEqual(blocking.browser_status(),{'extension':True,'host':True})
            extension=str(common.PLUGIN/'browser')
            self.assertEqual(flags.read_text(),'--ozone-platform=wayland\n--load-extension=/usr/share/other,'+extension+'\n')
            self.assertEqual((home/'.config/chromium-flags.conf.before-focus').read_text().count('focus'),0)
            host=json.loads((home/'.config/chromium/NativeMessagingHosts/local.omarchy.focus.json').read_text())
            self.assertEqual(host['allowed_origins'],['chrome-extension://'+blocking.extension_id(extension)+'/'])
        # Pinned so a change to the derivation is noticed; the formula was checked against an id Chromium assigned.
        self.assertEqual(blocking.extension_id('/home/user/.config/omarchy/plugins/local.focus/browser'),'ddlcfpcpogihbkdojjfgljoapmdeomeg')

# Speaks the agent's streaming protocol and drives Focus through the same tool op the real tool server uses.
FAKE_AGENT="""#!/usr/bin/python3
import json,os,re,socket,sys,time
def tool(name,**args):
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(os.environ['FOCUS_STATE_HOME']+'/control.sock'); s.sendall(json.dumps({'op':'tool','name':name,'args':args}).encode()+b'\\n')
        return json.loads(s.makefile().readline())
def out(o): print(json.dumps(o),flush=True); time.sleep(.08)
for line in sys.stdin:
    text=json.loads(line)['message']['content'][0]['text']
    said=text.rsplit('<user>',1)[-1].split('</user>')[0] if '<user>' in text else ''
    ids=re.findall(r'\\[([0-9a-f]{12})\\]',text)
    if '<event>' in text: tool('suggest_reply',text='not much'); reply='Morning. What is today?'
    elif said=='crash': sys.exit(3)
    elif said.startswith('today'): tool('add_tasks',tasks=[{'text':'Emails','check':'Inbox handled'},{'text':'Call mum'}]); reply='Which matters most?'
    elif said=='start': tool('update_task',id=ids[0],main=True); tool('start_day'); reply='Started.'
    elif said=='unblock youtube': reply='Refused.' if not tool('unblock',sites=['youtube.com'])['ok'] else 'Unblocked.'
    elif said=='done': [tool('record_verdict',id=i,passed=True,note='Fine.',basis='claim') for i in ids]; reply='Unlocked.'
    else: reply='Earlier: '+str('<earlier_today>' in text)
    out({'type':'stream_event','event':{'type':'content_block_delta','delta':{'type':'text_delta','text':reply[:4]}}})
    out({'type':'assistant','message':{'content':[{'type':'text','text':'Thinking aloud.'},{'type':'tool_use','name':'Read','input':{'file_path':'/x/notes.md'}}]}})
    out({'type':'assistant','message':{'content':[{'type':'text','text':reply}]}})
    out({'type':'result','is_error':False,'result':reply})
"""

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)
        fake=self.path/'agent'; fake.write_text(FAKE_AGENT); fake.chmod(0o700)
        model=Model(); model.s['setup']=True; model.s['settings']['sites']=['youtube.com']; common.write(self.path/'state.json',model.s)
        self.env={**os.environ,'FOCUS_STATE_HOME':self.tmp.name,'FOCUS_AGENT_CMD':str(fake),'PYTHONPATH':str(Path(focus.__file__).parent)}
        code="import blocking,daemon; blocking.HELPER='/nonexistent/focus-test'; blocking.clients=lambda: []; daemon.serve()"
        self.proc=subprocess.Popen([sys.executable,'-c',code],env=self.env,stderr=subprocess.PIPE)
        self.socket=patch.object(common,'SOCKET',self.path/'control.sock'); self.socket.start()
        for _ in range(100):
            if (self.path/'control.sock').exists(): break
            time.sleep(.02)
    def tearDown(self):
        self.socket.stop(); self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stderr.close(); self.tmp.cleanup()
    def test_plain_commands_and_restart_safe_state(self):
        s=common.rpc({'op':'add','text':'Integration task'}); ident=s['tasks'][0]['id']
        common.rpc({'op':'change','action':'main','id':ident}); common.rpc({'op':'start'})
        s=common.rpc({'op':'verdict','id':ident,'verdict':'pass','note':'Socket path verified.'}); self.assertFalse(s['locked']); self.assertEqual(s['tasks'][0]['by'],'external')
        self.assertEqual(len(common.rpc({'op':'snapshot','history':7})['history']),1)
        with self.assertRaises(ValueError): common.rpc({'op':'verdict','id':'missing','verdict':'pass','note':'No.'})
        self.assertEqual(common.rpc({'op':'snapshot'})['completed'],1)
        self.assertEqual(json.loads((self.path/'state.json').read_text())['days'][s['date']]['tasks'][0]['verdict'],'pass')
    def test_a_day_by_conversation(self):
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(10); sock.connect(str(self.path/'control.sock')); stream=sock.makefile('rwb')
            def send(command): stream.write(json.dumps(command).encode()+b'\n'); stream.flush()
            send({'op':'subscribe'}); first=json.loads(stream.readline()); self.assertEqual(first['chat']['messages'],[])
            send({'op':'opened'}); seen=[]
            while not (seen and not seen[-1]['busy'] and seen[-1]['messages']):
                message=json.loads(stream.readline())
                if message.get('push')=='chat': seen.append(message['chat'])
            self.assertEqual(seen[-1]['messages'][-1],{**seen[-1]['messages'][-1],'role':'agent','text':'Morning. What is today?'})
            self.assertEqual(seen[-1]['suggestion'],'not much')
            self.assertTrue(any(c['busy'] and c['activity']=='reading notes.md' for c in seen))
            self.assertTrue(any(c['streaming']=='Morn' for c in seen),[(c['busy'],c['streaming'],c['activity']) for c in seen])
        self.assertEqual(focus.say('today: emails and mum'),'Which matters most?')
        s=common.rpc({'op':'snapshot'}); self.assertEqual([t['text'] for t in s['tasks']],['Emails','Call mum']); self.assertEqual(s['tasks'][0]['check'],'Inbox handled')
        self.assertEqual(focus.say('start'),'Started.'); self.assertTrue(common.rpc({'op':'snapshot'})['locked'])
        self.assertEqual(focus.say('unblock youtube'),'Refused.'); self.assertEqual(common.rpc({'op':'snapshot'})['settings']['sites'],['youtube.com'])
        self.assertEqual(focus.say('done'),'Unlocked.')
        s=common.rpc({'op':'snapshot'}); self.assertFalse(s['locked']); self.assertEqual(s['streak'],1)
        # A dead agent is reported and replaced, and the new one is told what was said earlier.
        self.assertIn('stopped',focus.say('crash')); self.assertEqual(focus.say('still there?'),'Earlier: True')
        chat=json.loads((self.path/'chat.json').read_text()); self.assertEqual(chat['messages'][0]['text'],'Morning. What is today?')
    def test_first_run_opens_with_a_fixed_line(self):
        self.tearDown(); self.setUp_fresh=True
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)
        self.env={**self.env,'FOCUS_STATE_HOME':self.tmp.name}
        code="import blocking,daemon; blocking.HELPER='/nonexistent/focus-test'; blocking.clients=lambda: []; daemon.serve()"
        self.proc=subprocess.Popen([sys.executable,'-c',code],env=self.env,stderr=subprocess.PIPE)
        self.socket=patch.object(common,'SOCKET',self.path/'control.sock'); self.socket.start()
        for _ in range(100):
            if (self.path/'control.sock').exists(): break
            time.sleep(.02)
        self.assertFalse(common.rpc({'op':'snapshot'})['introduced'])
        common.request({'op':'opened'}); common.request({'op':'opened'})
        self.assertTrue(common.rpc({'op':'snapshot'})['introduced'])
        chat=json.loads((self.path/'chat.json').read_text())
        self.assertEqual([m['role'] for m in chat['messages']],['agent']); self.assertIn('Which ones waste your time?',chat['messages'][0]['text'])
    def test_emergency_code_never_reaches_the_agent(self):
        focus.say('today: x'); focus.say('start'); common.request({'op':'tool','name':'emergency_unlock','args':{}})
        code=common.rpc({'op':'snapshot'})['challenge']['code']
        self.assertEqual(focus.say(code),'Code accepted. Unlocking in 60 seconds.')
        self.assertIsNotNone(common.rpc({'op':'snapshot'})['challenge']['readyAt'])
    def test_tool_server_speaks_mcp(self):
        server=subprocess.Popen([sys.executable,str(Path(focus.__file__)),'mcp'],env=self.env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        def ask(ident,method,params=None):
            server.stdin.write(json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params or {}})+'\n'); server.stdin.flush()
            return json.loads(server.stdout.readline())
        try:
            self.assertEqual(ask(1,'initialize',{'protocolVersion':'2025-06-18'})['result']['protocolVersion'],'2025-06-18')
            server.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n')
            self.assertEqual(len(ask(2,'tools/list')['result']['tools']),len(TOOLS))
            result=ask(3,'tools/call',{'name':'add_tasks','arguments':{'tasks':[{'text':'From the tool server'}]}})['result']
            self.assertIn('From the tool server',result['content'][0]['text']); self.assertEqual(common.rpc({'op':'snapshot'})['total'],1)
            refused=ask(4,'tools/call',{'name':'start_day','arguments':{}})['result']
            self.assertTrue(refused['isError']); self.assertIn('main task',refused['content'][0]['text'])
        finally:
            server.stdin.close(); server.wait(timeout=5); server.stdout.close()

if __name__=='__main__': unittest.main()
