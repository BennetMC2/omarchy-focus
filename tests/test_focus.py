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
import agent
import backend
import evidence
import http.server
import shutil
import threading

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
    def test_planning_defaults_migrates_and_persists(self):
        self.assertEqual(self.m.s['settings']['planning'], 'quick')
        old=copy.deepcopy(self.m.s); old['settings'].pop('planning')
        self.assertEqual(Model(old).s['settings']['planning'], 'quick')
        self.call('settings', values={'planning':'guided'})
        saved=json.loads(json.dumps(self.m.s))
        restored=Model(saved)
        self.assertEqual(restored.s['settings']['planning'], 'guided')
        self.assertIn('planning style: guided', agent.digest(restored.snapshot(self.now), self.now))
        before=copy.deepcopy(self.m.s['settings'])
        for invalid in ('chatty', '', None, [], 1):
            with self.assertRaises(ValueError): self.call('settings', values={'planning':invalid})
            self.assertEqual(self.m.s['settings'], before)

    def test_quick_planning_does_not_relax_hard_review(self):
        self.call('settings', values={'strictness':'hard', 'planning':'guided'})
        self.start()
        self.call('settings', values={'planning':'quick'})
        self.assertEqual(self.m.s['settings']['strictness'], 'hard')
        self.assertIn('planning style: quick', agent.digest(self.m.snapshot(self.now), self.now))
        with self.assertRaises(ValueError):
            self.call('verdict', id=self.ids[0], verdict='pass', note='Done', basis='claim')
        with self.assertRaises(ValueError): self.call('settings', values={'strictness':'honor'})

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
    def test_reset_time_cannot_reopen_a_finished_day(self):
        self.start(1); self.call('verdict',id=self.ids[0],verdict='pass',note='Done.'); self.assertFalse(self.m.snapshot(self.now)['locked'])
        self.now+=86400; today=self.m.snapshot(self.now)['date']
        s=self.call('settings',values={'reset':'23:59'})   # later than now: the old arithmetic put this back in yesterday
        self.assertEqual(s['date'],today); self.assertTrue(s['locked']); self.assertFalse(s['started'])
        # Nor does a clock set backwards.
        s=self.m.snapshot(self.now-86400); self.assertEqual(s['date'],today); self.assertTrue(s['locked'])
    def test_rewording_keeps_the_check(self):
        self.call('add',text='Report',check='report.md exists'); ident=self.m.snapshot(self.now)['tasks'][0]['id']
        self.call('change',id=ident,action='edit',text='Full report')
        task=self.m.snapshot(self.now)['tasks'][0]; self.assertEqual((task['text'],task['check']),('Full report','report.md exists'))
        tools=Tools(self.m,None); tools.call('update_task',{'id':ident,'text':'The full report','check':'report.md has 500 words'},self.now)
        self.assertEqual(self.m.snapshot(self.now)['tasks'][0]['check'],'report.md has 500 words')
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
    def __init__(self): self.suggested=''; self.installs=0; self.asked=[]; self.links=set()
    def ask(self,kind,value): self.asked.append((kind,value)); return 'Asked.'
    def link_allowed(self,url): return url in self.links
    def shared_screenshot(self): raise ValueError('There is no approved screenshot to view.')
    def open_apps(self): return ['discord','foot']
    def installed_apps(self): return [('Steam','steam'),('YouTube','site youtube.com')]
    def connect_browser(self): return ['chromium']
    def suggest(self,text): self.suggested=text
    def choose(self,options,multiple): self.choices=(options,multiple)
    def validate_setup(self): pass
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
        self.assertEqual(self.call('list_apps'),'Open window classes: discord, foot\nInstalled: Steam=steam, YouTube=site youtube.com')
        self.call('set_rules',mode='earn',minutes=20); self.call('install_blocking_helper'); self.assertEqual(self.host.installs,1)
        self.assertFalse(self.state()['locked']); self.call('finish_setup'); self.assertTrue(self.state()['locked'])
        self.call('add_tasks',tasks=[{'text':'Emails','check':'Inbox handled'},{'text':'Call mum'}]); ids=[t['id'] for t in self.state()['tasks']]
        with self.assertRaises(ValueError): self.call('start_day')
        self.assertEqual(self.call('update_task',id=ids[1],main=True,check='She picked up'),'Task check updated, is now the main task.')
        self.call('start_day'); self.call('suggest_reply',text='yes'); self.assertEqual(self.host.suggested,'yes')
        self.call('offer_choices',options=['hard','lockdown']); self.assertEqual(self.host.choices,(['hard','lockdown'],None))
        with self.assertRaises(ValueError): self.call('offer_choices',options=['only one'])
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
    def test_only_a_fresh_attempt_is_announced(self):
        window={'address':'0xa','class':'discord','initialClass':'discord','pid':7,'workspace':{'name':'1'}}
        state={'locked':True,'settings':{'sites':[],'apps':['discord'],'hosts':False}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(common,'STATE',Path(tmp)), patch.object(blocking,'HELPER','/nonexistent/focus-test'), \
             patch.object(blocking,'clients',return_value=[window]), patch.object(blocking,'dispatch') as move:
            runtime=blocking.Runtime()
            runtime.reconcile(state); self.assertEqual(move.call_count,1); self.assertEqual(runtime.blocked_at,0)   # swept up as the lock began
            runtime.reconcile(state,force=True,quiet=True); self.assertEqual(runtime.blocked_at,0)                  # card is open
            runtime.reconcile(state,force=True); self.assertGreater(runtime.blocked_at,0); self.assertEqual(runtime.blocked_name,'discord')
    def test_installed_apps_name_their_class_or_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp); apps=home/'.local/share/applications'; apps.mkdir(parents=True)
            (apps/'Steam.desktop').write_text('[Desktop Entry]\nType=Application\nName=Steam\nExec=steam %U\nStartupWMClass=steam\n')
            (apps/'YouTube.desktop').write_text('[Desktop Entry]\nType=Application\nName=YouTube\nExec=omarchy-launch-webapp https://www.youtube.com/\n')
            (apps/'Hidden.desktop').write_text('[Desktop Entry]\nType=Application\nName=Hidden\nNoDisplay=true\nExec=x\n')
            with patch.object(blocking.Path,'home',return_value=home):
                found=dict(blocking.installed_apps())
            self.assertEqual(found['Steam'],'steam'); self.assertEqual(found['YouTube'],'site youtube.com'); self.assertNotIn('Hidden',found)
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
            extension=str(common.PLUGIN/'browser/extension')
            self.assertEqual(flags.read_text(),'--ozone-platform=wayland\n--load-extension=/usr/share/other,'+extension+'\n')
            self.assertEqual((home/'.config/chromium-flags.conf.before-focus').read_text().count('focus'),0)
            host=json.loads((home/'.config/chromium/NativeMessagingHosts/local.omarchy.focus.json').read_text())
            self.assertEqual(host['allowed_origins'],['chrome-extension://'+blocking.extension_id(extension)+'/'])
        # An install from before the extension moved one folder down is re-pointed, not left loading an empty folder.
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp); (home/'.config').mkdir(); flags=home/'.config/chromium-flags.conf'; former=str(common.PLUGIN/'browser')
            flags.write_text('--load-extension=/usr/share/other,'+former+'\n')
            with patch.object(blocking.Path,'home',return_value=home),patch.object(blocking.shutil,'which',return_value=None):
                self.assertTrue(blocking.browser_moved()); self.assertFalse(blocking.browser_status()['extension'])
                blocking.browser_connect()
                self.assertFalse(blocking.browser_moved()); self.assertEqual(blocking.browser_status(),{'extension':True,'host':True})
                self.assertEqual(flags.read_text(),'--load-extension=/usr/share/other,'+extension+'\n')
                flags.write_text('--load-extension='+former+'\n--other\n'); blocking.browser_disconnect(); self.assertEqual(flags.read_text(),'--other\n')
        # Pinned so a change to the derivation is noticed; the formula was checked against an id Chromium assigned.
        self.assertEqual(blocking.extension_id('/home/user/.config/omarchy/plugins/local.focus/browser'),'ddlcfpcpogihbkdojjfgljoapmdeomeg')

