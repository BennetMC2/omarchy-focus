import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent, backend, blocking, common, focus, netgate, evidence
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

class OpenCodeTests(unittest.TestCase):
    def launch(self, root, settings):
        home=root/'home'; data=home/'.local/share/opencode'; data.mkdir(parents=True, exist_ok=True)
        (data/'auth.json').write_text('{"openai":{"type":"oauth","refresh":"synthetic-1"}}'); (data/'opencode.db').write_text('PRIVATE_SESSIONS')
        (home/'.config/opencode').mkdir(parents=True, exist_ok=True); (home/'.config/opencode/opencode.json').write_text('{"plugin":["UNTRUSTED_USER_PLUGIN"]}')
        session=agent.OpenCodeSession(type('Host',(),{'model':Model()})()); session.token='test-token'
        self.gates=[]
        def gate(kind, domains=None): self.gates.append((kind,domains)); return type('Gate',(),{'path':str(root/'gate')})()
        with patch.object(common,'STATE',root), patch.object(Path,'home',return_value=home), patch.dict(os.environ,{'HOME':str(home)}), patch.object(agent,'binary',return_value='/usr/bin/opencode'), \
             patch.object(agent,'jail',side_effect=lambda program,private,scratch,network=True: ['bwrap','--unshare-net','PRIVATE=%r' % (private,)]), patch.object(agent,'gate',side_effect=gate):
            for name in ('XDG_DATA_HOME','XDG_CACHE_HOME'): os.environ.pop(name,None)
            return session, home, session.launch(settings)
    def test_launch_isolated_profile_gate_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,home,(command,env,stdin)=self.launch(Path(tmp),{'model':'openai/small-one'})
            profile=Path(env['XDG_DATA_HOME']).parent
            self.assertFalse(stdin); self.assertIn('--unshare-net',command); self.assertIn('PRIVATE=[]',command)   # nothing of the real OpenCode folders is mounted
            self.assertEqual(self.gates,[('opencode-openai',netgate.OPENCODE_HOSTS['openai'])])
            self.assertEqual(command[command.index('-m')+1],'openai/small-one'); self.assertEqual(command[command.index('--agent')+1],'focus'); self.assertEqual(command[-1],'--')
            for key in ('XDG_DATA_HOME','XDG_CONFIG_HOME','XDG_CACHE_HOME','XDG_STATE_HOME'): self.assertTrue(env[key].startswith(str(profile)))
            self.assertEqual(os.listdir(profile/'data/opencode'),['auth.json']); self.assertEqual(os.listdir(profile/'config'),[])
            self.assertEqual((profile/'data/opencode/auth.json').stat().st_mode & 0o777,0o600)
            config=json.loads(env['OPENCODE_CONFIG_CONTENT'])
            self.assertEqual(set(config['tools']),set(agent.OPENCODE_OFF)); self.assertFalse(any(config['tools'].values())); self.assertFalse(any(config['agent']['focus']['tools'].values()))
            self.assertEqual(config['agent']['focus']['prompt'],agent.PERSONA); self.assertEqual(session.PREFACE,'')
            self.assertEqual(config['mcp']['focus']['environment']['FOCUS_SESSION'],'test-token'); self.assertEqual(config['share'],'disabled')
            self.assertFalse({'OPENAI_API_KEY','ANTHROPIC_API_KEY','GITHUB_TOKEN'} & set(env))
            session.stop(); self.assertFalse(profile.exists())
            self.assertIn('synthetic-1',(home/'.local/share/opencode/auth.json').read_text())
    def test_a_renewed_sign_in_goes_back_to_the_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,home,(command,env,stdin)=self.launch(Path(tmp),{'model':'openai/small-one'})
            real=home/'.local/share/opencode/auth.json'; copy=Path(env['XDG_DATA_HOME'])/'opencode/auth.json'
            copy.write_text('{"openai":{"type":"oauth","refresh":"synthetic-2"}}'); session.stop()
            self.assertIn('synthetic-2',real.read_text()); self.assertEqual(real.stat().st_mode & 0o777,0o600)
            # Never over a login the user changed meanwhile, and never with something that is not a sign-in file.
            session,home,(command,env,stdin)=self.launch(Path(tmp),{'model':'openai/small-one'})
            copy=Path(env['XDG_DATA_HOME'])/'opencode/auth.json'; copy.write_text('{"renewed":true}'); real.write_text('{"user":"signed in again"}'); session.stop()
            self.assertEqual(real.read_text(),'{"user":"signed in again"}')
            session,home,(command,env,stdin)=self.launch(Path(tmp),{'model':'openai/small-one'})
            Path(env['XDG_DATA_HOME'],'opencode/auth.json').write_text('not json'); session.stop()
            self.assertIn('synthetic-1',real.read_text())
    def test_model_decides_the_route_and_the_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            for settings,word in (({'model':''},'Pick a model'),({'model':'small-one'},'Pick a model'),({'model':'elsewhere/small-one'},'does not know where')):
                with self.assertRaises(OSError) as refused: self.launch(Path(tmp),settings)
                self.assertIn(word,str(refused.exception))
            home=Path(tmp)/'home'
            with patch.object(Path,'home',return_value=home), patch.dict(os.environ,{'HOME':str(home)}), patch.object(agent,'binary',return_value='/usr/bin/opencode'), patch('shutil.which',return_value='/usr/bin/bwrap'):
                for name in ('XDG_DATA_HOME','XDG_CACHE_HOME'): os.environ.pop(name,None)
                info=backend.describe_agent('opencode',{'model':'anthropic/some-model'})
                self.assertTrue(info['ok']); self.assertEqual(info['label'],"OpenCode (anthropic/some-model), on Anthropic's servers"); self.assertFalse(info['vision'])
                info=backend.describe_agent('opencode',{'model':''}); self.assertFalse(info['ok']); self.assertIn('Pick a model',info['error'])
                (home/'.local/share/opencode/auth.json').unlink()
                info=backend.describe_agent('opencode',{'model':'openai/x'}); self.assertFalse(info['ok']); self.assertIn('opencode auth login',info['error'])
        self.assertTrue(netgate.permitted('api.anthropic.com',netgate.OPENCODE_HOSTS['anthropic'])); self.assertFalse(netgate.permitted('registry.npmjs.org',netgate.OPENCODE_HOSTS['openai']))
        self.assertEqual(set(netgate.OPENCODE_HOSTS),set(backend.OPENCODE_OWNERS))
    def test_events(self):
        read=agent.read_event
        self.assertEqual(read('opencode',{'type':'text','part':{'type':'text','text':'Added  both.'}}),('Added both.',None,''))
        self.assertEqual(read('opencode',{'type':'tool_use','part':{'tool':'focus_read_file','state':{'input':{'path':'/x/notes.md'}}}}),('','reading notes.md',''))
        self.assertIn('not supported',read('opencode',{'type':'error','error':{'name':'APIError','data':{'message':"Bad Request: The 'm' model is not supported"}}})[2])
        self.assertEqual(read('opencode',{'type':'step_start','part':{}}),('',None,''))

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
