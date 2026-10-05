import copy
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent, blocking, common, focus, netgate, evidence
import subprocess
from model import Model
from tools import Tools

class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.m=Model(); self.m.s['setup']=True; self.now=time.time()
    def call(self, **cmd): return self.m.apply(cmd,self.now)
    def test_batch_is_atomic_in_tools_and_model(self):
        self.call(op='capture',text='Existing')
        before=copy.deepcopy(self.m.s)
        with self.assertRaises(ValueError):
            Tools(self.m,None).call('add_tasks',{'tasks':[{'text':'Valid'},{'text':''}]},self.now)
        self.assertEqual(before,self.m.s)
        with self.assertRaises(ValueError): self.call(op='capture',text='Valid\n'+'x'*501)
        self.assertEqual(before,self.m.s)
    def test_capture_retry_survives_restart_and_preserves_commas(self):
        cmd={'op':'capture','text':'Email Alex, Sam and Jo\nCall the dentist','requestId':'one'}
        s=self.call(**cmd)
        self.assertEqual(len(s['tasks']),2); self.assertTrue(s['tasks'][0]['main'])
        self.m=Model(json.loads(json.dumps(self.m.s)))
        self.assertEqual(len(self.call(**cmd)['tasks']),2)
        with self.assertRaises(ValueError): self.call(**{**cmd,'text':'Different'})
        self.assertEqual(len(self.m.snapshot(self.now)['tasks']),2)
    def test_capture_preserves_main_and_lockdown(self):
        self.call(op='capture',text='First')
        s=self.call(op='capture',text='Second')
        self.assertEqual([t['text'] for t in s['tasks'] if t['main']],['First'])
        self.call(op='settings',values={'strictness':'lockdown'})
        self.call(op='start')
        for cmd in ({'op':'capture','text':'Third'},{'op':'add','text':'Third'},
                    {'op':'plan-accept','tasks':[{'text':'Third'}]}):
            with self.assertRaises(ValueError): self.call(**cmd)
        self.assertEqual(len(self.m.snapshot(self.now)['tasks']),2)
    def test_cancelled_edit_does_not_change_task(self):
        self.call(op='capture',text='Original')
        s=self.call(op='start'); ident=s['tasks'][0]['id']
        self.call(op='change',action='edit',id=ident,text='New')
        self.call(op='cancel',id=ident)
        self.m.settle(self.now+31)
        self.assertEqual(self.m.snapshot(self.now+31)['tasks'][0]['text'],'Original')

class BrowserRemovalTests(unittest.TestCase):
    def test_removal_preserves_unrelated_flags_extensions_and_hosts(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path,'home',return_value=Path(tmp)):
            flags=Path(tmp)/'.config/chromium-flags.conf'; flags.parent.mkdir()
            extension=str(common.PLUGIN/'browser')
            original='--other-flag\n--load-extension=/keep,'+extension+',/also-keep\n'
            flags.write_text(original)
            hosts=Path(tmp)/'.config/chromium/NativeMessagingHosts'; hosts.mkdir(parents=True)
            owned=hosts/(blocking.NATIVE_HOST+'.json')
            owned.write_text(json.dumps({'name':blocking.NATIVE_HOST,'path':str(common.PLUGIN/'focus.py')}))
            unrelated=hosts/'other.json'; unrelated.write_text('{"name":"other"}')
            blocking.browser_disconnect()
            self.assertEqual(flags.read_text(),'--other-flag\n--load-extension=/keep,/also-keep\n')
            self.assertFalse(owned.exists()); self.assertTrue(unrelated.exists())
            self.assertEqual(flags.with_name(flags.name+'.before-focus-remove').read_text(),original)
            self.assertEqual(blocking.browser_disconnect(),[])
    def test_connect_then_remove_on_fresh_home(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path,'home',return_value=Path(tmp)), patch.object(blocking.shutil,'which',return_value='/usr/bin/browser'):
            self.assertEqual(len(blocking.browser_connect()),2)
            blocking.browser_disconnect()
            for _,flags,hosts in blocking.BROWSERS:
                self.assertEqual((Path(tmp)/flags).read_text(),'')
                self.assertFalse((Path(tmp)/hosts/(blocking.NATIVE_HOST+'.json')).exists())
    def test_uninstall_stops_when_recovery_fails(self):
        with patch.object(focus,'recover',side_effect=RuntimeError('recovery failed')), patch.object(blocking,'browser_disconnect') as disconnect, patch.object(focus,'run') as run:
            with self.assertRaises(RuntimeError): focus.uninstall()
            disconnect.assert_not_called(); run.assert_not_called()