class EvidenceTests(unittest.TestCase):
    """The limits on what the agent can see are enforced in code. These attack them directly."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); base=Path(self.tmp.name).resolve()
        self.root=base/'projects'; self.outside=base/'private'; self.root.mkdir(); self.outside.mkdir()
        (self.root/'app').mkdir(); (self.root/'app/main.py').write_text('print("shipping")\n')
        (self.root/'app/.env').write_text('API_KEY=synthetic-secret\n'); (self.root/'app/id_rsa').write_text('synthetic key\n')
        (self.outside/'diary.txt').write_text('synthetic private note\n')
        (self.root/'app/escape').symlink_to(self.outside/'diary.txt'); (self.root/'door').symlink_to(self.outside)
        self.roots=[self.root]
    def tearDown(self): self.tmp.cleanup()
    def refused(self,call,*args,**kwargs):
        with self.assertRaises(evidence.Refused): call(*args,**kwargs)
    def test_nothing_is_readable_until_a_folder_is_approved(self):
        self.refused(evidence.read_file,str(self.root/'app/main.py'),[])
        self.assertEqual(evidence.approved({'roots':[str(self.root),'/nonexistent/x']}),[self.root])
    def test_reads_stay_inside_approved_folders(self):
        self.assertIn('shipping',evidence.read_file('app/main.py',self.roots)); self.assertIn('shipping',evidence.read_file(str(self.root/'app/main.py'),self.roots))
        for path in (str(self.outside/'diary.txt'),str(self.root/'../private/diary.txt'),'app/escape','door/diary.txt','/etc/passwd','~/.ssh/id_ed25519'):
            self.refused(evidence.read_file,path,self.roots)
        self.refused(evidence.list_files,'door',self.roots); self.refused(evidence.list_files,'..',self.roots)
    def test_credentials_are_never_readable_even_inside(self):
        for path in ('app/.env','app/id_rsa'): self.refused(evidence.read_file,path,self.roots)
        (self.root/'app/.git').mkdir(); (self.root/'app/.git/config').write_text('[remote]\nurl=https://token@host/x\n')
        self.refused(evidence.read_file,'app/.git/config',self.roots)
        listing=evidence.list_files('app',self.roots); self.assertIn('main.py',listing); self.assertNotIn('.env',listing); self.assertNotIn('id_rsa',listing)
        for name in ('.env.production','prod.pem','server.key','.npmrc','aws-credentials.json','secrets.yaml','terraform.tfstate'): self.assertTrue(evidence.is_secret(Path('x')/name),name)
        for name in ('main.py','README.md','environment.md','keyboard.py'): self.assertFalse(evidence.is_secret(Path('x')/name),name)
    def test_search_skips_secrets_and_escaping_links(self):
        self.assertIn('main.py:1',evidence.search_files('shipping','.',self.roots))
        self.assertEqual(evidence.search_files('synthetic','.',self.roots),'No matches.')
    def git(self,*args):
        env={'PATH':'/usr/bin:/bin','HOME':self.tmp.name,'GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_SYSTEM':'/dev/null'}
        subprocess.run(['git','-C',str(self.root/'app'),'-c','user.name=t','-c','user.email=t@t.invalid',*args],check=True,capture_output=True,env=env)
    @unittest.skipUnless(shutil.which('bwrap') and shutil.which('git'),'needs bubblewrap and git')
    def test_git_evidence_cannot_write_or_run_anything(self):
        repo=self.root/'app'; inside=repo/'canary-inside'; outside=self.outside/'canary-outside'
        marker=repo/'evil.sh'; marker.write_text('#!/bin/sh\ntouch %s %s 2>/dev/null\ncat "$1" 2>/dev/null\n' % (inside,outside)); marker.chmod(0o755)
        self.git('init','-q'); (repo/'.gitattributes').write_text('*.py diff=evil filter=evil\n'); (repo/'.gitignore').write_text('canary-*\n')
        self.git('add','main.py','.gitattributes','.gitignore','.env'); self.git('commit','-q','-m','first')
        # Every executable hook a repository can configure for the four views we offer.
        for key in ('diff.evil.textconv','diff.evil.command','diff.external','core.fsmonitor','filter.evil.clean','filter.evil.smudge','core.pager','core.sshCommand'):
            self.git('config',key,str(marker))
        (repo/'main.py').write_text('print("shipping more")\n')
        self.assertIn('main.py',evidence.git('app','status',self.roots)); self.assertIn('first',evidence.git('app','log',self.roots,limit=5))
        diff=evidence.git('app','diff',self.roots); self.assertIn('shipping more',diff)
        shown=evidence.git('app','show',self.roots,ref='HEAD'); self.assertIn('first',shown); self.assertIn('main.py',shown)
        self.assertNotIn('synthetic-secret',shown+diff)  # a committed .env stays out of the output
        self.assertFalse(inside.exists()); self.assertFalse(outside.exists())
        # No caller-supplied option ever reaches git.
        for ref in ('--output='+str(outside),'-p','HEAD --output=x','HEAD:.env','$(touch x)','a..b..c'):
            self.refused(evidence.git,'app','show',self.roots,ref=ref)
        self.refused(evidence.git,'app','push',self.roots); self.refused(evidence.git,'app','diff',self.roots,path='../../private')
        self.refused(evidence.git,str(self.outside),'status',self.roots)
        self.assertFalse(inside.exists()); self.assertFalse(outside.exists())
    def test_links_must_be_public_and_approved(self):
        for url in ('file:///etc/passwd','ftp://example.com/x','https://user:pw@example.com/','javascript:alert(1)',''): self.refused(evidence.check_url,url)
        for host in ('127.0.0.1','localhost','10.0.0.5','192.168.1.1','169.254.169.254','::1','0.0.0.0'): self.refused(evidence.public_address,host,80)
        self.refused(evidence.fetch,'https://example.com/page',lambda url: False)
    def test_redirects_are_checked_and_cannot_leave_the_site(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*a): pass
            def do_GET(self):
                if self.path=='/hop': self.send_response(302); self.send_header('Location','/landed'); self.end_headers()
                elif self.path=='/away': self.send_response(302); self.send_header('Location','http://elsewhere.invalid/steal?d=1'); self.end_headers()
                else:
                    body=b'<html><script>x</script><p>proof of work</p></html>'
                    self.send_response(200); self.send_header('Content-Type','text/html'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        server=http.server.HTTPServer(('127.0.0.1',0),Handler); threading.Thread(target=server.serve_forever,daemon=True).start()
        port=server.server_address[1]
        try:
            # The real address check refuses loopback (tested above); here it is pinned to the test server to exercise redirects.
            with patch.object(evidence,'public_address',return_value='127.0.0.1'):
                page=evidence.fetch('http://site.invalid:%d/hop' % port,lambda url: True)
                self.assertIn('proof of work',page); self.assertNotIn('script',page)
                self.refused(evidence.fetch,'http://site.invalid:%d/away' % port,lambda url: True)
        finally: server.shutdown(); server.server_close()

class ConfigTests(unittest.TestCase):
    def test_the_agent_has_no_tool_for_what_only_the_user_may_change(self):
        for definition in TOOLS:
            fields=set(definition['inputSchema']['properties'])
            self.assertFalse(fields & {'roots','provider','endpoint','model'},definition['name'])
        m=Model(); tools=Tools(m,Host()); now=time.time()
        with tempfile.TemporaryDirectory(dir=Path.home()) as inside:
            self.assertEqual(tools.call('request_folder',{'path':inside},now),'Asked.'); self.assertEqual(m.s['settings']['roots'],[])
            self.assertEqual(tools.host.asked,[('folder',str(Path(inside).resolve()))])
        for path in ('/',str(Path.home()),'/nonexistent/place','relative'):
            with self.assertRaises(ValueError): tools.call('request_folder',{'path':path},now)
        with self.assertRaises(ValueError): tools.call('read_file',{'path':'/etc/passwd'},now)
        self.assertEqual(tools.call('open_link',{'url':'https://example.com/a'},now),'Asked.'); self.assertEqual(tools.host.asked[-1],('link','https://example.com/a'))
        with self.assertRaises(ValueError): tools.call('open_link',{'url':'file:///etc/passwd'},now)
    def test_settings_are_validated_and_old_state_migrates(self):
        m=Model(); now=time.time(); change=lambda **v: m.apply({'op':'settings','values':v},now)
        change(provider='ollama',model='qwen3:8b',endpoint='http://localhost:11434/')
        self.assertEqual(m.s['settings']['endpoint'],'http://localhost:11434')
        for bad in ({'provider':'openai'},{'model':'x; rm -rf'},{'endpoint':'http://user:pw@host:1'},{'endpoint':'file:///x'},{'endpoint':'http://h/v1?key=1'},{'roots':['/']},{'roots':[str(Path.home())]}):
            with self.assertRaises(ValueError): change(**bad)
        with tempfile.TemporaryDirectory(dir=Path.home()) as inside:
            old=Model({'version':3,'settings':{'evidence':inside,'agent':'claude','sites':['x.com']},'days':{},'current':'','recovered':False})
            self.assertEqual(old.s['settings']['roots'],[str(Path(inside).resolve())]); self.assertEqual(old.s['settings']['provider'],'auto')
            self.assertEqual(old.s['settings']['sites'],['x.com']); self.assertNotIn('evidence',old.s['settings']); self.assertNotIn('agent',old.s['settings'])
    def test_the_agent_process_gets_no_tools_of_its_own_and_no_stray_secrets(self):
        class Stub: model=Model()
        session=agent.Session(Stub()); session.token='t'
        with patch.dict(os.environ,{'AWS_SECRET_ACCESS_KEY':'synthetic','GITHUB_TOKEN':'synthetic','ANTHROPIC_API_KEY':'synthetic'}), patch.object(agent,'binary',return_value='claude'), patch.dict(os.environ,{},clear=False):
            os.environ.pop('FOCUS_AGENT_CMD',None)
            command=session.command(Stub.model.s['settings'])
            self.assertEqual(command[command.index('--tools')+1],''); self.assertEqual(command[command.index('--allowedTools')+1:],['mcp__focus'])
            for word in ('Bash','WebFetch','Read','--add-dir'): self.assertNotIn(word,command)
            cloud=agent.environment({'provider':'claude','endpoint':'','model':''},'t')
            self.assertFalse({'AWS_SECRET_ACCESS_KEY','GITHUB_TOKEN','ANTHROPIC_API_KEY'} & set(cloud)); self.assertEqual(cloud['FOCUS_SESSION'],'t')
            with tempfile.TemporaryDirectory() as tmp, patch.object(common,'STATE',Path(tmp)):
                local=agent.environment({'provider':'ollama','endpoint':'http://127.0.0.1:11434','model':'m'},'t')
                self.assertEqual(local['ANTHROPIC_BASE_URL'],'http://127.0.0.1:11434'); self.assertEqual(local['ANTHROPIC_API_KEY'],'')
                # An empty profile: no cloud login is available for the harness to fall back on.
                self.assertEqual(local['CLAUDE_CONFIG_DIR'],str(Path(tmp)/'agent-ollama')); self.assertEqual(os.listdir(local['CLAUDE_CONFIG_DIR']),[])
                self.assertNotIn('GITHUB_TOKEN',local)

class AgentChoiceTests(unittest.TestCase):
    """Focus uses whichever coding agent the machine already has, and keeps the ones with tools of their own in a jail."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.home=Path(self.tmp.name).resolve()
        self.bin=self.home/'tools'; self.bin.mkdir()
        for name in ('claude','codex'): self.program(name,'#!/bin/sh\necho real\n')
        self.patches=[patch.object(agent.Path,'home',return_value=self.home),patch.object(agent.shutil,'which',side_effect=lambda n: str(self.bin/n) if (self.bin/n).exists() else ('/usr/bin/bwrap' if n=='bwrap' else None)),
                      patch.dict(os.environ,{'HOME':str(self.home)})]
        for p in self.patches: p.start()
        os.environ.pop('FOCUS_AGENT_CMD',None)
    def tearDown(self):
        for p in self.patches: p.stop()
        self.tmp.cleanup()
    def program(self,name,text): (self.bin/name).write_text(text); (self.bin/name).chmod(0o755)
    def default(self,name): (self.home/'.config/omarchy/defaults').mkdir(parents=True,exist_ok=True); (self.home/'.config/omarchy/defaults/agent').write_text(name+'\n')
    def test_auto_follows_the_agent_chosen_for_omarchy(self):
        self.assertEqual(agent.resolve({'provider':'auto'}),'claude')          # nothing chosen: the first one installed
        self.default('codex'); self.assertEqual(agent.resolve({'provider':'auto'}),'codex')
        self.default('gemini'); self.assertEqual(agent.resolve({'provider':'auto'}),'claude')   # one Focus cannot drive: fall back to one it can
        note=backend.Backend().describe({'provider':'auto','model':'','endpoint':'http://127.0.0.1:11434'})['note']
        self.assertIn('gemini',note); self.assertIn('using claude',note)
        self.default('claude'); self.assertEqual(agent.resolve({'provider':'codex'}),'codex')    # an explicit choice wins
        self.assertEqual(Model({'version':3,'settings':{'provider':'gemini','model':'x/y'},'days':{},'current':'','recovered':False}).s['settings']['provider'],'auto')
    def test_an_install_stub_is_not_an_installed_agent(self):
        self.program('codex','#!/bin/bash\nexport MISE_MINIMUM_RELEASE_AGE=0\nmise use -g --quiet "codex" || exit 1\n')
        self.assertEqual(agent.binary('codex'),''); self.default('codex'); self.assertEqual(agent.resolve({'provider':'auto'}),'claude')
        info=backend.describe_agent('codex',{'model':''}); self.assertFalse(info['ok']); self.assertIn('not installed',info['error'])
    def test_agent_lookup_is_remembered_between_state_pushes(self):
        with patch.object(agent,'locate',return_value='/x/claude') as locate:
            for _ in range(5): self.assertEqual(agent.binary('claude'),'/x/claude')
        self.assertEqual(locate.call_count,1)
    def test_agents_with_their_own_tools_only_run_jailed(self):
        class Stub: model=Model()
        with tempfile.TemporaryDirectory() as state, patch.object(common,'STATE',Path(state)), patch.object(common,'SOCKET',Path(state)/'control.sock'):
            session=agent.make_session(type('H',(),{'model':Model({'version':3,'settings':{'provider':'codex','model':'small-one'},'days':{},'current':'','recovered':False})})())
            self.assertIsInstance(session,agent.ExecSession); session.token='tok'
            picture=Path(state)/'proof.jpg'; picture.write_bytes(b'x'); session.attach=str(picture)
            try:
                command,env,_=session.launch(session.host.model.s['settings'])
                self.assertEqual(command[0],'/usr/bin/bwrap'); self.assertIn('--unshare-user',command)
                # No network of its own: the only way out is the gate, reached through the bridge that wraps the agent.
                self.assertIn('--unshare-net',command); gate=agent.GATES['codex'].path
                self.assertTrue(gate.startswith(os.environ.get('XDG_RUNTIME_DIR') or state)); self.assertEqual(os.stat(gate).st_mode & 0o777,0o600)
                self.assertEqual(command[command.index(str(self.bin/'codex'))-2:command.index(str(self.bin/'codex'))],[str(common.PLUGIN/'netgate.py'),gate])
                # The home directory is replaced by an empty one; only the agent's own sign-in folder is put back.
                self.assertEqual(command[command.index('--tmpfs',command.index('/tmp'))+1],str(self.home))
                binds=[command[i+1] for i,word in enumerate(command) if word in ('--bind','--ro-bind')]
                self.assertIn(str(self.home/'.codex'),binds); self.assertIn(gate,binds); self.assertIn(str(Path(state)/'control.sock'),binds); self.assertIn(str(picture),binds)
                for hidden in ('.ssh','Projects','.claude','.config/omarchy'): self.assertFalse(any(b==str(self.home/hidden) for b in binds),hidden)
                self.assertFalse(any(b==str(self.home) for b in binds))
                self.assertEqual(command[command.index('-m')+1],'small-one'); self.assertEqual(command[command.index('-i')+1],str(picture))
                self.assertEqual(set(env),set(env)&{'HOME','PATH','USER','LOGNAME','LANG','TERM'})
                for feature in ('shell_tool','unified_exec','multi_agent','browser_use'): self.assertEqual(command[command.index(feature)-1],'--disable')
                self.assertIn('mcp_servers.focus.default_tools_approval_mode="approve"',command); self.assertEqual(command[command.index('--sandbox')+1],'read-only')
                self.assertIn('model_reasoning_effort="low"',command)
            finally:
                for g in agent.GATES.values(): g.close()
                agent.GATES.clear()
            with patch.object(agent.shutil,'which',side_effect=lambda n: None if n=='bwrap' else str(self.bin/n)):
                with self.assertRaises(OSError): session.launch(session.host.model.s['settings'])
        with patch.object(agent.shutil,'which',side_effect=lambda n: None if n=='bwrap' else str(self.bin/n)):
            info=backend.describe_agent('codex',{'model':''}); self.assertFalse(info['ok']); self.assertIn('bwrap',info['error'])
        self.assertIsInstance(agent.make_session(Stub()),agent.Session)   # Claude Code has no tools of its own left, so it runs as before
    def test_a_turn_per_process_agent_runs_a_whole_turn(self):
        # Stands in for an agent with no long-running mode: prints its events and exits. Run without the jail, which the test above covers.
        self_bin=self.bin
        self.program('codex','#!/bin/sh\ncat >/dev/null\necho \'{"type":"item.started","item":{"type":"mcp_tool_call","tool":"add_tasks","arguments":{}}}\'\necho \'{"type":"item.completed","item":{"type":"agent_message","text":"Two on the list."}}\'\n')
        seen=[]
        class Host:
            model=Model({'version':3,'settings':{'provider':'codex'},'days':{},'current':'','recovered':False})
            def recap(self): return ''
            def digest(self): return '<focus_state/>'
            def watch(self,stream,callback): self.stream,self.callback=stream,callback
            def unwatch(self,stream): pass
            def turn_started(self): seen.append('started')
            def turn_progress(self,text,activity): seen.append(('progress',text,activity))
            def turn_finished(self,text): seen.append(('finished',text))
            def turn_failed(self,text): seen.append(('failed',text))
        class NoGate:
            path='/nonexistent/gate'
        # The jail, the gate and the bridge are covered above; here the stand-in runs bare so the turn logic is what is tested.
        with tempfile.TemporaryDirectory() as state, patch.object(common,'STATE',Path(state)), patch.object(agent,'jail',return_value=[]), patch.object(agent,'gate',return_value=NoGate()), \
             patch.object(agent.ExecSession,'launch',lambda self,settings: ([str(self_bin/'codex')],{'PATH':'/usr/bin:/bin'},True)):
            host=Host(); session=agent.make_session(host); session.send('<user>today: two things</user>')
            for _ in range(200):
                if not session.busy: break
                import select as wait
                if wait.select([host.stream],[],[],0.05)[0]: host.callback()
        self.assertEqual(seen,['started',('progress','','writing the list'),('progress','Two on the list.',None),('finished','Two on the list.')])
        self.assertFalse(session.busy); self.assertIsNone(session.proc)
    def test_each_agents_events_are_read_into_text_activity_and_failure(self):
        read=agent.read_event
        self.assertEqual(read('codex',{'type':'item.completed','item':{'type':'agent_message','text':'Added  both.'}}),('Added both.',None,''))
        self.assertEqual(read('codex',{'type':'item.started','item':{'type':'mcp_tool_call','tool':'add_tasks','arguments':{}}}),('','writing the list',''))
        self.assertEqual(read('codex',{'type':'error','message':'boom'})[2],'boom'); self.assertEqual(read('codex',{'type':'turn.started'}),('',None,''))

