const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function harness() {
  const events = {};
  const writes = [], redirects = [], sent = [];
  let rules = [];
  const event = name => ({addListener(fn) { events[name] = fn; }});
  const port = {onMessage: event('native'), onDisconnect: event('disconnect'), postMessage(m) { sent.push(m); }};
  const chrome = {
    runtime: {id: 'focus', getURL: p => 'chrome-extension://focus/' + p, connectNative: () => port,
      onStartup: event('startup'), onInstalled: event('installed'), onMessage: event('message')},
    declarativeNetRequest: {getDynamicRules: async () => rules, updateDynamicRules: async r => { rules = r.addRules; writes.push(r); }},
    storage: {local: {get: async () => ({}), set: async data => { events.stored = data; }}, session: {set: async data => { events.effect = data; }}},
    action: {setBadgeText: async () => {}, onClicked: event('click')},
    tabs: {query: async () => [{id: 1, url: 'https://m.youtube.com/watch'}, {id: 2, url: 'https://notyoutube.com/'}], update: async (id, opts) => redirects.push([id, opts])},
    alarms: {create: () => {}, onAlarm: event('alarm')}, webNavigation: {onErrorOccurred: event('navigationError')}
  };
  const context = vm.createContext({chrome, URL, console});
  vm.runInContext(fs.readFileSync(require.resolve('../browser/extension/background.js'), 'utf8'), context);
  return {context, events, writes, redirects, sent, rules: () => rules};
}
const state = {connected: true, locked: true, total: 2, completed: 0, settings: {sites: ['youtube.com']}};
test('domain redirects include subdomains without matching lookalikes', async () => {
  const h = harness(); await vm.runInContext(`apply(${JSON.stringify(state)})`, h.context);
  assert.equal(h.rules().length, 1); assert.equal(h.redirects.length, 1); assert.equal(h.redirects[0][0], 1);
});
test('clock updates do not repeatedly rebuild dynamic rules', async () => {
  const h = harness(); await vm.runInContext(`apply(${JSON.stringify(state)})`, h.context);
  await vm.runInContext(`apply(${JSON.stringify({...state, remainingSeconds: 42})})`, h.context);
  assert.equal(h.writes.length, 1);
});
test('unlock removes extension blocking, disconnect keeps last known lock', async () => {
  const h = harness(); await vm.runInContext(`apply(${JSON.stringify(state)})`, h.context);
  await vm.runInContext(`apply({connected:false,error:'offline'})`, h.context);
  assert.equal(h.rules().length, 1);
  await vm.runInContext(`apply(${JSON.stringify({...state, locked: false})})`, h.context);
  assert.equal(h.rules().length, 0);
});
test('policy-blocked top-level navigation goes to the local page', async () => {
  const h = harness(); await vm.runInContext(`apply(${JSON.stringify(state)})`, h.context);
  h.events.navigationError({frameId:0, tabId:3, url:'https://youtube.com/', error:'net::ERR_BLOCKED_BY_ADMINISTRATOR'});
  await Promise.resolve(); assert.equal(h.redirects.at(-1)[0], 3);
  assert.match(h.redirects.at(-1)[1].url, /^chrome-extension:\/\/focus\/blocked.html#/);
});
test('effect frames use session storage and never change blocking rules', async () => {
  const h = harness(); await vm.runInContext(`apply({effect:{frame:'TODAY',done:true}})`, h.context);
  assert.equal(h.events.effect.effect.frame, 'TODAY'); assert.equal(h.writes.length, 0);
});
test('messages from unrelated extensions cannot invoke the native bridge', async () => {
  const h = harness(); await Promise.resolve();
  h.events.message({action:'open'}, {id:'other'}, ()=>{}); assert.equal(h.sent.length, 0);
});
