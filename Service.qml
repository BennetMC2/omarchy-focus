import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

// Owns the Focus service process and a live connection to it. State and conversation are pushed, not polled.
Item {
  id: root
  property var shell: null
  property var state: ({tasks: [], carry: [], settings: {}, pending: {}, overrides: [], setup: true})
  property var chat: ({messages: [], streaming: "", activity: "", suggestion: "", busy: false})
  property string view: ""
  property string error: ""
  property bool ready: false
  // Set when a ping goes out, cleared by anything coming back. Still set at the next ping: the link is dead.
  property bool unanswered: false
  property bool screenLocked: true
  property bool lockKnown: false
  // Dismissing the card before the day has started snoozes it; blocking is unaffected.
  property real snoozeUntil: 0
  // Reopen after a password prompt has had the screen to itself.
  property bool reopenAfterAuth: false
  property string screenName: ""
  property real clock: Date.now() / 1000
  property real lastBlocked: 0
  // The morning briefing plays once per day, not on every snoozed reopening.
  property bool morningShown: false
  // A takeover plays over the screen before the card: "denied" at a block, "granted" at the unlock, "morning" on a new day.
  property real alarmAt: 0
  property string alarmKind: ""
  property string alarmName: ""
  // view is "" (closed), "open" (the dropdown under the bar icon) or "takeover" (a full-screen moment).
  function takeover(kind, name) {
    snoozeUntil = 0
    if (!lockProbe.running) lockProbe.running = true
    alarmKind = kind
    alarmName = name
    alarmAt = Date.now()
    var fresh = !view
    view = "takeover"
    focusScreen()
    if (fresh) send({op: "opened"})
    if (shell) shell.summon("local.focus", "{}")
  }
  // The moment has played: the dropdown takes over, except after locking in, when you get on with it.
  function endTakeover() {
    if (view !== "takeover") return
    alarmAt = 0
    if (alarmKind === "start") { view = ""; send({op: "closed"}) }
    else view = "open"
    if (shell) shell.hide("local.focus")
  }
  // The host tells us the full-screen surface went away; only a takeover the user dismissed needs cleaning up.
  function overlayClosed() { if (view === "takeover") dismissed() }
  function focusScreen() {
    var monitor = Hyprland.focusedMonitor
    screenName = monitor ? monitor.name : ""
  }
  function alarm(name) { takeover("denied", name) }
  // Previews show a look without changing any state.
  property string skinPreview: ""
  property bool stripPreview: false
  Timer { id: stripPreviewOff; interval: 6000; onTriggered: root.stripPreview = false }
  readonly property string script: decodeURIComponent(Qt.resolvedUrl("focus.py").toString().replace("file://", ""))
  readonly property string socketPath: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/local.focus/control.sock"
  // First-run setup introduces itself once and then waits to be opened; an unstarted day keeps asking.
  readonly property bool wantsAttention: ready && (!state.setup ? !state.introduced : (!state.started && !state.recovered))

  signal submissionFinished(string id, bool ok, string message)
  function send(command) {
    if (!link.connected) return false
    link.write(JSON.stringify(command) + "\n")
    link.flush()
    return true
  }
  function say(text) { send({op: "say", text: text}) }

  function show(screen) {
    if (!lockProbe.running) lockProbe.running = true
    if (view === "open") return
    var fresh = !view
    if (screen) screenName = screen
    else focusScreen()
    view = "open"
    if (fresh) send({op: "opened"})
  }
  function openHome(screen) { snoozeUntil = 0; show(screen) }
  // View state only; the host calls this from shell.hide(), so never call shell.hide() here.
  function dismissed() {
    if (!view) return
    if (wantsAttention && !state.auth) snoozeUntil = Date.now() + 600000
    view = ""
    alarmAt = 0
    skinPreview = ""
    send({op: "closed"})
  }
  function close() {
    if (!view) return
    var overlay = view === "takeover"
    dismissed()
    if (overlay && shell) shell.hide("local.focus")
  }
  function autoOpen() {
    if (!(wantsAttention && lockKnown && !screenLocked && !view && !state.auth && Date.now() >= snoozeUntil)) return
    if (state.setup && !morningShown) { morningShown = true; takeover("morning", "") }
    else show()
  }

  function receive(line) {
    var message
    try { message = JSON.parse(line) } catch (e) { return }
    unanswered = false
    if (message.requestId) submissionFinished(message.requestId, message.ok !== false, message.error || "")
    if (message.ok === false) {
      error = message.error || "Refused."
      errorClear.restart()
      return
    }
    if (message.chat) chat = message.chat
    if (!message.state) return
    var next = message.state
    // Keep list identity across unrelated updates so rows are not rebuilt.
    for (var key of ["tasks", "carry", "settings", "pending", "overrides", "challenge"]) {
      if (JSON.stringify(next[key]) === JSON.stringify(state[key])) next[key] = state[key]
    }
    var unlocked = ready && state.started && state.locked && next.started && next.fullUnlock
    var began = ready && !state.started && next.started && state.date === next.date
    if (state.date !== next.date) morningShown = false
    state = next
    ready = true
    // The card steps aside for a password prompt or a screenshot, then comes back.
    var aside = next.auth || next.capture
    if (aside && view) { reopenAfterAuth = true; close() }
    if (!aside && reopenAfterAuth) { reopenAfterAuth = false; show() }
    if (unlocked && !screenLocked) takeover("granted", "")
    if (began && !screenLocked) takeover("start", "")
    if (next.blockedAt > lastBlocked) {
      var first = lastBlocked === 0
      lastBlocked = next.blockedAt
      if (!first && !screenLocked) alarm(next.blockedName || "")
    }
    autoOpen()
  }

  Process {
    id: daemon
    command: ["/usr/bin/python3", root.script, "serve"]
    running: true
    onExited: restartDaemon.restart()
  }
  Timer { id: restartDaemon; interval: 1500; onTriggered: daemon.running = true }

  Socket {
    id: link
    path: root.socketPath
    parser: SplitParser { onRead: function(line) { root.receive(line) } }
    onConnectionStateChanged: {
      if (!connected) return
      root.send({op: "subscribe"})
      if (root.view) root.send({op: "opened"})
    }
  }
  // The service can restart underneath us; reconnect until it answers again.
  Timer {
    interval: 800; running: !root.ready; repeat: true; triggeredOnStart: true
    onTriggered: { link.connected = false; link.connected = true }
  }
  Timer {
    interval: 2500; running: root.ready; repeat: true
    onTriggered: {
      if (root.unanswered) { root.unanswered = false; root.ready = false; return }
      root.unanswered = true
      root.send({op: "ping"})
    }
  }
  Timer { id: errorClear; interval: 6000; onTriggered: root.error = "" }
  Timer { interval: 500; running: root.view !== ""; repeat: true; triggeredOnStart: true; onTriggered: root.clock = Date.now() / 1000 }

  // The session lock is only worth asking about while the card is waiting to show itself.
  Process {
    id: lockProbe
    command: ["omarchy-shell", "lock", "isLocked"]
    stdout: StdioCollector {
      onStreamFinished: {
        var value = text.trim()
        if (value !== "true" && value !== "false") return
        root.screenLocked = value === "true"
        root.lockKnown = true
        root.autoOpen()
      }
    }
  }
  Timer {
    interval: 2000; repeat: true; triggeredOnStart: true
    running: !root.lockKnown || (root.wantsAttention && !root.view)
    onTriggered: if (!lockProbe.running) lockProbe.running = true
  }

  // A browser showing a blocked page titles the tab with the address it could not load. Watching window titles
  // catches that in any browser, whether or not the companion extension is loaded.
  property real lastTitleAlarm: 0
  function blockedSite(title) {
    var parts = String(title || "").split(/ [-–—] /)
    var head = (parts.length > 1 ? parts.slice(0, -1).join(" - ") : parts[0]).trim().toLowerCase()
    if (!head || /\s/.test(head)) return ""
    var host = head.replace(/^https?:\/\//, "").split("/")[0].replace(/^www\./, "")
    var sites = state.settings.sites || []
    for (var i = 0; i < sites.length; i++) if (host === sites[i] || host.endsWith("." + sites[i])) return sites[i]
    return ""
  }
  function watchTitle(title) {
    if (!ready || !state.locked || screenLocked || view || Date.now() - lastTitleAlarm < 4000) return
    var site = blockedSite(title)
    if (!site) return
    lastTitleAlarm = Date.now()
    send({op: "blocked", name: site})
    alarm(site)
  }
  Connections {
    target: Hyprland
    function onRawEvent(event) {
      var name = String(event.name), data = String(event.data || "")
      if (["openwindow", "movewindow", "movewindowv2", "pin"].indexOf(name) >= 0 && root.ready && root.state.locked) root.send({op: "window"})
      // activewindow carries "class,title"; windowtitlev2 carries "address,title".
      if (name === "activewindow" || name === "windowtitlev2") root.watchTitle(data.slice(data.indexOf(",") + 1))
    }
  }

  MissionStrip { service: root }

  IpcHandler {
    target: "local.focus"
    function open(): void { root.openHome() }
    function openView(mode: string): void { mode === "blocked" ? blocked("") : root.openHome() }
    function blocked(name: string): void {
      root.send({op: "blocked", name: name})
      root.alarm(name)
    }
    function close(): void { root.close() }
    function toggle(): void { root.view ? root.close() : root.openHome() }
    function say(text: string): void { root.say(text) }
    // Shows a look without changing anything: denied, granted, morning, start, strip, honor, hard or lockdown.
    function preview(kind: string): void {
      if (kind === "strip") { root.stripPreview = true; stripPreviewOff.restart() }
      else if (kind === "honor" || kind === "hard" || kind === "lockdown") { root.skinPreview = kind; root.openHome() }
      else root.takeover(kind, kind === "denied" ? "youtube.com" : "")
    }
    function status(): string { return JSON.stringify(root.state) }
  }
}