class GateTests(unittest.TestCase):
    """A jailed agent's only way out: its own provider, port 443, nothing else."""
    def test_only_the_provider_is_reachable(self):
        import netgate
        allowed=netgate.PROVIDER_HOSTS['codex']
        for host in ('api.openai.com','chatgpt.com','auth.openai.com','API.OpenAI.com.'): self.assertTrue(netgate.permitted(host,allowed),host)
        for host in ('example.com','openai.com.evil.net','notopenai.com','evilchatgpt.com','127.0.0.1','localhost',''): self.assertFalse(netgate.permitted(host,allowed),host)
        upstream=socket.socket(); upstream.bind(('127.0.0.1',0)); upstream.listen(1)
        def answer():
            conn,_=upstream.accept(); conn.sendall(b'provider says hi'); conn.close()
        threading.Thread(target=answer,daemon=True).start()
        with tempfile.TemporaryDirectory() as tmp:
            gate=netgate.Gate(Path(tmp)/'gate.sock',allowed)
            def ask(line):
                with socket.socket(socket.AF_UNIX) as s:
                    s.settimeout(5); s.connect(gate.path); s.sendall(line+b'\r\n\r\n'); data=b''
                    while True:
                        chunk=s.recv(4096)
                        if not chunk: break
                        data+=chunk
                    return data
            try:
                for refused in (b'CONNECT example.com:443 HTTP/1.1',b'CONNECT api.openai.com:22 HTTP/1.1',b'GET http://api.openai.com/ HTTP/1.1',b'CONNECT 169.254.169.254:443 HTTP/1.1',b'garbage'):
                    self.assertTrue(ask(refused).startswith(b'HTTP/1.1 403'),refused)
                self.assertEqual(len(gate.refused),5)
                # An allowed destination is connected and relayed (pointed at a local stand-in for the provider).
                real=socket.create_connection
                with patch.object(netgate.socket,'create_connection',side_effect=lambda address,timeout=None: real(upstream.getsockname())) as dial:
                    self.assertEqual(ask(b'CONNECT api.openai.com:443 HTTP/1.1'),b'HTTP/1.1 200 Connection established\r\n\r\nprovider says hi')
                    self.assertEqual(dial.call_args[0][0],('api.openai.com',443))
            finally: gate.close(); upstream.close()

