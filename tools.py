"""The tools the Bouncer agent uses to run the day. Every change goes through the model's rules.

These are the agent's only tools: it has no shell, no file access and no network of its own.
Evidence comes through evidence.py, inside folders and links the user approved.
"""
import evidence
import model as rules

def tool(name, description, properties=None, required=()):
    return {'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': properties or {}, 'required': list(required)}}

ID = {'type': 'string', 'description': 'Task id from focus_state, e.g. 3f9a1c2b7d10'}
STRINGS = {'type': 'array', 'items': {'type': 'string'}}

TOOLS = [
    tool('add_tasks', 'Add tasks to today\'s list. Each is one short line in the user\'s words, with an optional check saying what will show it is done. In quick capture, leave unclear checks empty instead of questioning the user.',
         {'tasks': {'type': 'array', 'items': {'type': 'object', 'properties': {'text': {'type': 'string'}, 'check': {'type': 'string'}}, 'required': ['text']}}}, ['tasks']),
    tool('update_task', 'Reword a task, change its check, make it the main task, or agree it passes on their word (on_word, before the day starts only). After the day has started, rewording or changing the main task takes effect after a cooling-off.',
         {'id': ID, 'text': {'type': 'string'}, 'check': {'type': 'string'}, 'main': {'type': 'boolean'}, 'on_word': {'type': 'boolean'}}, ['id']),
    tool('remove_task', 'Remove a task. After the day has started this takes effect after a 30 second cooling-off, and the main task needs a replacement first.', {'id': ID}, ['id']),
    tool('cancel_change', 'Cancel a pending rewording, removal or main-task change during its cooling-off.', {'id': ID}, ['id']),
    tool('carry_over', 'Decide yesterday\'s unfinished tasks: keep them on today\'s list or drop them.',
         {'ids': {**STRINGS, 'description': 'Ids from "carried over"'}, 'keep': {'type': 'boolean'}}, ['ids', 'keep']),
    tool('start_day', 'Start the day. Needs at least one task, exactly one main task, and every carried-over task decided. Blocking stays on until tasks pass.'),
    tool('record_verdict', 'Record your review of one task. The note is shown under the task.',
         {'id': ID, 'passed': {'type': 'boolean'}, 'note': {'type': 'string', 'description': 'One dry, honest line, at most 120 characters'},
          'basis': {'type': 'string', 'enum': ['evidence', 'claim'], 'description': 'evidence if you inspected it yourself, claim if you judged their account'}}, ['id', 'passed', 'note', 'basis']),
    tool('block', 'Add websites (domains such as youtube.com) and apps (window classes from list_apps) to the blocklist.', {'sites': STRINGS, 'apps': STRINGS}),
    tool('unblock', 'Remove websites or apps from the blocklist. Refused once the day has started.', {'sites': STRINGS, 'apps': STRINGS}),
    tool('list_apps', 'List apps to match a name to something blockable: window classes open now, then installed apps as name=class (or name=site for web apps).'),
    tool('set_rules', 'Change the rules. strictness is the mode: honor, standard, hard or lockdown; it can be raised any time but lowered only before the day starts. mode "all": everything unlocks when every task passes; mode "earn": each pass earns minutes. reset is the HH:MM a new day begins. mode, minutes and reset are refused once the day has started.',
         {'strictness': {'type': 'string', 'enum': ['honor', 'standard', 'hard', 'lockdown']}, 'mode': {'type': 'string', 'enum': ['all', 'earn']},
          'minutes': {'type': 'integer'}, 'reset': {'type': 'string'}, 'hosts': {'type': 'boolean'}}),
    tool('set_look', 'Turn parts of the look on or off: borders (window borders turn red while locked), strip (a thin bar showing the main task while locked), sound.',
         {'borders': {'type': 'boolean'}, 'strip': {'type': 'boolean'}, 'sound': {'type': 'boolean'}}),
    tool('start_timer', 'Start a timer on a task that is about spending time ("read for 30 minutes"). You get an event when it finishes; a finished timer is evidence.',
         {'id': ID, 'minutes': {'type': 'integer'}}, ['id', 'minutes']),
    tool('request_folder', 'Ask the user to let you read a folder (their projects, their notes). They see the path and must approve it themselves. Their answer arrives as an event.',
         {'path': {'type': 'string', 'description': 'Full path, such as /home/name/Projects'}}, ['path']),
    tool('list_files', 'List a folder inside an approved folder.', {'path': {'type': 'string'}}, ['path']),
    tool('read_file', 'Read a text file inside an approved folder. Credentials and keys are never readable.',
         {'path': {'type': 'string'}, 'start': {'type': 'integer'}, 'lines': {'type': 'integer'}}, ['path']),
    tool('search_files', 'Search text files under an approved folder for a word or regular expression.',
         {'query': {'type': 'string'}, 'path': {'type': 'string'}, 'glob': {'type': 'string', 'description': 'Optional file name pattern such as *.py'}}, ['query', 'path']),
    tool('git_evidence', 'Look at a git repository inside an approved folder: status (uncommitted changes), log (recent commits), diff (working changes, or between two revisions as a..b), show (one commit).',
         {'repo': {'type': 'string'}, 'what': {'type': 'string', 'enum': ['status', 'log', 'diff', 'show']},
          'ref': {'type': 'string', 'description': 'A commit, branch or tag, or a..b for diff'}, 'path': {'type': 'string'}, 'limit': {'type': 'integer'}}, ['repo', 'what']),
    tool('open_link', 'Read a web page the user gave you as evidence. The first call asks them to approve that exact link; call again after the event says they did.',
         {'url': {'type': 'string'}}, ['url']),
    tool('look_at_screen', 'Ask to see the user\'s screen as proof. They approve the capture, see the image, and approve sending it; then an event tells you to call view_screenshot.'),
    tool('view_screenshot', 'See the screenshot the user approved. Available once, after the event says it is ready.'),
    tool('emergency_unlock', 'Begin an emergency unlock: the user is shown a 32 character code to type, then waits 60 seconds for 15 minutes of access. It is logged.'),
    tool('grade_day', 'Record a one-word grade and a one-line note for the day.', {'word': {'type': 'string'}, 'note': {'type': 'string'}}, ['word', 'note']),
    tool('suggest_reply', 'Offer the user\'s most likely reply as ghost text they can accept with Enter. Use it with any question that has an obvious answer.', {'text': {'type': 'string'}}, ['text']),
    tool('offer_choices', 'Show clickable answers under your question. Use it when there are two to six clear answers (which mode, keep or drop). multiple lets them pick several before sending.',
         {'options': STRINGS, 'multiple': {'type': 'boolean'}}, ['options']),
    tool('install_blocking_helper', 'Setup: install the system helper that makes website blocks hold in every browser. Shows the user one password prompt. The result arrives later as an event.'),
    tool('connect_browser', 'Setup: load the companion browser extension and register its local bridge. Takes effect when the browser restarts.'),
    tool('finish_setup', 'Setup: mark first-run setup complete. Blocking begins from here.'),
]

