import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui as Ui

// The Focus dropdown: hero, mode switch, today's list, the conversation and one prompt.
// Built from the same parts as Omarchy's own panels so it reads as one of them.
Item {
  id: root
  property var service: null
  // True while the dropdown is showing; animations only run then.
  property bool active: false
  property alias prompt: prompt
  implicitHeight: body.implicitHeight

  readonly property var snapshot: service ? service.state : ({tasks: [], carry: [], settings: {}, pending: {}, overrides: [], setup: true})
  readonly property var chat: service ? service.chat : ({messages: [], streaming: "", activity: "", suggestion: "", busy: false})
  readonly property real clock: service ? service.clock : 0
  readonly property color foreground: Color.popups.text
  readonly property color dim: Qt.darker(foreground, 1.4)
  readonly property color track: Style.selectedFillFor(foreground, Color.accent)
  readonly property var spinnerFrames: ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
  property int spinnerFrame: 0
  // The reply being written counts as the newest message.
  readonly property var lines: {
    var shown = (chat.messages || []).slice(-3)
    if (chat.streaming) shown = shown.slice(-2).concat([{role: "agent", text: chat.streaming, live: true}])
    return shown
  }
  readonly property string strictness: (service && service.skinPreview) || snapshot.settings.strictness || "standard"
  readonly property var levels: ["honor", "standard", "hard", "lockdown"]
  // Lockdown runs in the theme's red; hard and lockdown get scanlines.
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
  readonly property real progress: snapshot.total ? (snapshot.completed || 0) / snapshot.total : 0
  readonly property string status: {
    if (!snapshot.setup) return "setting up"
    if (snapshot.recovered) return "recovery · blocking off"
    if (!snapshot.started) return readyToStart ? "ready to lock in" : "not started"
    if (snapshot.locked) return "locked"
    if (snapshot.fullUnlock) return "unlocked"
    return "unlocked for " + Math.max(1, Math.ceil(((snapshot.until || 0) - clock) / 60)) + "m"
  }
  readonly property string headline: {
    if (!snapshot.total) return "Nothing on the list yet"
    var left = snapshot.total - (snapshot.completed || 0)
    return left === 0 ? "All " + snapshot.total + " done" : (snapshot.completed || 0) + " of " + snapshot.total + " done"
  }
  readonly property string blockedText: {
    var all = (snapshot.settings.sites || []).concat(snapshot.settings.apps || [])
    return all.length ? all.join(" · ") : "Nothing blocked yet"
  }
  function clockText(until) {
    var left = Math.max(0, Math.ceil(until - clock))
    return Math.floor(left / 60) + ":" + ("0" + (left % 60)).slice(-2)
  }
  function seconds(until) { return Math.max(0, Math.ceil(until - clock)) }
  function pendingText(change) {
    var verb = change.action === "delete" ? "Drops" : change.action === "main" ? "Becomes main" : "Rewords"
    return verb + " in " + seconds(change.readyAt) + "s · say cancel to stop it"
  }
  // Something only you can approve: a folder, a link, a screenshot. The agent can ask; it cannot grant.
  readonly property string consentKey: JSON.stringify(chat.consent || null)
  readonly property var consent: JSON.parse(consentKey)
  readonly property var backend: snapshot.backend || ({label: "", ok: true, error: ""})
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

  Timer { interval: 80; running: root.active && !!root.chat.busy; repeat: true; onTriggered: root.spinnerFrame = (root.spinnerFrame + 1) % root.spinnerFrames.length }

  Canvas {
    // Scanlines, for the stricter modes.
    anchors.fill: parent
    visible: root.harsh
    opacity: 0.06
    onPaint: {
      var ctx = getContext("2d")
      ctx.clearRect(0, 0, width, height)
      ctx.fillStyle = root.tone
      for (var y = 0; y < height; y += 3) ctx.fillRect(0, y, width, 1)
    }
    onVisibleChanged: requestPaint()
    onHeightChanged: requestPaint()
  }

  Flickable {
    id: flick
    anchors.fill: parent
    contentHeight: body.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    // The prompt is at the bottom; keep it in view when the list outgrows the panel.
    onContentHeightChanged: contentY = Math.max(0, contentHeight - height)
    onHeightChanged: contentY = Math.max(0, contentHeight - height)

    ColumnLayout {
      id: body
      width: flick.width
      spacing: Style.space(12)

      Ui.PanelHero {
        Layout.fillWidth: true
        title: "Focus"
        meta: (root.snapshot.setup ? root.rank + " · " : "") + root.status
        foreground: root.foreground
        iconComponent: Component {
          // The same dot as the bar: solid while locked, hollow once you are through.
          Item {
            implicitWidth: Style.font.display; implicitHeight: Style.font.display
            Rectangle {
              anchors.centerIn: parent
              width: Style.space(16); height: width; radius: width / 2
              color: root.snapshot.locked && root.snapshot.setup ? (root.strictness === "lockdown" ? root.tone : root.foreground) : "transparent"
              border.width: Math.max(2, Style.space(2)); border.color: root.strictness === "lockdown" ? root.tone : root.foreground
              Behavior on color { ColorAnimation { duration: 200 } }
            }
          }
        }
      }

      // How strict Focus is today. It goes up any time; down only before the day starts.
      RowLayout {
        id: modes
        visible: !!root.snapshot.setup
        Layout.fillWidth: true
        spacing: Style.spacing.md
        Repeater {
          model: root.levels
          delegate: Ui.Button {
            required property string modelData
            required property int index
            readonly property int current: root.levels.indexOf(root.strictness)
            readonly property bool reachable: !root.snapshot.started || index >= current
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            text: modelData.charAt(0).toUpperCase() + modelData.slice(1)
            selected: index === current
            bordered: true
            foreground: root.foreground
            accent: root.tone
            fontSize: Style.font.bodySmall
            verticalPadding: Style.spacing.controlPaddingY
            horizontalPadding: Style.spacing.sm
            opacity: reachable ? 1 : 0.4
            tooltipText: reachable ? "" : "Lower it tomorrow, before the day starts"
            onClicked: if (index !== current) root.service.send({op: "settings", values: {strictness: modelData}})
          }
        }
      }

      Ui.PanelSeparator { Layout.fillWidth: true; foreground: root.foreground }

      Ui.PanelSectionHeader { text: "TODAY"; foreground: root.foreground }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(6)
        RowLayout {
          Layout.fillWidth: true
          Line { text: root.headline; Layout.fillWidth: true; elide: Text.ElideRight }
          Line { text: root.snapshot.total ? Math.round(root.progress * 100) + "%" : "—"; font.pixelSize: Style.font.caption }
        }
        Item {
          Layout.fillWidth: true
          implicitHeight: Math.max(Style.space(4), Math.round(Style.spacing.controlHeight * 0.14))
          Rectangle { id: meterTrack; anchors.fill: parent; radius: height / 2; color: root.track }
          Rectangle {
            height: meterTrack.height; radius: meterTrack.radius
            width: meterTrack.width * root.progress
            color: root.strictness === "lockdown" ? root.tone : root.foreground
            Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
          }
        }
        Line {
          color: root.dim; font.pixelSize: Style.font.caption
          text: (root.snapshot.settings.mode === "earn" ? "Each pass earns " + (root.snapshot.settings.minutes || 15) + " minutes" : "Everything unlocks when all pass")
                + " · new day at " + (root.snapshot.settings.reset || "04:00")
        }
      }

      ColumnLayout {
        visible: (root.snapshot.carry || []).length + (root.snapshot.tasks || []).length > 0
        Layout.fillWidth: true
        Layout.topMargin: Style.space(2)
        spacing: Style.space(10)
        Repeater {
          model: root.snapshot.carry || []
          delegate: RowLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: Style.space(10)
            Line { text: "↻"; color: root.dim; Layout.preferredWidth: Style.space(14); Layout.alignment: Qt.AlignTop }
            Line { text: modelData.text; color: root.dim; Layout.fillWidth: true; wrapMode: Text.Wrap }
            Line { text: "yesterday"; color: root.dim; font.pixelSize: Style.font.caption; Layout.alignment: Qt.AlignTop }
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
            spacing: Style.space(10)
            Line {
              text: row.passed ? "✓" : modelData.main ? "★" : modelData.verdict === "fail" ? "×" : "·"
              color: row.passed || modelData.main ? root.tone : modelData.verdict === "fail" ? Color.urgent : root.dim
              Layout.preferredWidth: Style.space(14); Layout.alignment: Qt.AlignTop
            }
            ColumnLayout {
              Layout.fillWidth: true
              spacing: Style.space(2)
              Line {
                text: modelData.text; Layout.fillWidth: true; wrapMode: Text.Wrap
                color: row.fresh ? (row.passed ? root.tone : Color.urgent) : row.passed ? root.dim : root.foreground
                Behavior on color { ColorAnimation { duration: 900 } }
              }
              Line { visible: !!modelData.note; text: modelData.note || ""; color: root.dim; font.pixelSize: Style.font.caption; Layout.fillWidth: true; wrapMode: Text.Wrap }
              Line { visible: !!row.change; text: row.change ? root.pendingText(row.change) : ""; color: root.tone; font.pixelSize: Style.font.caption }
              Line {
                visible: !!modelData.timer && !row.passed
                text: !modelData.timer ? "" : modelData.timer.done ? "Timer finished · " + modelData.timer.minutes + " minutes" : "Timer " + root.clockText(modelData.timer.until)
                color: root.tone; font.pixelSize: Style.font.caption
              }
            }
            Line {
              visible: text !== ""
              text: row.passed && modelData.by === "external" ? "external" : (row.passed && modelData.basis === "claim") || (!row.passed && modelData.onWord) ? "on your word" : modelData.main ? "main" : ""
              color: root.dim; font.pixelSize: Style.font.caption; Layout.alignment: Qt.AlignTop
            }
          }
        }
      }

      ColumnLayout {
        visible: !!root.snapshot.challenge
        Layout.fillWidth: true
        spacing: Style.space(6)
        Ui.PanelSeparator { Layout.fillWidth: true; foreground: root.foreground }
        Ui.PanelSectionHeader { text: "EMERGENCY UNLOCK"; foreground: root.foreground }
        Line {
          text: root.snapshot.challenge ? root.snapshot.challenge.code : ""
          color: root.tone; font.pixelSize: Style.font.heading; font.letterSpacing: Style.space(2)
          Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
        }
        Line {
          color: root.dim; font.pixelSize: Style.font.caption
          text: !root.snapshot.challenge ? "" : root.snapshot.challenge.readyAt === null ? "Type this exactly for 15 minutes of access. It is logged."
            : "Unlocking in " + root.seconds(root.snapshot.challenge.readyAt) + "s"
        }
      }

      Ui.PanelSeparator { Layout.fillWidth: true; foreground: root.foreground }

      ColumnLayout {
        visible: root.lines.length > 0 || !!root.chat.busy
        Layout.fillWidth: true
        spacing: Style.space(6)
        Repeater {
          model: root.lines
          delegate: Line {
            required property var modelData
            required property int index
            readonly property bool newest: index === root.lines.length - 1
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: (modelData.role === "user" ? "› " : "") + modelData.text + (modelData.live ? " ▍" : "")
            font.pixelSize: modelData.role === "user" || !newest ? Style.font.caption : Style.font.body
            color: newest && modelData.role !== "user" ? root.foreground : root.dim
            lineHeight: 1.15
            // Older lines are context, not content: two lines at most, so the panel stays short.
            maximumLineCount: newest ? 12 : 2
            elide: Text.ElideRight
          }
        }
        Line {
          visible: !!root.chat.busy && !root.chat.streaming
          text: root.spinnerFrames[root.spinnerFrame] + "  " + (root.chat.activity || "thinking")
          color: root.dim; font.pixelSize: Style.font.caption
          Layout.fillWidth: true; elide: Text.ElideRight
        }
      }

      Ui.BorderSurface {
        visible: !!root.consent
        Layout.fillWidth: true
        implicitHeight: asking.implicitHeight + Style.space(20)
        radius: Style.cornerRadius
        color: Util.alpha(root.tone, 0.08)
        borderSpec: Border.flat(Util.alpha(root.tone, 0.45), 1)
        ColumnLayout {
          id: asking
          anchors { left: parent.left; right: parent.right; top: parent.top; margins: Style.space(10) }
          spacing: Style.space(8)
          Line { Layout.fillWidth: true; wrapMode: Text.Wrap; text: root.consent ? root.consent.text : "" }
          Image {
            // What was captured, shown before anything is sent.
            visible: !!root.consent && !!root.consent.preview
            source: root.consent && root.consent.preview ? "file://" + root.consent.preview : ""
            cache: false; asynchronous: true
            fillMode: Image.PreserveAspectFit
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? width * 0.56 : 0
          }
          Line {
            Layout.fillWidth: true; wrapMode: Text.Wrap
            color: root.dim; font.pixelSize: Style.font.caption
            text: !root.consent ? "" : root.consent.kind === "screen" ? "Nothing is sent yet." : "It will be read by " + root.consent.goes + "."
          }
          RowLayout {
            spacing: Style.spacing.md
            Ui.Button {
              text: root.consent && root.consent.kind === "share" ? "Send it" : root.consent && root.consent.kind === "screen" ? "Capture" : "Allow"
              selected: true; bordered: true; foreground: root.foreground; accent: root.tone; fontSize: Style.font.bodySmall
              onClicked: root.service.send({op: "consent", answer: true})
            }
            Ui.Button {
              text: root.consent && root.consent.kind === "share" ? "Discard" : "No"
              bordered: true; foreground: root.foreground; accent: root.tone; fontSize: Style.font.bodySmall
              onClicked: root.service.send({op: "consent", answer: false})
            }
            Line { text: "or type yes / no"; color: root.dim; font.pixelSize: Style.font.caption }
          }
        }
      }

      Flow {
        visible: root.choices.length > 0 && !root.chat.busy
        Layout.fillWidth: true
        spacing: Style.spacing.md
        Repeater {
          model: root.choices
          delegate: Ui.Button {
            required property string modelData
            text: modelData
            selected: root.picked.indexOf(modelData) >= 0
            bordered: true
            foreground: root.foreground
            accent: root.tone
            fontSize: Style.font.bodySmall
            verticalPadding: Style.spacing.controlPaddingY
            onClicked: root.pick(modelData)
          }
        }
      }

      // The prompt, drawn as one of the kit's input fields.
      Ui.BorderSurface {
        id: field
        Layout.fillWidth: true
        implicitHeight: prompt.implicitHeight + Style.spacing.inputPaddingY * 2 + Style.space(4)
        radius: Style.cornerRadius
        color: Style.controlFill(prompt.activeFocus, false, root.foreground, root.tone)
        borderSpec: Border.controlSpec(prompt.activeFocus ? "focus" : "normal", root.foreground, root.tone)
        Line {
          id: chevron
          anchors { left: parent.left; leftMargin: Style.spacing.controlPaddingX; top: parent.top; topMargin: Style.spacing.inputPaddingY + Style.space(2) }
          text: "›"; color: root.tone; font.weight: Font.Bold
        }
        TextInput {
          id: prompt
          anchors { left: chevron.right; leftMargin: Style.space(8); right: parent.right; rightMargin: Style.spacing.controlPaddingX; top: parent.top; topMargin: Style.spacing.inputPaddingY + Style.space(2) }
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          wrapMode: TextInput.Wrap
          selectionColor: Style.selectionFill
          selectedTextColor: root.foreground
          maximumLength: 4000
          focus: true
          cursorDelegate: Rectangle { width: Style.space(6); color: root.tone; opacity: prompt.activeFocus ? 0.9 : 0 }
          property string ghost: root.picked.length ? "Add your own, or press Enter" : root.readyToStart ? "Press Enter to lock in" : root.chat.suggestion || (!root.snapshot.agent ? "Type a task" : !root.snapshot.setup ? "" : !root.snapshot.started ? "Say what today holds" : root.snapshot.locked ? "Say what's done" : "Say anything")
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
            else if (event.key === Qt.Key_V && (event.modifiers & Qt.ControlModifier)) {
              // A picture on the clipboard becomes evidence you confirm before it is sent; text pastes as usual.
              root.service.send({op: "paste"})
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
            x: Style.space(10)
            text: prompt.ghost
            color: root.readyToStart ? root.tone : root.dim
          }
        }
      }

      Line {
        visible: !!(root.service && root.service.error) || !!root.snapshot.blockingError
        Layout.fillWidth: true; wrapMode: Text.Wrap
        text: root.service && root.service.error ? root.service.error : root.snapshot.blockingError || ""
        color: Color.urgent; font.pixelSize: Style.font.caption
      }

      Ui.PanelSeparator { Layout.fillWidth: true; foreground: root.foreground }

      Ui.PanelSectionHeader { text: "BLOCKED"; foreground: root.foreground }
      Line {
        Layout.fillWidth: true
        text: root.blockedText
        color: root.dim; font.pixelSize: Style.font.caption
        wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
      }
      Ui.PanelSectionHeader { text: "AGENT"; foreground: root.foreground }
      Line {
        Layout.fillWidth: true; wrapMode: Text.Wrap
        text: root.backend.ok === false ? root.backend.error : (root.backend.label || "") + (root.backend.auto ? " · the agent Omarchy is set to" : "")
        color: root.backend.ok === false ? Color.urgent : root.dim; font.pixelSize: Style.font.caption
      }
      Line {
        visible: !!root.backend.note
        Layout.fillWidth: true; wrapMode: Text.Wrap
        text: root.backend.note || ""
        color: root.dim; font.pixelSize: Style.font.caption
      }
      // Cost is the model: one click for the cheap one. Other agents list theirs with /models.
      RowLayout {
        visible: root.backend.provider === "claude"
        Layout.fillWidth: true
        spacing: Style.spacing.md
        Repeater {
          model: [{id: "haiku", label: "Low cost"}, {id: "sonnet", label: "Balanced"}, {id: "opus", label: "Best"}]
          delegate: Ui.Button {
            required property var modelData
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            text: modelData.label
            tooltipText: "Claude " + modelData.id
            selected: (root.backend.model || "sonnet") === modelData.id
            bordered: true
            foreground: root.foreground
            accent: root.tone
            fontSize: Style.font.caption
            verticalPadding: Style.spacing.xs
            onClicked: root.service.send({op: "settings", values: {model: modelData.id}})
          }
        }
      }
      Line {
        visible: root.backend.provider !== "claude" && root.backend.ok !== false
        text: "/models lists what it can run · /model NAME picks one"
        color: root.dim; font.pixelSize: Style.font.caption; opacity: 0.7
      }
      Line {
        Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
        text: (root.snapshot.settings.roots || []).length ? "May read " + root.snapshot.settings.roots.join(" · ") : "No folder approved for it to read yet"
        color: root.dim; font.pixelSize: Style.font.caption
      }
      Line {
        Layout.fillWidth: true
        Layout.topMargin: Style.space(2)
        text: (root.readyToStart && !prompt.text ? "Enter locks in" : root.chat.suggestion && !prompt.text && !root.picked.length ? "Enter accepts" : "Enter sends") + " · Ctrl+V pastes a screenshot · /help · Esc closes"
        color: root.dim; font.pixelSize: Style.font.caption; opacity: 0.7
      }
    }
  }

  component Line: Text {
    color: root.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    textFormat: Text.PlainText
  }
}
