let port;
let current;
let queue = Promise.resolve();
let signature = '';
const blockedPage = chrome.runtime.getURL('blocked.html');
function matches(url, sites) {
  try {
    const parsed = new URL(url);
    return ['http:', 'https:'].includes(parsed.protocol) && sites.some(site => parsed.hostname === site || parsed.hostname.endsWith('.' + site));
  } catch { return false; }
}
async function redirect(tabId, url) {
  if (!matches(url, current?.settings?.sites || current?.sites || [])) return;
  await chrome.tabs.update(tabId, {url: blockedPage + '#' + encodeURIComponent(url)}).catch(() => {});
  port?.postMessage({action: 'blocked', host: new URL(url).hostname});
}
async function apply(state) {
  if (state.effect) { await chrome.storage.session.set({effect: state.effect}); return; }
  if (state.connected === false) {
    current = {...current, connected: false, error: state.error};
    await chrome.storage.local.set({state: current});
    return;
  }
  current = {...state, connected: true};
  const sites = [...new Set(state.settings?.sites || state.sites || [])];
  const nextSignature = JSON.stringify([state.locked, sites]);
  if (signature !== nextSignature) {
    const rules = state.locked ? sites.map((site, index) => ({
      id: index + 1, priority: 1,
      action: {type: 'redirect', redirect: {regexSubstitution: blockedPage + '#\\0'}},
      condition: {requestDomains: [site], regexFilter: '^https?://.*', resourceTypes: ['main_frame']}
    })) : [];
    const old = await chrome.declarativeNetRequest.getDynamicRules();
    await chrome.declarativeNetRequest.updateDynamicRules({removeRuleIds: old.map(r => r.id), addRules: rules});
    signature = nextSignature;
    if (state.locked) {
      for (const tab of await chrome.tabs.query({})) {
        if (matches(tab.url, sites)) await redirect(tab.id, tab.url);
      }
    }
  }
  await chrome.storage.local.set({state: current});
  await chrome.action.setBadgeText({text: state.locked ? String(state.total - state.completed) : ''});
}
function connect() {
  if (port) return;
  port = chrome.runtime.connectNative('local.omarchy.focus');
  port.onMessage.addListener(state => {
    queue = queue.then(() => apply(state)).catch(error => console.error('Focus:', error));
  });
  port.onDisconnect.addListener(() => {
    const error = chrome.runtime.lastError?.message || 'Disconnected';
    port = null;
    signature = '';
    chrome.storage.local.get('state').then(({state}) => chrome.storage.local.set({state: {...state, connected: false, error}}));
    chrome.alarms.create('reconnect', {delayInMinutes: 0.5});
  });
}
// Managed policy can reject a navigation before an extension redirect runs.
chrome.webNavigation.onErrorOccurred.addListener(details => {
  if (details.frameId === 0 && current?.locked && details.error.includes('BLOCKED_BY_ADMINISTRATOR')) redirect(details.tabId, details.url);
});
chrome.alarms.onAlarm.addListener(connect);
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.action.onClicked.addListener(() => { connect(); port?.postMessage({action: 'open'}); });
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id) return;
  if (['open','blocked','effect','back'].includes(message.action)) { connect(); port?.postMessage({action: message.action}); }
  reply({ok: true});
});
chrome.storage.local.get('state').then(({state}) => { current = current || state; connect(); });