class GrokTests(unittest.TestCase):
    def test_launch_isolated_profile_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); home=root/'home'; (home/'.grok').mkdir(parents=True)
            (home/'.grok/auth.json').write_text('{"synthetic":"credential"}')
            (home/'.grok/config.toml').write_text('UNTRUSTED_USER_PLUGIN')
            host=type('Host',(),{'model':Model()})()
            session=agent.GrokSession(host); session.token='test-token'
            gate=type('Gate',(),{'path':str(root/'gate')})()
            with patch.object(common,'STATE',root), patch.object(Path,'home',return_value=home), patch.object(agent,'binary',return_value='/usr/bin/grok'), patch.object(agent,'jail',return_value=['bwrap','--unshare-net']), patch.object(agent,'gate',return_value=gate):
                command,env,stdin=session.launch({})
                profile=Path(env['GROK_HOME'])
                self.assertFalse(stdin); self.assertIn('--unshare-net',command)
                self.assertEqual(command[command.index('--tools')+1],'search_tool,use_tool')
                self.assertNotIn(str(home/'.grok'),command)
                self.assertNotIn('UNTRUSTED_USER_PLUGIN',(profile/'config.toml').read_text())
                self.assertEqual((profile/'auth.json').stat().st_mode & 0o777,0o600)
                self.assertNotIn('XAI_API_KEY',env)
                session.stop(); self.assertFalse(profile.exists())
    def test_events_and_provider_gate(self):
        said,_,error=agent.read_event('grok',{'type':'result','result':'Added.','is_error':False})
        self.assertEqual((said,error),('Added.',''))
        self.assertTrue(agent.read_event('grok',{'type':'result','is_error':True,'result':'Login expired'})[2])
        _,activity,_=agent.read_event('grok',{'type':'assistant','message':{'content':[{'type':'tool_use','name':'use_tool','input':{'tool_name':'focus__add_tasks','tool_input':{'tasks':[{'text':'Task'}]}}}]}})
        self.assertEqual(activity,'writing the list')
        self.assertTrue(netgate.permitted('api.x.ai',netgate.PROVIDER_HOSTS['grok']))
        self.assertFalse(netgate.permitted('api.x.ai.evil.invalid',netgate.PROVIDER_HOSTS['grok']))
        self.assertFalse(netgate.permitted('openai.com',netgate.PROVIDER_HOSTS['grok']))

class EvidenceReleaseTests(unittest.TestCase):
    def test_approving_a_credential_directory_does_not_expose_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'.grok'; root.mkdir()
            (root/'config.toml').write_text('synthetic secret')
            with self.assertRaises(evidence.Refused): evidence.read_file(root/'config.toml',[root])
    def test_git_views_exclude_agent_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('auth.json','.grok/auth.json','.claude/settings.json','notes.txt'):
                path=root/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('CANARY-'+name)
            def git(*args): subprocess.run(['git','-C',tmp,*args],check=True,capture_output=True)
            git('init'); git('add','.')
            git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','Fixture')
            result=evidence.git(root,'show',[root])
            self.assertIn('CANARY-notes.txt',result)
            self.assertNotIn('CANARY-auth.json',result)
            self.assertNotIn('CANARY-.grok',result)
            self.assertNotIn('CANARY-.claude',result)
