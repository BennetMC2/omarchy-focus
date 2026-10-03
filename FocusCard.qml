import QtQuick
import QtQuick.Layouts
import qs.Commons

// Today's list, what the agent last said, and one prompt. Lives in the dropdown under the bar icon.
Item {
  id: root
  property var service: null
  // True while the dropdown is showing; animations and the clock only run then.
  property bool active: false
  property alias prompt: prompt
  implicitHeight: body.implicitHeight
  readonly property var snapshot: service ? service.state : ({tasks: [], carry: [], settings: {}, pending: {}, overrides: [], setup: true})
  readonly property var chat: service ? service.chat : ({messages: [], streaming: "", activity: "", suggestion: "", busy: false})
  readonly property real clock: service ? service.clock : 0
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
  readonly property var levels: ["honor", "standard", "hard", "lockdown"]
  readonly property color tone: strictness === "lockdown" ? Color.urgent : Color.accent
  readonly property bool harsh: strictness === "hard" || strictness === "lockdown"
  readonly property string rank: {
    var days = snapshot.streak || 0
    return days >= 30 ? "ghost" : days >= 14 ? "veteran" : days >= 7 ? "specialist" : days >= 3 ? "operator" : days >= 1 ? "initiate" : "drifter"
  }
  readonly property var mainTask: (snapshot.tasks || []).filter(function(t) { return t.main })[0] || null
  // The list is settled and the day has not begun: one Enter starts it.
  readonly property bool readyToStart: !!snapshot.setup && !snapshot.started && (snapshot.tasks || []).length > 0 && !!mainTask
    && (snapshot.tasks || []).filter(function(t) { return t.main }).length === 1 && !(snapshot.carry || []).length && !chat.busy
  function clockText(until) {
    var left = Math.max(0, Math.ceil(until - clock))
    return Math.floor(left / 60) + ":" + ("0" + (left % 60)).slice(-2)
  }
  readonly property string status: {
    if (!snapshot.setup) return "setting up"
    if (snapshot.recovered) return "recovery · blocking off"
    var count = snapshot.total ? (snapshot.completed || 0) + " of " + snapshot.total + " · " : ""
    if (!snapshot.started) return readyToStart ? "ready" : count + "not started"
    if (snapshot.locked) return count + "locked"
    if (snapshot.fullUnlock) return count + "unlocked"
    return count + "unlocked " + Math.max(1, Math.ceil(((snapshot.until || 0) - clock) / 60)) + "m"
  }
  readonly property string blockedSummary: {
    var all = (snapshot.settings.sites || []).concat(snapshot.settings.apps || [])
    if (!all.length) return "nothing blocked yet"
    return all.slice(0, 3).join(" · ") + (all.length > 3 ? " +" + (all.length - 3) : "")
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

  Timer { interval: 80; running: root.active && !!root.chat.busy; repeat: true; onTriggered: root.spinnerFrame = (root.spinnerFrame + 1) % root.spinnerFrames.length }

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
    anchors { left: parent.left; right: parent.right; top: parent.top }
    spacing: Style.space(10)

    RowLayout {
      Layout.fillWidth: true
      Line { text: "FOCUS"; color: root.strictness === "lockdown" ? root.tone : Color.menu.text; font.pixelSize: Style.font.subtitle; font.weight: Font.Bold; font.letterSpacing: Style.space(4); Layout.fillWidth: true }
      Line { text: "[ " + (root.snapshot.setup ? root.rank.toUpperCase() + " · " : "") + root.status.toUpperCase() + " ]"; color: root.snapshot.locked && root.snapshot.setup ? root.tone : Color.muted; font.pixelSize: Style.font.caption; font.letterSpacing: Style.space(1) }
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

    // How strict Focus is today, as a level you can click. It goes up any time; down only before the day starts.
    RowLayout {
      visible: !!root.snapshot.setup
      Layout.fillWidth: true
      Layout.topMargin: -Style.space(6)
      spacing: Style.space(6)
      Repeater {
        model: root.levels
        delegate: Item {
          id: step
          required property string modelData
          required property int index
          readonly property int current: root.levels.indexOf(root.strictness)
          readonly property bool reachable: !root.snapshot.started || index >= current
          Layout.fillWidth: true
          implicitHeight: stepLabel.implicitHeight + Style.space(12)
          Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: Math.max(2, Style.space(3))
            color: step.index <= step.current ? root.tone : Util.alpha(Color.menu.text, stepArea.containsMouse && step.reachable ? 0.35 : 0.12)
            Behavior on color { ColorAnimation { duration: 160 } }
          }
          Line {
            id: stepLabel
            anchors { left: parent.left; bottom: parent.bottom }
            text: step.modelData.toUpperCase()
            color: step.index === step.current ? root.tone : stepArea.containsMouse && step.reachable ? Color.menu.text : Color.muted
            opacity: step.reachable ? 1 : 0.35
            font.pixelSize: Style.font.caption; font.letterSpacing: Style.space(2); font.weight: step.index === step.current ? Font.Bold : Font.Normal
          }
          MouseArea {
            id: stepArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: step.reachable && step.index !== step.current ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: if (step.index !== step.current) root.service.send({op: "settings", values: {strictness: step.modelData}})
          }
        }
      }
    }

    Flickable {
      id: list
      visible: tasks.implicitHeight > 0
      Layout.fillWidth: true
      Layout.preferredHeight: Math.min(tasks.implicitHeight, Style.space(300))
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
            Line { text: "↻"; color: Color.muted; font.pixelSize: Style.font.body; Layout.preferredWidth: Style.space(14); Layout.alignment: Qt.AlignTop }
            Line { text: modelData.text; color: Color.muted; font.pixelSize: Style.font.body; Layout.fillWidth: true; wrapMode: Text.Wrap }
            Line { text: "from yesterday"; color: Color.muted; font.pixelSize: Style.font.caption; Layout.alignment: Qt.AlignTop }
          }
        }
        Repeater {
          model: root.snapshot.tasks || []
          delegate: RowLayout {
            id: row
            required property var modelData
            readonly property bool passed: modelData.status === "passed"
            // A verdict that just landed glows for a few seconds.
            readonly property real verdictAt: (modelData.verdicts || []).length ? modelData.verdicts[modelData.verdicts.length - 1].at : 0
            readonly property bool fresh: verdictAt > 0 && root.clock - verdictAt < 4
            readonly property var change: (root.snapshot.pending || {})[modelData.id] || null
            Layout.fillWidth: true
            spacing: Style.space(12)
            Line {
              text: row.passed ? "✓" : modelData.main ? "★" : modelData.verdict === "fail" ? "×" : "·"
              color: row.passed || modelData.main ? root.tone : modelData.verdict === "fail" ? Color.urgent : Color.muted
              font.pixelSize: Style.font.body
              Layout.preferredWidth: Style.space(14); Layout.alignment: Qt.AlignTop
            }
            ColumnLayout {
              Layout.fillWidth: true
              spacing: Style.space(3)
              Line {
                text: modelData.text; font.pixelSize: Style.font.body; Layout.fillWidth: true; wrapMode: Text.Wrap
                color: row.fresh ? (row.passed ? root.tone : Color.urgent) : row.passed ? Color.muted : Color.menu.text
                Behavior on color { ColorAnimation { duration: 900 } }
              }
              Line { visible: !!modelData.note; text: modelData.note || ""; color: Color.muted; font.pixelSize: Style.font.bodySmall; Layout.fillWidth: true; wrapMode: Text.Wrap }
              Line { visible: !!row.change; text: row.change ? root.pendingText(row.change) : ""; color: root.tone; font.pixelSize: Style.font.bodySmall }
              Line {
                visible: !!modelData.timer && !row.passed
                text: !modelData.timer ? "" : modelData.timer.done ? "timer finished · " + modelData.timer.minutes + " minutes" : "timer " + root.clockText(modelData.timer.until)
                color: root.tone; font.pixelSize: Style.font.bodySmall
              }
            }
            Line {
              visible: text !== ""
              text: row.passed && modelData.by === "external" ? "external" : (row.passed && modelData.basis === "claim") || (!row.passed && modelData.onWord) ? "on your word" : modelData.main && row.passed ? "main" : ""
              color: Color.muted; font.pixelSize: Style.font.caption; Layout.alignment: Qt.AlignTop
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
        color: root.tone; font.pixelSize: Style.font.heading; font.letterSpacing: Style.space(2)
        Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
      }
      Line {
        color: Color.muted; font.pixelSize: Style.font.bodySmall
        text: !root.snapshot.challenge ? "" : root.snapshot.challenge.readyAt === null ? "Type this exactly for 15 minutes of access. It is logged."
          : "Unlocking in " + root.seconds(root.snapshot.challenge.readyAt) + "s"
      }
    }

    ColumnLayout {
      visible: root.lines.length > 0 || !!root.chat.busy
      Layout.fillWidth: true
      spacing: Style.space(8)
      Repeater {
        model: root.lines
        delegate: Line {
          required property var modelData
          required property int index
          readonly property bool newest: index === root.lines.length - 1
          Layout.fillWidth: true
          wrapMode: Text.Wrap
          text: (modelData.role === "user" ? "› " : "") + modelData.text + (modelData.live ? " ▍" : "")
          font.pixelSize: modelData.role === "user" ? Style.font.subtitle : Style.font.body
          color: modelData.role === "user" ? Color.muted : Color.menu.text
          opacity: newest || modelData.role === "user" ? 1 : 0.45
          lineHeight: 1.2
        }
      }
      Line {
        visible: !!root.chat.busy && !root.chat.streaming
        text: root.spinnerFrames[root.spinnerFrame] + "  " + (root.chat.activity || "thinking")
        color: Color.muted; font.pixelSize: Style.font.bodySmall
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
          Line { id: chip; anchors.centerIn: parent; text: (parent.on ? "✓ " : "") + modelData; color: parent.on ? root.tone : Color.menu.text; font.pixelSize: Style.font.bodySmall }
          MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.pick(modelData) }
        }
      }
    }

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(12)
      Line { text: "›"; color: root.tone; font.pixelSize: Style.font.body; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignTop }
      TextInput {
        id: prompt
        Layout.fillWidth: true
        color: Color.menu.text
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        wrapMode: TextInput.Wrap
        selectionColor: Style.selectionFill
        selectedTextColor: Color.menu.text
        maximumLength: 4000
        focus: true
        cursorDelegate: Rectangle { width: Style.space(8); color: root.tone; opacity: prompt.activeFocus ? 0.9 : 0 }
        property string ghost: root.picked.length ? "add your own, or press enter" : root.readyToStart ? "press enter to lock in" : root.chat.suggestion || (!root.snapshot.agent ? "type a task" : !root.snapshot.setup ? "" : !root.snapshot.started ? "say what today holds" : root.snapshot.locked ? "say what's done" : "")
        function submit() {
          if (!text.trim() && !root.picked.length && root.readyToStart) { root.service.send({op: "start"}); return }
          var words = root.picked.concat(text.trim() ? [text.trim()] : []).join(", ") || root.chat.suggestion || ""
          if (!words) return
          root.service.say(words)
          text = ""
        }
        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { submit(); event.accepted = true }
          else if (event.key === Qt.Key_Escape) { root.service.close(); event.accepted = true }
          else if ((event.key === Qt.Key_Right || event.key === Qt.Key_Left) && (event.modifiers & Qt.ControlModifier) && root.snapshot.setup) {
            var next = root.levels[root.levels.indexOf(root.strictness) + (event.key === Qt.Key_Right ? 1 : -1)]
            if (next) root.service.send({op: "settings", values: {strictness: next}})
            event.accepted = true
          }
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
          color: root.readyToStart ? root.tone : Color.muted; font.pixelSize: Style.font.body
          opacity: root.readyToStart || root.chat.suggestion ? 0.9 : 0.55
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
        font.pixelSize: Style.font.caption; opacity: 0.8
      }
      Line {
        text: (root.choices.length ? "click to pick · " : "") + (root.readyToStart && !prompt.text ? "enter locks in · " : root.chat.suggestion && !prompt.text && !root.picked.length ? "enter accepts · " : "enter sends · ") + "esc closes"
        color: Color.muted; font.pixelSize: Style.font.caption; opacity: 0.8
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