class FakeOllama:
    """Answers the one question Focus asks an Ollama server: what is this model and what can it do."""
    def __init__(self,**shown):
        outer=self; self.shown=shown; self.asked=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*a): pass
            def do_POST(self):
                outer.asked.append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                body=json.dumps(outer.shown).encode()
                self.send_response(200 if outer.shown else 404); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        self.server=http.server.HTTPServer(('127.0.0.1',0),Handler); threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.url='http://127.0.0.1:%d' % self.server.server_address[1]
    def close(self): self.server.shutdown(); self.server.server_close()

class BackendTests(unittest.TestCase):
    def describe(self,url,model='qwen3'): return backend.describe_ollama({'endpoint':url,'model':model})
    def test_local_remote_and_capabilities_are_checked_not_assumed(self):
        server=FakeOllama(capabilities=['completion','tools'])
        try:
            info=self.describe(server.url); self.assertTrue(info['ok']); self.assertEqual(info['where'],'local'); self.assertFalse(info['vision']); self.assertIn('on this machine',info['label'])
            self.assertEqual(server.asked[0],('/api/show',{'model':'qwen3'}))
            server.shown={'capabilities':['completion','tools','vision'],'remote_host':'https://ollama.com'}
            info=self.describe(server.url); self.assertEqual(info['where'],'remote'); self.assertIn('remote',info['label']); self.assertTrue(info['vision'])
            self.assertEqual(self.describe(server.url,'big-model:cloud')['where'],'remote')
            server.shown={'capabilities':['completion']}
            info=self.describe(server.url); self.assertFalse(info['ok']); self.assertIn('cannot call tools',info['error'])
        finally: server.close()
    def test_a_missing_server_or_model_is_an_error_never_a_fallback(self):
        info=self.describe('http://127.0.0.1:9'); self.assertFalse(info['ok']); self.assertIn('not answering',info['error']); self.assertEqual(info['provider'],'ollama')
        self.assertFalse(self.describe('http://127.0.0.1:9','')['ok'])
        self.assertEqual(backend.describe_claude({'model':''})['where'],'remote')

