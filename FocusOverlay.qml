import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui as Ui

// The whole of Focus: today's list, what the agent last said, and one prompt. No buttons.
Item {
  id: root
  property var service: null
  readonly property var snapshot: service ? service.state : ({tasks: [], carry: [], settings: {}, pending: {}, overrides: [], setup: true})
  readonly property var chat: service ? service.chat : ({messages: [], streaming: "", activity: "", suggestion: "", busy: false})
  readonly property real clock: service ? service.clock : 0
  readonly property bool open: !!service && service.view !== "" && !service.screenLocked
  readonly property var spinnerFrames: ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
  property int spinnerFrame: 0
  // The reply being written counts as the newest message.
  readonly property var lines: {
    var shown = (chat.messages || []).slice(-3)
    if (chat.streaming) shown = shown.slice(-2).concat([{role: "agent", text: chat.streaming, live: true}])
    return shown
  }
  readonly property string strictness: (service && service.skinPreview) || snapshot.settings.strictness || "standard"
  // Lockdown runs in the theme's red; hard and lockdown get scanlines.
  readonly property color tone: strictness === "lockdown" ? Color.urgent : Color.accent
  readonly property bool harsh: strictness === "hard" || strictness === "lockdown"
  readonly property string rank: {
    var days = snapshot.streak || 0
    return days >= 30 ? "ghost" : days >= 14 ? "veteran" : days >= 7 ? "specialist" : days >= 3 ? "operator" : days >= 1 ? "initiate" : "drifter"
  }
  readonly property string kind: service ? service.alarmKind : ""
  readonly property string bannerTitle: kind === "granted" ? "ACCESS GRANTED" : kind === "morning" ? "NEW DAY" : "ACCESS DENIED"
  readonly property string bannerLine: {
    if (kind === "granted") return "everything is unlocked. good work."
    if (kind === "morning") {
      var y = snapshot.yesterday
      return (y ? "yesterday " + y.completed + " of " + y.total + (y.grade ? " · " + y.grade.toLowerCase() : "") + " · " : "") + "rank " + rank + " · everything is locked"
    }
    return (service && service.alarmName ? service.alarmName : "that one") + " is locked until today's work is done"
  }
  function clockText(until) {
    var left = Math.max(0, Math.ceil(until - clock))
    return Math.floor(left / 60) + ":" + ("0" + (left % 60)).slice(-2)
  }
  readonly property string status: {
    if (!snapshot.setup) return "setting up"
    if (snapshot.recovered) return "recovery · blocking off"
    var count = snapshot.total ? (snapshot.completed || 0) + " of " + snapshot.total + " · " : ""
    if (!snapshot.started) return count + "not started"
    if (snapshot.locked) return count + "locked"
    if (snapshot.fullUnlock) return count + "unlocked"
    return count + "unlocked " + Math.max(1, Math.ceil(((snapshot.until || 0) - clock) / 60)) + "m"
  }
  readonly property string blockedSummary: {
    var all = (snapshot.settings.sites || []).concat(snapshot.settings.apps || [])
    if (!all.length) return "nothing blocked yet"
    return all.slice(0, 5).join(" · ") + (all.length > 5 ? " +" + (all.length - 5) : "")
  }
  // The takeover that plays when something blocked was just reached.
  readonly property bool alarm: !!service && service.alarmAt > 0
  property real alarmElapsed: 0
  property string quote: ""
  readonly property bool intro: alarm && alarmElapsed < 2900
  readonly property var quotes: [
    "The work is the way out.",
    "Do the hard thing first. It only gets heavier.",
    "You don't need motivation. You need twenty minutes.",
    "Nobody ships from the feed.",
    "Start badly. Fix it after.",
    "One task. Then the next. That's the whole trick.",
    "Scrolling is rented time. Shipping is owned.",
    "Close the tab. Open the editor.",
    "Done beats perfect, and both beat YouTube.",
    "Future you is watching. Give them nothing to complain about."
  ]
  readonly property real alarmAt: service ? service.alarmAt : 0
  onAlarmAtChanged: if (alarmAt > 0) { alarmElapsed = 0; quote = quotes[Math.floor(Math.random() * quotes.length)] }
  Timer { interval: 40; running: root.open && root.alarm && root.alarmElapsed < 4000; repeat: true; onTriggered: root.alarmElapsed = Date.now() - root.service.alarmAt }
  // Letters lock into place left to right out of noise.
  function decode(target, elapsed, start, pace) {
    var shown = Math.floor((elapsed - start) / pace), noise = "0123456789ABCDEF#$%&@", out = ""
    if (shown < 0) return ""
    for (var i = 0; i < target.length; i++)
      out += i < shown || target.charAt(i) === " " ? target.charAt(i) : noise.charAt(Math.floor(Math.random() * noise.length))
    return out
  }
  // Clickable answers the agent (or the first-run question) is offering.
  readonly property string choicesKey: JSON.stringify(chat.choices || null)
  readonly property var choices: { var c = JSON.parse(choicesKey); return c ? c.options || [] : [] }
  readonly property bool manyChoices: { var c = JSON.parse(choicesKey); return !!c && !!c.multiple }
  property var picked: []
  onChoicesKeyChanged: picked = []
  function pick(option) {
    if (!manyChoices) { service.say(option); return }
    picked = picked.indexOf(option) >= 0 ? picked.filter(function(o) { return o !== option }) : picked.concat([option])
  }
  function seconds(until) { return Math.max(0, Math.ceil(until - clock)) }
  function pendingText(change) {
    var verb = change.action === "delete" ? "drops" : change.action === "main" ? "becomes main" : "rewords"
    return verb + " in " + seconds(change.readyAt) + "s · say cancel to stop it"
  }

  Timer { interval: 80; running: root.open && !!root.chat.busy; repeat: true; onTriggered: root.spinnerFrame = (root.spinnerFrame + 1) % root.spinnerFrames.length }

  Variants {
    model: Quickshell.screens
    delegate: PanelWindow {
      id: window
      required property var modelData
      screen: modelData
      visible: root.open && (root.service.screenName === "" || modelData.name === root.service.screenName)
      anchors { top: true; bottom: true; left: true; right: true }
      exclusionMode: ExclusionMode.Ignore
      color: "transparent"
      WlrLayershell.namespace: "local-focus-overlay"
      WlrLayershell.layer: WlrLayer.Overlay
      WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
      onVisibleChanged: if (visible) Qt.callLater(function() { prompt.forceActiveFocus() })

      Rectangle { anchors.fill: parent; color: Color.menu.scrim }
      MatrixRain {
        anchors.fill: parent
        visible: root.alarm
        ink: root.kind === "granted" ? Color.accent : root.tone
        running: root.alarm && window.visible
        opacity: root.intro ? 1 : 0.22
        Behavior on opacity { NumberAnimation { duration: 500 } }
      }
      MouseArea { anchors.fill: parent; onClicked: root.service.close() }
      Column {
        anchors.centerIn: parent
        spacing: Style.space(18)
        visible: opacity > 0
        opacity: root.intro && root.alarmElapsed > 250 ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 260 } }
        Rectangle {
          id: plate
          anchors.horizontalCenter: parent.horizontalCenter
          width: banner.implicitWidth + Style.space(72); height: banner.implicitHeight + Style.space(56)
          color: Util.alpha(Color.background, 0.92)
          border.color: root.kind === "denied" ? Color.urgent : root.tone; border.width: Math.max(1, Style.space(2))
          // A denial lands with a jolt.
          readonly property bool jolt: root.kind === "denied" && root.alarmElapsed < 420
          transform: Translate { x: plate.jolt ? (Math.random() - 0.5) * Style.space(18) * (1 - root.alarmElapsed / 420) : 0 }
          Column {
            id: banner
            anchors.centerIn: parent
            spacing: Style.space(14)
            Item {
              anchors.horizontalCenter: parent.horizontalCenter
              width: title.implicitWidth; height: title.implicitHeight
              // Two offset ghosts split the colours for the first moments of a denial.
              Repeater {
                model: root.kind === "denied" && root.alarmElapsed < 700 ? [-1, 1] : []
                delegate: Line {
                  required property int modelData
                  text: title.text; font: title.font
                  color: modelData < 0 ? Color.urgent : Color.accent; opacity: 0.55
                  x: modelData * Style.space(5) * (1 - root.alarmElapsed / 700)
                }
              }
              Line {
                id: title
                text: root.decode(root.bannerTitle, root.alarmElapsed, 300, 45)
                color: root.kind === "denied" ? Color.urgent : root.tone
                font.pixelSize: Style.font.displayLarge * 2; font.weight: Font.Bold; font.letterSpacing: Style.space(6)
              }
            }
            Line {
              anchors.horizontalCenter: parent.horizontalCenter
              text: root.decode(root.bannerLine, root.alarmElapsed, 900, 14)
              font.pixelSize: Style.font.heading
            }
            Line {
              anchors.horizontalCenter: parent.horizontalCenter
              visible: root.kind === "denied"
              opacity: root.alarmElapsed > 1700 ? 0.7 : 0
              Behavior on opacity { NumberAnimation { duration: 300 } }
              text: root.quote
              color: Color.menu.text; font.pixelSize: Style.font.subtitle; font.italic: true
            }
          }
        }
      }

      Ui.BorderSurface {
        id: card
        readonly property int pad: Style.space(28)
        width: Math.min(Style.space(760), parent.width - Style.gapsOut * 8)
        height: Math.min(body.implicitHeight + pad * 2, parent.height - Style.gapsOut * 8)
        x: (parent.width - width) / 2
        // Grows downward from a fixed line, like a launcher, so the prompt never jumps.
        y: Math.max(Style.gapsOut * 4, Math.min(parent.height * 0.18, parent.height - height - Style.gapsOut * 4))
        color: Color.menu.background
        borderSpec: Border.surfaceSpec("menu", "border", root.strictness === "lockdown" ? root.tone : Color.menu.border, Math.max(1, Style.space(2)))
        radius: Style.cornerRadius
        opacity: root.intro ? 0 : 1
        // Fades in after a takeover; vanishes at once when one begins.
        Behavior on opacity { enabled: !root.intro; NumberAnimation { duration: 320 } }
        Behavior on height { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
        MouseArea { anchors.fill: parent }
        Canvas {
          // Scanlines, for the stricter modes.
          anchors.fill: parent
          visible: root.harsh
          opacity: 0.07
          onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            ctx.fillStyle = root.tone
            for (var y = 0; y < height; y += 3) ctx.fillRect(0, y, width, 1)
          }
          onVisibleChanged: requestPaint()
          onHeightChanged: requestPaint()
        }

        ColumnLayout {
          id: body
          anchors { left: parent.left; right: parent.right; top: parent.top; margins: card.pad }
          spacing: Style.space(16)

          RowLayout {
            Layout.fillWidth: true
            Line { text: "FOCUS" + (root.strictness !== "standard" ? " // " + root.strictness.toUpperCase() : ""); color: root.strictness === "lockdown" ? root.tone : Color.menu.text; font.pixelSize: Style.font.title; font.weight: Font.Bold; font.letterSpacing: Style.space(4); Layout.fillWidth: true }
            Line { text: "[ " + (root.snapshot.setup ? root.rank.toUpperCase() + " · " : "") + root.status.toUpperCase() + " ]"; color: root.snapshot.locked && root.snapshot.setup ? root.tone : Color.muted; font.pixelSize: Style.font.bodySmall; font.letterSpacing: Style.space(1) }
          }
          Rectangle {
            Layout.fillWidth: true; Layout.topMargin: -Style.space(6); height: Math.max(1, Style.space(2))
            color: Util.alpha(Color.menu.text, 0.12)
            Rectangle {
              height: parent.height; color: root.tone
              width: parent.width * (root.snapshot.total ? (root.snapshot.completed || 0) / root.snapshot.total : 0)
              Behavior on width { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
            }
          }

          Flickable {
            id: list
            visible: tasks.implicitHeight > 0
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(tasks.implicitHeight, Math.max(Style.space(120), window.height * 0.42))
            contentHeight: tasks.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ColumnLayout {
              id: tasks
              width: list.width
              spacing: Style.space(10)
              Repeater {
                model: root.snapshot.carry || []
                delegate: RowLayout {
                  required property var modelData
                  Layout.fillWidth: true
                  spacing: Style.space(12)
                  Line { text: "↻"; color: Color.muted; font.pixelSize: Style.font.heading; Layout.preferredWidth: Style.space(18); Layout.alignment: Qt.AlignTop }
                  Line { text: modelData.text; color: Color.muted; font.pixelSize: Style.font.heading; Layout.fillWidth: true; wrapMode: Text.Wrap }
                  Line { text: "from yesterday"; color: Color.muted; font.pixelSize: Style.font.bodySmall; Layout.alignment: Qt.AlignTop }
                }
              }
              Repeater {
                model: root.snapshot.tasks || []
                delegate: RowLayout {
                  id: row
                  required property var modelData
                  readonly property bool passed: modelData.status === "passed"
                  readonly property var change: (root.snapshot.pending || {})[modelData.id] || null
                  Layout.fillWidth: true
                  spacing: Style.space(12)
                  Line {
                    text: row.passed ? "✓" : modelData.main ? "★" : modelData.verdict === "fail" ? "×" : "·"
                    color: row.passed || modelData.main ? root.tone : modelData.verdict === "fail" ? Color.urgent : Color.muted
                    font.pixelSize: Style.font.heading
                    Layout.preferredWidth: Style.space(18); Layout.alignment: Qt.AlignTop
                  }
                  ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Style.space(3)
                    Line { text: modelData.text; color: row.passed ? Color.muted : Color.menu.text; font.pixelSize: Style.font.heading; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    Line { visible: !!modelData.note; text: modelData.note || ""; color: Color.muted; font.pixelSize: Style.font.body; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    Line { visible: !!row.change; text: row.change ? root.pendingText(row.change) : ""; color: root.tone; font.pixelSize: Style.font.body }
                    Line {
                      visible: !!modelData.timer && !row.passed
                      text: !modelData.timer ? "" : modelData.timer.done ? "timer finished · " + modelData.timer.minutes + " minutes" : "timer " + root.clockText(modelData.timer.until)
                      color: root.tone; font.pixelSize: Style.font.body
                    }
                  }
                  Line {
                    visible: text !== ""
                    text: row.passed && modelData.by === "external" ? "external" : (row.passed && modelData.basis === "claim") || (!row.passed && modelData.onWord) ? "on your word" : modelData.main && row.passed ? "main" : ""
                    color: Color.muted; font.pixelSize: Style.font.bodySmall; Layout.alignment: Qt.AlignTop
                  }
                }
              }
            }
          }

          Rectangle { visible: list.visible; Layout.fillWidth: true; height: Math.max(1, Style.space(1)); color: Util.alpha(Color.menu.text, 0.12) }

          ColumnLayout {
            visible: !!root.snapshot.challenge
            Layout.fillWidth: true
            spacing: Style.space(6)
            Line {
              text: root.snapshot.challenge ? root.snapshot.challenge.code : ""
              color: root.tone; font.pixelSize: Style.font.display; font.letterSpacing: Style.space(2)
              Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
            }
            Line {
              color: Color.muted; font.pixelSize: Style.font.body
              text: !root.snapshot.challenge ? "" : root.snapshot.challenge.readyAt === null ? "Type this exactly for 15 minutes of access. It is logged."
                : "Unlocking in " + root.seconds(root.snapshot.challenge.readyAt) + "s"
            }
          }

          ColumnLayout {
            visible: root.lines.length > 0 || !!root.chat.busy
            Layout.fillWidth: true
            spacing: Style.space(8)
            Line {
              visible: root.alarm && root.kind === "denied" && root.quote !== ""
              text: "// " + root.quote
              color: Color.muted; font.pixelSize: Style.font.subtitle; font.italic: true
              Layout.fillWidth: true; wrapMode: Text.Wrap
            }
            Repeater {
              model: root.lines
              delegate: Line {
                required property var modelData
                required property int index
                readonly property bool newest: index === root.lines.length - 1
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: (modelData.role === "user" ? "› " : "") + modelData.text + (modelData.live ? " ▍" : "")
                font.pixelSize: modelData.role === "user" ? Style.font.subtitle : Style.font.heading
                color: modelData.role === "user" ? Color.muted : Color.menu.text
                opacity: newest || modelData.role === "user" ? 1 : 0.45
                lineHeight: 1.25
              }
            }
            Line {
              visible: !!root.chat.busy && !root.chat.streaming
              text: root.spinnerFrames[root.spinnerFrame] + "  " + (root.chat.activity || "thinking")
              color: Color.muted; font.pixelSize: Style.font.subtitle
              Layout.fillWidth: true; elide: Text.ElideRight
            }
          }

          Flow {
            visible: root.choices.length > 0 && !root.chat.busy
            Layout.fillWidth: true
            spacing: Style.space(8)
            Repeater {
              model: root.choices
              delegate: Rectangle {
                required property string modelData
                readonly property bool on: root.picked.indexOf(modelData) >= 0
                width: chip.implicitWidth + Style.space(22); height: chip.implicitHeight + Style.space(12)
                radius: Style.cornerRadius
                color: on ? Util.alpha(root.tone, 0.2) : hover.containsMouse ? Util.alpha(Color.menu.text, 0.08) : "transparent"
                border.width: 1; border.color: on ? root.tone : Util.alpha(Color.menu.text, 0.28)
                Line { id: chip; anchors.centerIn: parent; text: (parent.on ? "✓ " : "") + modelData; color: parent.on ? root.tone : Color.menu.text; font.pixelSize: Style.font.subtitle }
                MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.pick(modelData) }
              }
            }
          }

          RowLayout {
            Layout.fillWidth: true
            spacing: Style.space(12)
            Line { text: "›"; color: root.tone; font.pixelSize: Style.font.heading; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignTop }
            TextInput {
              id: prompt
              Layout.fillWidth: true
              color: Color.menu.text
              font.family: Style.font.family
              font.pixelSize: Style.font.heading
              wrapMode: TextInput.Wrap
              selectionColor: Style.selectionFill
              selectedTextColor: Color.menu.text
              maximumLength: 4000
              focus: true
              cursorDelegate: Rectangle { width: Style.space(8); color: root.tone; opacity: prompt.activeFocus ? 0.9 : 0 }
              property string ghost: root.picked.length ? "add your own, or press enter" : root.chat.suggestion || (!root.snapshot.agent ? "type a task" : !root.snapshot.setup ? "" : !root.snapshot.started ? "say what today holds" : root.snapshot.locked ? "say what's done" : "")
              function submit() {
                var words = root.picked.concat(text.trim() ? [text.trim()] : []).join(", ") || root.chat.suggestion || ""
                if (!words) return
                root.service.say(words)
                text = ""
              }
              Keys.onPressed: function(event) {
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { submit(); event.accepted = true }
                else if (event.key === Qt.Key_Escape) { root.service.close(); event.accepted = true }
                else if (event.key === Qt.Key_Tab) { if (!text && root.chat.suggestion) text = root.chat.suggestion; event.accepted = true }
                else if (event.key === Qt.Key_Up && !text) {
                  var said = (root.chat.messages || []).filter(function(m) { return m.role === "user" })
                  if (said.length) text = said[said.length - 1].text
                  event.accepted = true
                }
              }
              Line {
                visible: !prompt.text
                x: Style.space(14)
                text: prompt.ghost
                color: Color.muted; font.pixelSize: Style.font.heading
                opacity: root.chat.suggestion ? 0.9 : 0.55
              }
            }
          }

          RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: -Style.space(4)
            Line {
              Layout.fillWidth: true; elide: Text.ElideRight
              text: root.service && root.service.error ? root.service.error : root.snapshot.blockingError ? root.snapshot.blockingError : root.blockedSummary
              color: (root.service && root.service.error) || root.snapshot.blockingError ? Color.urgent : Color.muted
              font.pixelSize: Style.font.bodySmall; opacity: 0.8
            }
            Line {
              text: (root.choices.length ? "click to pick · " : "") + (root.chat.suggestion && !prompt.text && !root.picked.length ? "enter accepts · " : "enter sends · ") + "esc closes"
              color: Color.muted; font.pixelSize: Style.font.bodySmall; opacity: 0.8
            }
          }
        }
      }
    }
  }

  component Line: Text {
    color: Color.menu.text
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    textFormat: Text.PlainText
  }
}
