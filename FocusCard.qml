import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui as Ui

Item {
  id: root
  property var service: null
  property bool active: false
  property alias prompt: prompt
  property string page: "today"
  property bool adding: false
  property bool showDone: false
  property string editing: ""
  property var picked: []
  readonly property string choicesKey: JSON.stringify(chat.choices || null)
  onChoicesKeyChanged: picked = []
  property string requestId: ""
  property string submittedText: ""
  property bool sending: false
  property string inputError: ""
  implicitHeight: Style.space(520)

  readonly property var snapshot: service ? service.state : ({tasks: [], carry: [], settings: {}, pending: {}})
  readonly property var chat: service ? service.chat : ({messages: [], busy: false})
  readonly property var backend: snapshot.backend || ({})
  readonly property var release: snapshot.update || ({})
  readonly property color foreground: Color.popups.text
  readonly property color dim: Util.alpha(foreground, 0.68)
  readonly property color tone: snapshot.settings.strictness === "lockdown" ? Color.urgent : Color.accent
  readonly property var tasks: snapshot.tasks || []
  readonly property var openTasks: tasks.filter(function(t) { return t.status !== "passed" })
  readonly property var doneTasks: tasks.filter(function(t) { return t.status === "passed" })
  readonly property var visibleTasks: openTasks.concat(showDone ? doneTasks : [])
  readonly property var mainTask: tasks.filter(function(t) { return t.main })[0] || null
  readonly property bool readyToStart: !!snapshot.setup && !snapshot.started && !!mainTask && !(snapshot.carry || []).length && !chat.busy && !sending
  readonly property var latest: {
    if (chat.streaming) return ({text: chat.streaming, role: "agent"})
    var replies = (chat.messages || []).filter(function(m) { return m.role !== "user" })
    return replies.length ? replies[replies.length - 1] : ({text: snapshot.started ? "Tell me what's done." : "What do you want to get done today?"})
  }
  readonly property string status: snapshot.recovered ? "Recovery · blocking off" : !snapshot.setup ? "Setup" : !snapshot.started ? "Planning today" : snapshot.locked ? "Distractions blocked" : "Unlocked"
  readonly property var levels: ["honor", "standard", "hard", "lockdown"]

  function showConversation() {
    page = "today"
    Qt.callLater(function() {
      scroll.contentY = Math.max(0, scroll.contentHeight - scroll.height)
    })
  }

  function submit() {
    if (sending || !service) return
    var words = picked.concat(prompt.text.trim() ? [prompt.text.trim()] : []).join(", ") || (!adding ? chat.suggestion || "" : "")
    if (!words) return
    if (!adding) showConversation()
    if (words !== submittedText) requestId = ""
    if (!requestId) requestId = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2)
    submittedText = words
    var command = adding ? {op: "capture", text: words} : {op: "say", text: words}
    command.requestId = requestId
    inputError = ""
    sending = true
    if (!service.send(command)) { sending = false; inputError = "Disconnected. Your text is kept. Try again when Bouncer reconnects."; return }
    if (sending) ackTimeout.restart()
  }
  Connections {
    target: root.service
    ignoreUnknownSignals: true
    function onSubmissionFinished(id, ok, message) {
      if (id !== root.requestId) return
      ackTimeout.stop()
      root.sending = false
      if (ok) {
        prompt.text = ""
        root.picked = []
        root.requestId = ""
        root.submittedText = ""
      } else root.inputError = message
    }
  }
  Timer { id: ackTimeout; interval: 10000; onTriggered: { root.sending = false; root.inputError = root.adding ? "No confirmation yet. Your text is kept; retry is safe." : "No confirmation yet. Check History before sending again." } }

  ColumnLayout {
    anchors.fill: parent
    spacing: Style.space(12)
    RowLayout {
      Layout.fillWidth: true
      ColumnLayout {
        Layout.fillWidth: true; spacing: Style.space(4)
        Label { text: "Bouncer"; font.pixelSize: Style.font.heading; font.bold: true }
        Label { text: root.status; color: root.dim; font.pixelSize: Style.font.caption }
      }
      Item { Layout.fillWidth: true }
      Action { text: root.page === "settings" ? "Back" : "Settings"; onClicked: root.page = root.page === "settings" ? "today" : "settings" }
    }
    Ui.PanelSeparator { Layout.fillWidth: true; foreground: root.foreground }

    Flickable {
      id: scroll
      Layout.fillWidth: true
      Layout.fillHeight: true
      clip: true
      contentHeight: content.implicitHeight
      Rectangle {
        visible: scroll.contentHeight > scroll.height
        width: 2; height: Math.max(20, scroll.height * scroll.height / scroll.contentHeight)
        x: scroll.width - width
        y: scroll.contentY + (scroll.height - height) * scroll.contentY / Math.max(1, scroll.contentHeight - scroll.height)
        color: Util.alpha(root.foreground, 0.3)
        z: 5
      }
      boundsBehavior: Flickable.StopAtBounds
      ColumnLayout {
        id: content
        width: scroll.width
        spacing: Style.space(14)
        ColumnLayout {
          visible: root.page === "today"
          Layout.fillWidth: true; spacing: Style.space(12)
          RowLayout {
            visible: !!root.release.available || root.release.busy === "installing"; Layout.fillWidth: true
            Label { text: root.release.busy === "installing" ? "Updating Bouncer…" : "Bouncer " + (root.release.version || "update") + " is available."; color: root.dim; font.pixelSize: Style.font.caption; Layout.fillWidth: true }
            Action { text: "Update"; enabled: !root.release.busy; opacity: enabled ? 1 : 0.4; tooltipText: "Installs it and restarts the shell"; onClicked: root.service.send({op: "update"}) }
          }
          RowLayout {
            visible: !!root.snapshot.helperStale; Layout.fillWidth: true
            Label { text: "This version has a newer blocking helper."; color: root.dim; font.pixelSize: Style.font.caption; Layout.fillWidth: true }
            Action { text: "Refresh"; enabled: !root.snapshot.auth; opacity: enabled ? 1 : 0.4; tooltipText: "Asks for your password once"; onClicked: root.service.send({op: "helper-refresh"}) }
          }
          RowLayout {
            Layout.fillWidth: true
            Label { text: "TODAY"; color: root.dim; font.pixelSize: Style.font.caption; Layout.fillWidth: true }
            Label { text: root.doneTasks.length + " of " + root.tasks.length + " done"; color: root.dim; font.pixelSize: Style.font.caption }
          }
          Rectangle {
            Layout.fillWidth: true; implicitHeight: Style.space(3)
            color: Util.alpha(root.foreground, 0.12)
            Rectangle { height: parent.height; width: parent.width * (root.tasks.length ? root.doneTasks.length / root.tasks.length : 0); color: root.tone }
          }
          Label { visible: !root.tasks.length; text: "A short list is a good start."; color: root.dim; Layout.fillWidth: true }
          Label { visible: root.tasks.length > 0 && !root.openTasks.length; text: root.snapshot.fullUnlock ? "Everything is done. You’re unlocked." : "All tasks passed."; color: root.tone; Layout.fillWidth: true }
          Repeater {
            model: root.snapshot.carry || []
            delegate: ColumnLayout {
              required property var modelData
              Layout.fillWidth: true; spacing: Style.space(4)
              Label { text: modelData.text; Layout.fillWidth: true }
              RowLayout {
                Label { text: "From yesterday"; color: root.dim; font.pixelSize: Style.font.caption; Layout.fillWidth: true }
                Action { text: "Keep"; onClicked: root.service.send({op: "carry", id: modelData.id, action: "carry"}) }
                Action { text: "Drop"; onClicked: root.service.send({op: "carry", id: modelData.id, action: "drop"}) }
              }
            }
          }
          Repeater {
            model: root.visibleTasks
            delegate: ColumnLayout {
              id: taskRow
              required property var modelData
              readonly property bool passed: modelData.status === "passed"
              readonly property var change: (root.snapshot.pending || {})[modelData.id]
              Layout.fillWidth: true; spacing: Style.space(4)
              RowLayout {
                Layout.fillWidth: true; spacing: Style.space(8)
                Label { text: taskRow.passed ? "✓" : modelData.main ? "★" : "·"; color: modelData.main || taskRow.passed ? root.tone : root.dim; Layout.alignment: Qt.AlignTop }
                Label {
                  visible: root.editing !== modelData.id
                  text: modelData.text; Layout.fillWidth: true
                  color: taskRow.passed ? root.dim : root.foreground
                  MouseArea { anchors.fill: parent; enabled: !root.snapshot.started; onClicked: { edit.text = modelData.text; root.editing = modelData.id; edit.forceActiveFocus() } }
                }
                TextInput {
                  id: edit
                  visible: root.editing === modelData.id
                  Layout.fillWidth: true; color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body
                  maximumLength: 500; selectByMouse: true
                  onAccepted: { if (text.trim()) root.service.send({op: "change", id: modelData.id, action: "edit", text: text.trim()}); root.editing = "" }
                  Keys.onEscapePressed: root.editing = ""
                }
                Action { visible: !root.snapshot.started; text: "★"; selected: modelData.main; tooltipText: "Make this the main task"; onClicked: root.service.send({op: "change", id: modelData.id, action: "main"}) }
                Action { visible: !root.snapshot.started; text: "×"; tooltipText: "Remove task"; onClicked: root.service.send({op: "change", id: modelData.id, action: "delete"}) }
              }
              Label { visible: !!modelData.note; text: modelData.note || ""; color: root.dim; font.pixelSize: Style.font.caption; Layout.fillWidth: true; Layout.leftMargin: Style.space(18) }
              Label {
                visible: !!modelData.timer && !taskRow.passed
                text: !modelData.timer ? "" : modelData.timer.done ? "Timer finished" : "Timer · " + Math.max(0, Math.ceil((modelData.timer.until - (root.service ? root.service.clock : 0)) / 60)) + "m left"
                color: root.tone; font.pixelSize: Style.font.caption
              }
              RowLayout {
                visible: !!taskRow.change; Layout.fillWidth: true
                Label { text: taskRow.change ? taskRow.change.action + " in " + Math.max(0, Math.ceil(taskRow.change.readyAt - (root.service ? root.service.clock : 0))) + "s" : ""; color: root.dim; font.pixelSize: Style.font.caption; Layout.fillWidth: true }
                Action { text: "Cancel"; onClicked: root.service.send({op: "cancel", id: modelData.id}) }
              }
            }
          }
          Action { visible: root.doneTasks.length > 0; text: (root.showDone ? "Hide" : "Show") + " completed (" + root.doneTasks.length + ")"; onClicked: root.showDone = !root.showDone }
          RowLayout {
            visible: !root.snapshot.started && !!root.snapshot.setup; Layout.fillWidth: true
            Label { text: !root.tasks.length ? "Add your tasks below." : !root.mainTask ? "Choose a main task with ★." : (root.snapshot.carry || []).length ? "Keep or drop yesterday's tasks." : "Ready when you are."; color: root.dim; font.pixelSize: Style.font.caption; Layout.fillWidth: true }
            Action { text: "Start day"; selected: true; enabled: root.readyToStart; opacity: enabled ? 1 : 0.4; onClicked: root.service.send({op: "start"}) }
          }
          Ui.PanelSeparator { Layout.fillWidth: true; foreground: root.foreground }
          RowLayout {
            Label { text: "BOUNCER"; color: root.dim; font.pixelSize: Style.font.caption; Layout.fillWidth: true }
            Action { text: "History"; onClicked: root.page = "history" }
          }
          Label { Layout.fillWidth: true; text: root.chat.busy && !root.chat.streaming ? (root.chat.activity || "Thinking…") : (root.latest.text.indexOf("Unknown command.") === 0 && root.latest.text.length > 120 ? "Unknown command. Open Settings or type /help." : root.latest.text); color: root.chat.busy ? root.dim : root.foreground }
        }

        ColumnLayout {
          visible: root.page === "history"; Layout.fillWidth: true; spacing: Style.space(10)
          Action { text: "Back to today"; onClicked: root.page = "today" }
          Repeater {
            model: root.chat.messages || []
            delegate: ColumnLayout {
              required property var modelData
              Layout.fillWidth: true; spacing: Style.space(3)
              Label { text: modelData.role === "user" ? "YOU" : "BOUNCER"; color: root.dim; font.pixelSize: Style.font.caption }
              Label { text: modelData.text; Layout.fillWidth: true }
            }
          }
        }

        ColumnLayout {
          visible: root.page === "settings"; Layout.fillWidth: true; spacing: Style.space(12)
          Label { text: "AGENT"; color: root.dim; font.pixelSize: Style.font.caption }
          Flow {
            Layout.fillWidth: true; spacing: Style.space(6)
            Repeater {
              model: [{id:"auto",label:"Auto"},{id:"claude",label:"Claude"},{id:"codex",label:"OpenAI"},{id:"grok",label:"Grok"},{id:"opencode",label:"OpenCode"}]
              delegate: Action {
                required property var modelData
                text: modelData.label; selected: root.snapshot.settings.provider === modelData.id
                onClicked: root.service.send({op:"settings", values:{provider:modelData.id}})
              }
            }
          }
          Label { text: root.backend.ok === false ? root.backend.error : root.backend.label || ""; color: root.backend.ok === false ? Color.urgent : root.dim; Layout.fillWidth: true }
          Label { visible: !!root.backend.note; text: root.backend.note || ""; color: root.dim; Layout.fillWidth: true; font.pixelSize: Style.font.caption }
          Flow {
            visible: root.backend.provider === "claude"; Layout.fillWidth: true; spacing: Style.space(6)
            Repeater { model: ["haiku","sonnet","opus"]; delegate: Action { required property string modelData; text: modelData; selected: root.backend.model === modelData; onClicked: root.service.send({op:"settings",values:{model:modelData}}) } }
          }
          Label { text: "Change model with /model NAME. /models lists options."; color: root.dim; Layout.fillWidth: true; font.pixelSize: Style.font.caption }
          Ui.PanelSeparator { Layout.fillWidth: true; foreground: root.foreground }
          Label { text: "PLANNING"; color: root.dim; font.pixelSize: Style.font.caption }
          RowLayout {
            Action { text: "Quick capture"; selected: root.snapshot.settings.planning !== "guided"; onClicked: root.service.send({op:"settings",values:{planning:"quick"}}) }
            Action { text: "Guided"; selected: root.snapshot.settings.planning === "guided"; onClicked: root.service.send({op:"settings",values:{planning:"guided"}}) }
          }
          Label { text: "Quick capture adds tasks without an interview. Review rules stay the same."; color: root.dim; Layout.fillWidth: true; font.pixelSize: Style.font.caption }
          Label { text: "MODE"; color: root.dim; font.pixelSize: Style.font.caption }
          Flow {
            Layout.fillWidth: true; spacing: Style.space(6)
            Repeater {
              model: root.levels
              delegate: Action {
                required property string modelData
                text: modelData; selected: root.snapshot.settings.strictness === modelData
                enabled: !root.snapshot.started || root.levels.indexOf(modelData) >= root.levels.indexOf(root.snapshot.settings.strictness)
                opacity: enabled ? 1 : 0.4
                onClicked: root.service.send({op:"settings",values:{strictness:modelData}})
              }
            }
          }
          Label { text: "You can lower the mode before the day starts."; color: root.dim; Layout.fillWidth: true; font.pixelSize: Style.font.caption }
          Ui.PanelSeparator { Layout.fillWidth: true; foreground: root.foreground }
          Label { text: "BLOCKED SITES & APPS"; color: root.dim; font.pixelSize: Style.font.caption }
          Label { text: (root.snapshot.settings.sites || []).concat(root.snapshot.settings.apps || []).join(" · ") || "Nothing blocked."; Layout.fillWidth: true }
          Label { text: "Ask Bouncer to add or remove a block."; color: root.dim; Layout.fillWidth: true; font.pixelSize: Style.font.caption }
          Label { text: "APPROVED FOLDERS"; color: root.dim; font.pixelSize: Style.font.caption }
          Label { text: (root.snapshot.settings.roots || []).join("\n") || "None. Use /folder PATH to approve one."; Layout.fillWidth: true; color: root.dim }
          Label { text: "Recovery: run focusctl recover in a terminal. This removes blocks and pauses enforcement."; Layout.fillWidth: true; color: root.dim; font.pixelSize: Style.font.caption }
          Ui.PanelSeparator { Layout.fillWidth: true; foreground: root.foreground }
          Label { text: "UPDATES"; color: root.dim; font.pixelSize: Style.font.caption }
          Label {
            Layout.fillWidth: true; color: root.release.error ? Color.urgent : root.dim
            text: !root.release.managed ? "Version " + (root.release.current || "unknown") + ". This copy updates by hand."
                : root.release.busy === "checking" ? "Checking…" : root.release.busy === "installing" ? "Updating…"
                : root.release.error ? "Could not check: " + root.release.error
                : root.release.available ? "Version " + (root.release.version || "newer") + " is available. You have " + root.release.current + "."
                : "Version " + (root.release.current || "unknown") + (root.release.checked ? ", up to date." : ".")
          }
          RowLayout {
            visible: !!root.release.managed
            Action { visible: !!root.release.available; text: "Update"; selected: true; enabled: !root.release.busy; opacity: enabled ? 1 : 0.4; onClicked: root.service.send({op: "update"}) }
            Action { text: "Check now"; enabled: !root.release.busy; opacity: enabled ? 1 : 0.4; onClicked: root.service.send({op: "update-check"}) }
            Action { text: "Check automatically"; selected: root.snapshot.settings.updates !== false; onClicked: root.service.send({op: "settings", values: {updates: root.snapshot.settings.updates === false}}) }
          }
          Label { text: "Bouncer only looks for a newer version. Nothing installs until you choose Update."; color: root.dim; Layout.fillWidth: true; font.pixelSize: Style.font.caption }
        }
      }
    }

    ColumnLayout {
      visible: !!root.snapshot.challenge; Layout.fillWidth: true
      Label { text: root.snapshot.challenge ? root.snapshot.challenge.code : ""; Layout.fillWidth: true; color: root.tone }
      Label { text: !root.snapshot.challenge ? "" : root.snapshot.challenge.readyAt === null ? "Type this code exactly for 15 minutes. It is logged." : "Unlocking in " + Math.max(0, Math.ceil(root.snapshot.challenge.readyAt - root.service.clock)) + "s"; Layout.fillWidth: true; color: root.dim; font.pixelSize: Style.font.caption }
    }
    ColumnLayout {
      visible: !!root.chat.consent; Layout.fillWidth: true
      Label { text: root.chat.consent ? root.chat.consent.text : ""; Layout.fillWidth: true }
      Image { visible: !!root.chat.consent && !!root.chat.consent.preview; source: visible ? "file://" + root.chat.consent.preview : ""; Layout.fillWidth: true; Layout.preferredHeight: visible ? Style.space(140) : 0; fillMode: Image.PreserveAspectFit; cache: false }
      Label { text: root.chat.consent ? "Recipient: " + root.chat.consent.goes : ""; Layout.fillWidth: true; color: root.dim; font.pixelSize: Style.font.caption }
      RowLayout {
        Action { text: root.chat.consent && root.chat.consent.kind === "share" ? "Send image" : root.chat.consent && root.chat.consent.kind === "screen" ? "Capture" : "Allow"; onClicked: root.service.send({op:"consent",answer:true}) }
        Action { text: "Cancel"; onClicked: root.service.send({op:"consent",answer:false}) }
      }
    }
    Flow {
      visible: !!root.chat.choices && !root.chat.busy; Layout.fillWidth: true; spacing: Style.space(6)
      Repeater {
        model: root.chat.choices ? root.chat.choices.options || [] : []
        delegate: Action {
          required property string modelData
          text: modelData; selected: root.picked.indexOf(modelData) >= 0
          onClicked: {
            root.adding = false
            if (root.chat.choices.multiple) root.picked = selected ? root.picked.filter(function(p) { return p !== modelData }) : root.picked.concat([modelData])
            else { prompt.text = modelData; root.submit() }
          }
        }
      }
    }
    Ui.PanelSeparator { Layout.fillWidth: true; foreground: root.foreground }
    RowLayout {
      Layout.fillWidth: true
      Action { text: "Talk"; selected: !root.adding; enabled: !root.sending; onClicked: { root.adding = false; root.showConversation(); prompt.forceActiveFocus() } }
      Action { text: "Add task"; selected: root.adding; enabled: !root.sending; onClicked: { root.adding = true; root.page = "today"; prompt.forceActiveFocus() } }
      Item { Layout.fillWidth: true }
      Label { text: root.snapshot.settings.strictness || "standard"; color: root.dim; font.pixelSize: Style.font.caption }
    }
    Ui.BorderSurface {
      Layout.fillWidth: true
      implicitHeight: Math.min(Style.space(100), Math.max(Style.space(42), prompt.contentHeight + Style.space(20)))
      color: Style.controlFill(prompt.activeFocus, false, root.foreground, root.tone)
      borderSpec: Border.controlSpec(prompt.activeFocus ? "focus" : "normal", root.foreground, root.tone)
      radius: Style.cornerRadius
      TextEdit {
        id: prompt
        anchors.fill: parent; anchors.margins: Style.space(10)
        color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body
        wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText; selectByMouse: true; clip: true
        readOnly: root.sending
        Keys.onPressed: function(event) {
          if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && !(event.modifiers & Qt.ShiftModifier)) { root.submit(); event.accepted = true }
          else if (event.key === Qt.Key_Escape) { root.service.close(); event.accepted = true }
          else if (event.key === Qt.Key_Tab && !text && !root.adding && root.chat.suggestion) { text = root.chat.suggestion; event.accepted = true }
          else if (event.key === Qt.Key_V && (event.modifiers & Qt.ControlModifier)) root.service.send({op:"paste"})
        }
        Label { visible: !prompt.text; text: root.adding ? "One task per line…" : root.chat.suggestion || "Tell me what's done…"; color: root.dim; width: parent.width }
      }
    }
    Label { visible: !!root.inputError || !!(root.service && root.service.error) || !!root.snapshot.blockingError; text: root.inputError || (root.service ? root.service.error : "") || root.snapshot.blockingError || ""; color: Color.urgent; font.pixelSize: Style.font.caption; Layout.fillWidth: true }
    RowLayout {
      Layout.fillWidth: true
      Label { text: root.sending ? "Sending…" : "Enter sends · Shift+Enter adds a line"; color: root.dim; font.pixelSize: Style.font.caption; Layout.fillWidth: true }
      Action { text: root.adding ? "Add" : "Send"; enabled: !root.sending && (!!prompt.text.trim() || root.picked.length > 0 || (!root.adding && !!root.chat.suggestion)); onClicked: root.submit() }
    }
  }
  component Label: Text { color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body; textFormat: Text.PlainText; wrapMode: Text.Wrap }
  component Action: Ui.Button { foreground: root.foreground; accent: root.tone; bordered: true; focusable: true; fontSize: Style.font.caption; verticalPadding: Style.space(4); horizontalPadding: Style.space(8) }
}