class RoutingTests(unittest.TestCase):
    @unittest.skipUnless(agent.binary(),'needs the Claude Code program')
    def test_ollama_mode_sends_model_requests_to_the_chosen_server_without_a_cloud_login(self):
        seen=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*a): pass
            def do_GET(self): self.send_response(404); self.end_headers()
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
                seen.append((self.path.split('?')[0],self.headers.get('Authorization') or self.headers.get('x-api-key') or '',body.get('model')))
                events=[('message_start',{'type':'message_start','message':{'id':'m','type':'message','role':'assistant','model':body.get('model'),'content':[],'stop_reason':None,'stop_sequence':None,'usage':{'input_tokens':1,'output_tokens':1}}}),
                        ('content_block_start',{'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}}),
                        ('content_block_delta',{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'From the chosen server.'}}),
                        ('content_block_stop',{'type':'content_block_stop','index':0}),
                        ('message_delta',{'type':'message_delta','delta':{'stop_reason':'end_turn','stop_sequence':None},'usage':{'output_tokens':5}}),('message_stop',{'type':'message_stop'})]
                out=''.join('event: %s\ndata: %s\n\n' % (n,json.dumps(d)) for n,d in events).encode()
                self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.send_header('Content-Length',str(len(out))); self.end_headers(); self.wfile.write(out)
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler); threading.Thread(target=server.serve_forever,daemon=True).start()
        settings={'provider':'ollama','endpoint':'http://127.0.0.1:%d' % server.server_address[1],'model':'local-test-model'}
        class Stub: pass
        with tempfile.TemporaryDirectory() as tmp, patch.object(common,'STATE',Path(tmp)), patch.dict(os.environ,{}):
            os.environ.pop('FOCUS_AGENT_CMD',None)
            session=agent.Session(Stub()); session.token='t'
            proc=subprocess.Popen(session.command(settings),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,cwd=tmp,env=agent.environment(settings,'t'))
            try:
                proc.stdin.write(json.dumps({'type':'user','message':{'role':'user','content':[{'type':'text','text':'hello'}]}}).encode()+b'\n'); proc.stdin.flush()
                result=None; deadline=time.time()+60
                while time.time()<deadline:
                    line=proc.stdout.readline()
                    if not line: break
                    event=json.loads(line)
                    if event.get('type')=='result': result=event; break
            finally:
                proc.terminate(); proc.wait(timeout=10); proc.stdin.close(); proc.stdout.close(); server.shutdown(); server.server_close()
        self.assertIsNotNone(result); self.assertEqual(result['result'],'From the chosen server.')
        # The reply came from the chosen server, named the chosen model, and carried the placeholder token rather than any login.
        self.assertTrue(seen); self.assertEqual({(path,auth,model) for path,auth,model in seen},{('/v1/messages','Bearer ollama','local-test-model')})

