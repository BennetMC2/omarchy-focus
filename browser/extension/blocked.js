const byId = id => document.getElementById(id);
let destination = '';
let attemptedReturn = false;
try {
  let raw = location.hash.slice(1);
  if (!/^https?:/.test(raw)) raw = decodeURIComponent(raw);
  const url = new URL(raw);
  if (['http:', 'https:'].includes(url.protocol)) destination = url.href;
} catch {}
function render(state = {}) {
  for (const [key, value] of Object.entries(state.theme || {})) {
    if (/^#[0-9a-f]{6}$/i.test(value)) document.documentElement.style.setProperty('--' + key, value);
  }

  const tasks = state.tasks || [];
  const remaining = tasks.filter(task => task.status !== 'passed');
  const priority = remaining.find(task => task.main) || remaining[0];
  const connected = state.connected === true;
  const unlocked = connected && state.locked === false;
  const host = destination ? new URL(destination).hostname.replace(/^www\./, '') : 'That site';
  byId('count').textContent = (state.completed || 0) + ' of ' + (state.total || 0) + ' done';
  byId('status').textContent = connected ? (unlocked ? 'Access restored' : 'Bouncer is on duty') : 'Bouncer is offline';
  byId('headline').textContent = !connected ? 'Hold on.' : unlocked ? 'You’re clear.' : 'Not yet.';
  byId('context').textContent = !connected ? 'Reconnecting to Bouncer. Your last task list is below.' : unlocked ? 'Your break is yours. Enjoy it.' : host + ' can wait.' + (priority ? ' You picked this first.' : ' Check in with Bouncer to continue.');
  byId('priority').hidden = !priority || unlocked;
  byId('priority-label').textContent = priority?.main ? 'Main task' : 'Up next';
  byId('priority-title').textContent = priority?.text || '';
  byId('priority-note').textContent = priority?.note || '';
  byId('priority-note').hidden = !priority?.note;
  byId('empty').hidden = !!priority || unlocked;
  byId('empty').textContent = !connected ? 'Open Bouncer to check the connection.' : 'Open Bouncer to review your day.';
  byId('task-list').hidden = tasks.length === 0;
  byId('task-summary').textContent = 'View all ' + tasks.length + (tasks.length === 1 ? ' task' : ' tasks');
  byId('tasks').replaceChildren();
  for (const task of tasks) {
    const item = document.createElement('li');
    const passed = task.status === 'passed';
    item.classList.toggle('passed', passed);
    const mark = document.createElement('span');
    mark.className = 'task-mark';
    mark.textContent = passed ? '✓' : '○';
    mark.setAttribute('aria-label', passed ? 'Completed' : 'Incomplete');
    const content = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'task-title';
    title.textContent = task.text;
    content.append(title);
    if (task.note) {
      const note = document.createElement('p');
      note.className = 'note'; note.textContent = task.note; content.append(note);
    }
    item.append(mark, content);
    byId('tasks').append(item);
  }
  byId('detail').textContent = state.connected ? 'Day resets at ' + (state.settings?.reset || '04:00') + '. Tasks require an agent verdict.' : (state.error || 'Waiting for the local service.');
  if (state.connected && state.locked === false && destination && !attemptedReturn) {
    attemptedReturn = true;
    // Avoid loops if managed policy has not refreshed yet.
    const key = 'focus-return:' + destination;
    const last = Number(sessionStorage.getItem(key) || 0);
    if (Date.now() - last > 30000) { sessionStorage.setItem(key, String(Date.now())); location.replace(destination); }
    else byId('detail').textContent = 'Waiting for browser policy refresh. Return to the site after policies update.';
  }
}
chrome.storage.local.get('state').then(({state}) => render(state));
chrome.storage.onChanged.addListener(changes => {
  if (changes.state) render(changes.state.newValue);

});
chrome.runtime.sendMessage({action: 'blocked'});
byId('back').onclick = () => { chrome.runtime.sendMessage({action:'back'}); };
byId('done').onclick = () => { chrome.runtime.sendMessage({action:'open'}); };
