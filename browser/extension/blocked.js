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
  document.body.hidden = !state.theme?.foreground;
  byId('count').textContent = (state.completed || 0) + '/' + (state.total || 0);
  byId('status').textContent = state.connected ? (state.locked ? 'Blocked' : 'Unlocked') : 'Bouncer is offline';
  byId('tasks').replaceChildren();
  for (const task of state.tasks || []) {
    if (task.status === 'passed') continue;
    const item = document.createElement('li');
    const title = document.createElement('div');
    title.textContent = (task.main ? '★ ' : '') + task.text;
    item.append(title);
    if (task.note) {
      const note = document.createElement('p'); note.textContent = task.note; item.append(note);
    }
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
  if (changes.effect) {
    const effect = changes.effect.newValue;
    byId('matrix').textContent = effect.frame;
    byId('matrix').hidden = effect.done;
    byId('tasks').hidden = !effect.done;
  }
});
chrome.runtime.sendMessage({action: 'blocked'});
chrome.runtime.sendMessage({action: 'effect'});
byId('back').onclick = () => { chrome.runtime.sendMessage({action:'back'}); };
byId('done').onclick = () => { chrome.runtime.sendMessage({action:'open'}); };