# Speaks the agent's streaming protocol and drives Focus through the same tool op the real tool server uses.
FAKE_AGENT="""#!/usr/bin/python3
import json,os,re,socket,sys,time
def tool(name,**args):
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(os.environ['FOCUS_STATE_HOME']+'/control.sock'); s.sendall(json.dumps({'op':'tool','name':name,'args':args,'session':os.environ['FOCUS_SESSION']}).encode()+b'\\n')
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
    elif said.startswith('folder '): reply=tool('request_folder',path=said[7:]).get('text','refused')[:5]
    elif said=='screen': r=tool('look_at_screen'); reply='asked' if r['ok'] else r['error']
    elif said=='done': [tool('record_verdict',id=i,passed=True,note='Fine.',basis='claim') for i in ids]; reply='Unlocked.'
    else: reply='Earlier: '+str('<earlier_today>' in text)
    out({'type':'stream_event','event':{'type':'content_block_delta','delta':{'type':'text_delta','text':reply[:4]}}})
    out({'type':'assistant','message':{'content':[{'type':'text','text':'Thinking aloud.'},{'type':'tool_use','name':'mcp__focus__read_file','input':{'path':'/x/notes.md'}}]}})
    out({'type':'assistant','message':{'content':[{'type':'text','text':reply}]}})
    out({'type':'result','is_error':False,'result':reply})
"""

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)
        fake=self.path/'agent'; fake.write_text(FAKE_AGENT); fake.chmod(0o700)
        model=Model(); model.s['setup']=True; model.s['settings']['sites']=['youtube.com']; common.write(self.path/'state.json',model.s)
        self.env={**os.environ,'FOCUS_STATE_HOME':self.tmp.name,'FOCUS_AGENT_CMD':str(fake),'PYTHONPATH':str(Path(focus.__file__).parent)}
        # The stand-in screenshot writes a file, so a capture that should not have happened is detectable.
        code=("import blocking,daemon,common; blocking.HELPER='/nonexistent/focus-test'; blocking.clients=lambda: []\n"
              "def shot():\n p=common.STATE/'proof'; p.mkdir(exist_ok=True); f=p/'screen-1.jpg'; f.write_bytes(b'synthetic image'); return str(f)\n"
              "def clip():\n p=common.STATE/'proof'; p.mkdir(exist_ok=True); f=p/'screen-2.png'; f.write_bytes(b'synthetic paste'); return str(f)\n"
              "blocking.screenshot=shot; blocking.clipboard_image=clip; daemon.serve()")
        self.proc=subprocess.Popen([sys.executable,'-c',code],env=self.env,stderr=subprocess.PIPE)
        self.socket=patch.object(common,'SOCKET',self.path/'control.sock'); self.socket.start()
        for _ in range(100):
            if (self.path/'control.sock').exists(): break
            time.sleep(.02)
    def chat(self): return common.request({'op':'subscribe'})['chat']
    def until(self,done):
        for _ in range(200):
            chat=self.chat()
            if done(chat): return chat
            time.sleep(.05)
        self.fail('Timed out: '+json.dumps(chat)[:400])
    def test_planning_commands_work_without_model_and_persist(self):
        common.rpc({'op':'settings', 'values':{'provider':'ollama', 'endpoint':'http://127.0.0.1:1'}})
        before=common.rpc({'op':'snapshot'})
        self.assertIn('Planning: quick', focus.say('/planning'))
        self.assertIn('Planning: guided', focus.say('/planning guided'))
        self.assertIn('Planning: guided', focus.say('/config'))
        self.assertIn('/planning quick|guided', focus.say('/help'))
        self.assertIn('Choose quick or guided', focus.say('/planning chatty'))
        after=common.rpc({'op':'snapshot'})
        self.assertEqual(after['settings']['planning'], 'guided')
        self.assertEqual(after['tasks'], before['tasks'])
        self.assertEqual(after['settings']['strictness'], before['settings']['strictness'])
        saved=json.loads((self.path/'state.json').read_text())
        self.assertEqual(Model(saved).s['settings']['planning'], 'guided')
        self.assertIn('Planning: quick', focus.say('/planning quick'))

    def test_capture_ack_and_retry_use_the_same_saved_tasks(self):
        command={'op':'capture','text':'Send a note\nCall the dentist','requestId':'release-capture'}
        first=common.request(command)
        self.assertEqual(first['requestId'],'release-capture')
        second=common.request(command)
        self.assertEqual(first['state']['tasks'],second['state']['tasks'])
        saved=json.loads((self.path/'state.json').read_text())
        self.assertIn('release-capture',saved['captureReceipts'])
        with self.assertRaises(ValueError):
            common.request({'op':'capture','text':'Valid\n'+'x'*501,'requestId':'invalid-batch'})
        self.assertEqual(len(common.rpc({'op':'snapshot'})['tasks']),2)

    def test_unknown_command_is_short_and_actionable(self):
        reply=focus.say('/planing')
        self.assertIn('/planning',reply)
        self.assertLess(len(reply),100)
        reply=focus.say('/not-a-command')
        self.assertIn('Settings',reply)
        self.assertLess(len(reply),100)
        self.assertIn('Agent:',focus.say('/provider'))
        self.assertIn('Model:',focus.say('/model'))

    def test_only_the_user_can_approve_a_folder(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as inside:
            real=str(Path(inside).resolve()); (Path(real)/'notes.md').write_text('evidence here\n')
            focus.say('folder '+real); consent=self.chat()['consent']
            self.assertEqual(consent['kind'],'folder'); self.assertIn(real,consent['text']); self.assertEqual(common.rpc({'op':'snapshot'})['settings']['roots'],[])
            # Until it is approved, reading inside it is refused and changes nothing.
            with self.assertRaises(ValueError): common.request({'op':'tool','name':'read_file','args':{'path':real+'/notes.md'}})
            focus.say('no'); self.until(lambda c: not c['busy'] and not c['consent']); self.assertEqual(common.rpc({'op':'snapshot'})['settings']['roots'],[])
            focus.say('folder '+real); common.request({'op':'consent','answer':True}); self.until(lambda c: not c['busy'] and not c['consent'])
            self.assertEqual(common.rpc({'op':'snapshot'})['settings']['roots'],[real])
            self.assertIn('evidence here',common.request({'op':'tool','name':'read_file','args':{'path':real+'/notes.md'}})['text'])
            self.assertEqual(json.loads((self.path/'state.json').read_text())['settings']['roots'],[real])
            focus.say('/folder remove '+real); self.assertEqual(common.rpc({'op':'snapshot'})['settings']['roots'],[])
    def test_a_screenshot_needs_two_yeses_and_is_seen_once(self):
        shot=self.path/'proof/screen-1.jpg'; view=lambda: common.request({'op':'tool','name':'view_screenshot','args':{}})
        focus.say('screen'); self.assertEqual(self.chat()['consent']['kind'],'screen'); self.assertFalse(shot.exists())
        focus.say('no'); self.until(lambda c: not c['busy'] and not c['consent']); self.assertFalse(shot.exists())  # declined: never captured
        with self.assertRaises(ValueError): view()
        focus.say('screen'); common.request({'op':'consent','answer':True})
        consent=self.until(lambda c: c['consent'] and c['consent']['kind']=='share')['consent']
        self.assertEqual(consent['preview'],str(shot)); self.assertIn('Anthropic',consent['goes']); self.assertTrue(shot.exists())
        with self.assertRaises(ValueError): view()   # captured, but not yet approved for sending
        common.request({'op':'consent','answer':False}); self.until(lambda c: not c['busy'] and not c['consent'])
        self.assertFalse(shot.exists())
        with self.assertRaises(ValueError): view()   # looked at and withheld
        focus.say('screen'); common.request({'op':'consent','answer':True}); self.until(lambda c: c['consent'] and c['consent']['kind']=='share')
        common.request({'op':'consent','answer':True}); self.until(lambda c: not c['busy'] and not c['consent'])
        reply=view(); self.assertEqual(reply['image']['mime'],'image/jpeg'); self.assertFalse(shot.exists())
        with self.assertRaises(ValueError): view()   # once
    def test_a_pasted_image_is_previewed_and_confirmed_before_it_is_seen(self):
        pasted=self.path/'proof/screen-2.png'; view=lambda: common.request({'op':'tool','name':'view_screenshot','args':{}})
        common.request({'op':'paste'}); consent=self.chat()['consent']
        self.assertEqual((consent['kind'],consent['preview']),('share',str(pasted)))
        with self.assertRaises(ValueError): view()
        common.request({'op':'consent','answer':False}); self.assertFalse(pasted.exists())
        common.request({'op':'paste'}); common.request({'op':'consent','answer':True}); self.until(lambda c: not c['busy'] and not c['consent'])
        self.assertEqual(view()['image']['mime'],'image/png'); self.assertFalse(pasted.exists())
    def test_a_replaced_session_cannot_act_and_settings_never_depend_on_the_model(self):
        focus.say('today: one thing')
        with self.assertRaises(ValueError): common.request({'op':'tool','name':'add_tasks','args':{'tasks':[{'text':'Injected'}]},'session':'stale-token'})
        self.assertEqual(common.rpc({'op':'snapshot'})['total'],2)
        server=FakeOllama(capabilities=['completion','tools'])
        try:
            self.assertIn('Model:',focus.say('/provider ollama')); focus.say('/endpoint '+server.url); focus.say('/model qwen3')
            self.until(lambda c: common.rpc({'op':'snapshot'})['backend']['ok'])
            state=common.rpc({'op':'snapshot'}); self.assertEqual(state['backend']['where'],'local'); self.assertFalse(state['backend']['vision'])
            self.assertEqual(focus.say('screen'),'This model cannot see images, so a screenshot would not help. Use another kind of evidence.')
            self.assertIsNone(self.chat()['consent'])
            saved=json.loads((self.path/'state.json').read_text())['settings']; self.assertEqual((saved['provider'],saved['model'],saved['endpoint']),('ollama','qwen3',server.url))
        finally: server.close()
        # The server is gone: an honest error, no cloud fallback, nothing changes.
        focus.say('/model other-model'); before=common.rpc({'op':'snapshot'})
        self.until(lambda c: not common.rpc({'op':'snapshot'})['backend']['ok'] and 'Checking' not in common.rpc({'op':'snapshot'})['backend']['error'])
        answer=focus.say('today: something else'); self.assertIn('not answering',answer); self.assertIn('/provider claude',answer)
        after=common.rpc({'op':'snapshot'}); self.assertEqual(after['settings']['provider'],'ollama'); self.assertEqual(after['total'],before['total'])
        self.assertIn('Forgotten',focus.say('/forget')); self.assertEqual(self.chat()['messages'][-1]['role'],'system'); self.assertEqual(len(self.chat()['messages']),1)
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
        common.request({'op':'opened'}); common.request({'op':'opened'}); common.request({'op':'closed'})
        self.assertTrue(common.rpc({'op':'snapshot'})['introduced'])
        chat=json.loads((self.path/'chat.json').read_text())
        self.assertEqual([m['role'] for m in chat['messages']],['system','agent']); self.assertIn('Which ones waste your time?',chat['messages'][1]['text'])
        # Where the words go is said before anything is typed.
        self.assertIn('Anthropic',chat['messages'][0]['text']); self.assertIn('stay on this machine',chat['messages'][0]['text'])
        self.assertIn('youtube.com',chat['choices']['options']); self.assertTrue(chat['choices']['multiple'])
        focus.say('youtube.com, reddit.com'); self.assertIsNone(common.request({'op':'subscribe'})['chat']['choices'])
    def test_first_run_without_an_agent_says_so_and_keeps_setup_pending(self):
        self.tearDown()
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)
        env={k:v for k,v in self.env.items() if k!='FOCUS_AGENT_CMD'}
        env.update(FOCUS_STATE_HOME=self.tmp.name,HOME=self.tmp.name,PATH='/usr/bin')
        code="import blocking,daemon; blocking.HELPER='/nonexistent/focus-test'; blocking.clients=lambda: []; daemon.serve()"
        self.proc=subprocess.Popen([sys.executable,'-c',code],env=env,stderr=subprocess.PIPE)
        self.socket=patch.object(common,'SOCKET',self.path/'control.sock'); self.socket.start()
        for _ in range(100):
            if (self.path/'control.sock').exists(): break
            time.sleep(.02)
        common.request({'op':'opened'}); common.request({'op':'say','text':'youtube'})
        s=common.rpc({'op':'snapshot'}); self.assertFalse(s['setup']); self.assertEqual(s['total'],0); self.assertFalse(s['introduced'])
        chat=json.loads((self.path/'chat.json').read_text())
        self.assertEqual([m['role'] for m in chat['messages']],['system','user','system']); self.assertIn('Claude Code',chat['messages'][0]['text'])
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