class Tools:
    """Dispatches tool calls. `host` supplies the things that reach outside the model."""
    def __init__(self, model, host):
        self.model, self.host = model, host

    def call(self, name, args, now):
        handler = getattr(self, 'tool_' + str(name), None)
        if handler is None: raise ValueError('Unknown tool.')
        self.now = now
        return handler(args if isinstance(args, dict) else {})

    def apply(self, op, **fields): return self.model.apply({'op': op, **fields}, self.now)
    def day(self): return self.model.tick(self.now)

    def tool_add_tasks(self, a):
        tasks = a.get('tasks')
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= 30: raise ValueError('Give 1 to 30 tasks.')
        before = {t['id'] for t in self.day()['tasks']}
        self.apply('plan-accept', tasks=tasks)
        return 'Added: ' + '; '.join('[%s] %s' % (t['id'], t['text']) for t in self.day()['tasks'] if t['id'] not in before)

    def tool_update_task(self, a):
        done, started = [], self.day()['started']
        if a.get('check') is not None:
            self.apply('check', id=a.get('id'), check=a['check']); done.append('check updated')
        if a.get('on_word') is not None:
            self.apply('trust', id=a.get('id'), value=bool(a['on_word'])); done.append('passes on their word' if a['on_word'] else 'needs evidence')
        if a.get('text'):
            self.apply('change', id=a.get('id'), action='edit', text=a['text']); done.append('reworded after the cooling-off unless cancelled' if started else 'reworded')
        if a.get('main'):
            # One pending change per task: a rewording requested in the same call wins after Start.
            if started and a.get('text'): done.append('main-task change not requested; ask again after the rewording lands')
            else:
                self.apply('change', id=a.get('id'), action='main'); done.append('becomes the main task after the cooling-off unless cancelled' if started else 'is now the main task')
        if not done: raise ValueError('Nothing to change.')
        return 'Task ' + ', '.join(done) + '.'

    def tool_remove_task(self, a):
        started = self.day()['started']
        self.apply('change', id=a.get('id'), action='delete')
        return 'Removal happens after the cooling-off (%d seconds) unless cancelled.' % (120 if self.model.s['settings']['strictness'] == 'hard' else 30) if started else 'Removed.'

    def tool_cancel_change(self, a):
        if a.get('id') not in self.day()['pending']: raise ValueError('Nothing is pending for that task.')
        self.apply('cancel', id=a.get('id'))
        return 'Cancelled.'

    def tool_carry_over(self, a):
        ids = a.get('ids')
        if not isinstance(ids, list) or not ids: raise ValueError('Give the ids to decide.')
        for ident in ids: self.apply('carry', id=ident, action='carry' if a.get('keep') else 'drop')
        return ('Kept %d.' if a.get('keep') else 'Dropped %d.') % len(ids)

    def tool_start_day(self, a):
        self.apply('start')
        return 'Day started. Blocked until tasks pass.'

    def tool_record_verdict(self, a):
        state = self.apply('verdict', id=a.get('id'), verdict='pass' if a.get('passed') else 'fail', note=a.get('note'),
                           basis=a.get('basis') or 'evidence', by='agent')
        left = state['total'] - state['completed']
        return 'Recorded. ' + ('Everything has passed; the user is unlocked.' if state['fullUnlock'] else '%d left. %s' % (left, 'Locked.' if state['locked'] else 'Unlocked for now.'))

    def lists(self, a):
        sites, apps = a.get('sites') or [], a.get('apps') or []
        if not isinstance(sites, list) or not isinstance(apps, list) or not (sites or apps): raise ValueError('Give sites or apps.')
        return sites, apps, self.model.s['settings']

    def tool_block(self, a):
        sites, apps, current = self.lists(a)
        state = self.apply('settings', values={'sites': current['sites'] + sites, 'apps': current['apps'] + apps})
        return 'Blocked. Sites: %s. Apps: %s.' % (', '.join(state['settings']['sites']) or 'none', ', '.join(state['settings']['apps']) or 'none')

    def tool_unblock(self, a):
        sites, apps, current = self.lists(a)
        lowered = {s.lower().removeprefix('www.') for s in sites}
        state = self.apply('settings', values={'sites': [s for s in current['sites'] if s not in lowered],
                                               'apps': [x for x in current['apps'] if x not in apps]})
        return 'Unblocked. Sites: %s. Apps: %s.' % (', '.join(state['settings']['sites']) or 'none', ', '.join(state['settings']['apps']) or 'none')

    def tool_list_apps(self, a):
        installed = self.host.installed_apps()[:150]
        return 'Open window classes: %s\nInstalled: %s' % (', '.join(self.host.open_apps()) or 'none', ', '.join('%s=%s' % pair for pair in installed) or 'none found')

    def tool_set_rules(self, a):
        values = {k: a[k] for k in ('strictness', 'mode', 'minutes', 'reset', 'hosts') if a.get(k) is not None}
        if not values: raise ValueError('Nothing to change.')
        self.apply('settings', values=values)
        return 'Rules updated.'

    def tool_set_look(self, a):
        values = {k: a[k] for k in ('borders', 'strip', 'sound') if a.get(k) is not None}
        if not values: raise ValueError('Nothing to change.')
        self.apply('settings', values=values)
        return 'Look updated.'

    def tool_start_timer(self, a):
        self.apply('timer', id=a.get('id'), minutes=a.get('minutes'))
        return 'Timer running. It shows on the task; you get an event when it finishes.'

    def roots(self): return evidence.approved(self.model.s['settings'])

    def tool_request_folder(self, a):
        return self.host.ask('folder', rules.folder(a.get('path')))

    def tool_list_files(self, a): return evidence.list_files(a.get('path'), self.roots())
    def tool_read_file(self, a): return evidence.read_file(a.get('path'), self.roots(), a.get('start'), a.get('lines'))
    def tool_search_files(self, a): return evidence.search_files(a.get('query'), a.get('path'), self.roots(), a.get('glob') or '')
    def tool_git_evidence(self, a): return evidence.git(a.get('repo'), a.get('what'), self.roots(), a.get('ref') or '', a.get('path') or '', a.get('limit'))

    def tool_open_link(self, a):
        url = evidence.check_url(a.get('url')).geturl()
        if not self.host.link_allowed(url): return self.host.ask('link', url)
        return evidence.fetch(url, self.host.link_allowed)

    def tool_look_at_screen(self, a):
        return self.host.ask('screen', '')

    def tool_view_screenshot(self, a):
        # The image itself is attached by the service; this only exists so the tool is real everywhere.
        return self.host.shared_screenshot()

    def tool_emergency_unlock(self, a):
        self.apply('challenge')
        return 'The code is on screen. The user must type it exactly, then wait 60 seconds. Do not repeat the code.'

    def tool_grade_day(self, a):
        self.apply('grade', word=(str(a.get('word') or '').split() or ['Ungraded'])[0][:40], note=a.get('note') or '')
        return 'Graded.'

    def tool_suggest_reply(self, a):
        self.host.suggest(a.get('text'))
        return 'Shown.'

    def tool_offer_choices(self, a):
        options = a.get('options')
        if not isinstance(options, list) or not 2 <= len(options) <= 12: raise ValueError('Offer 2 to 12 options.')
        self.host.choose(options, a.get('multiple'))
        return 'Shown.'

    def tool_install_blocking_helper(self, a):
        return self.host.install_helper()

    def tool_connect_browser(self, a):
        return 'Connected: %s. It loads when the browser next starts.' % ', '.join(self.host.connect_browser())

    def tool_finish_setup(self, a):
        self.host.validate_setup()
        self.apply('setup-done')
        return 'Setup complete.'