class UpdateTests(unittest.TestCase):
    """Focus notices a newer published version; installing it is always the user's call."""
    def setUp(self):
        import update
        self.update=update
        self.tmp=tempfile.TemporaryDirectory(); root=Path(self.tmp.name)
        self.origin, self.copy = root/'origin', root/'local.focus'
        self.origin.mkdir(); self.git(self.origin,'init','-q','-b','main'); self.publish('1.0.0')
        self.git(root,'clone','-q',str(self.origin),str(self.copy))
        self.patch=patch.object(common,'PLUGIN',self.copy); self.patch.start()
    def tearDown(self): self.patch.stop(); self.tmp.cleanup()
    def git(self,where,*args): subprocess.run(['git','-C',str(where),'-c','user.name=t','-c','user.email=t@example.invalid','-c','commit.gpgsign=false']+list(args),check=True,capture_output=True)
    def publish(self,version):
        (self.origin/'manifest.json').write_text(json.dumps({'version':version})); self.git(self.origin,'add','.'); self.git(self.origin,'commit','-q','-m',version)
    def test_notices_a_published_version_without_changing_files(self):
        self.assertEqual(self.update.check(),{'available':False,'version':'','changes':0})
        self.publish('1.1.0'); self.publish('1.2.0')
        self.assertEqual(self.update.check(),{'available':True,'version':'1.2.0','changes':2})
        self.assertEqual(self.update.current(),'1.0.0')   # looking is not installing
        self.git(self.copy,'merge','-q','--ff-only','FETCH_HEAD'); self.assertFalse(self.update.check()['available'])
    def test_install_is_handed_to_omarchy_and_never_runs_unasked(self):
        watcher=self.update.Watcher(); self.assertTrue(watcher.managed); self.assertEqual(watcher.public()['current'],'1.0.0')
        with patch.object(self.update,'check') as check:
            watcher.at=0; watcher.poll(time.time(),False)   # switched off
            with patch.object(common,'TOASTS',False): watcher.poll(time.time(),True)   # a test or scratch run
            watcher.at=time.time(); watcher.poll(time.time(),True)   # looked recently
            self.assertFalse(check.called)
        finished=[]
        with patch.object(common,'run',return_value='') as run:
            self.assertTrue(watcher.install(finished.append))
            for _ in range(100):
                if finished: break
                time.sleep(.02)
        self.assertEqual(finished,['']); self.assertEqual(run.call_args[0][0],['omarchy','plugin','update','local.focus','--yes'])
    def test_a_copy_that_was_not_installed_from_git_says_so(self):
        shutil.rmtree(self.copy/'.git')
        with self.assertRaises(ValueError): self.update.check()
        self.assertFalse(self.update.Watcher().managed)
    def test_a_changed_root_helper_is_noticed(self):
        (self.copy/'setup').mkdir(); (self.copy/'setup/focus-root-helper').write_text('new'); installed=Path(self.tmp.name)/'helper'
        with patch.object(blocking,'HELPER',str(installed)):
            self.assertFalse(blocking.helper_stale())   # not installed at all is setup's business, not an update's
            installed.write_text('old'); self.assertTrue(blocking.helper_stale())
            installed.write_text('new'); self.assertFalse(blocking.helper_stale())

if __name__=='__main__': unittest.main()
