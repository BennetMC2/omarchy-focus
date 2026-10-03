import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons

// Full-screen moments: a block reached, the day locked in, the unlock, a new day. The card itself lives under the bar icon.
Item {
  id: root
  property var service: null
  readonly property var snapshot: service ? service.state : ({tasks: [], carry: [], settings: {}, pending: {}, overrides: [], setup: true})
  readonly property var chat: service ? service.chat : ({messages: [], streaming: "", activity: "", suggestion: "", busy: false})
  readonly property real clock: service ? service.clock : 0
  readonly property bool open: !!service && service.view === "takeover" && !service.screenLocked
  readonly property string strictness: (service && service.skinPreview) || snapshot.settings.strictness || "standard"
  // Lockdown runs in the theme's red; hard and lockdown get scanlines.
  readonly property color tone: strictness === "lockdown" ? Color.urgent : Color.accent
  readonly property string rank: {
    var days = snapshot.streak || 0
    return days >= 30 ? "ghost" : days >= 14 ? "veteran" : days >= 7 ? "specialist" : days >= 3 ? "operator" : days >= 1 ? "initiate" : "drifter"
  }
  readonly property string kind: service ? service.alarmKind : ""
  readonly property string bannerTitle: kind === "granted" ? "ACCESS GRANTED" : kind === "morning" ? "NEW DAY" : kind === "start" ? "LOCKED IN" : "ACCESS DENIED"
  readonly property var mainTask: (snapshot.tasks || []).filter(function(t) { return t.main })[0] || null
  // When the moment has played, hand over to the dropdown (or to nothing, after locking in).
  onIntroChanged: if (!intro && alarm && service) Qt.callLater(service.endTakeover)
  readonly property string bannerLine: {
    if (kind === "granted") return "everything is unlocked. good work."
    if (kind === "start") return (mainTask ? "★ " + mainTask.text + " · " : "") + (snapshot.total || 0) + " to go"
    if (kind === "morning") {
      var y = snapshot.yesterday
      return (y ? "yesterday " + y.completed + " of " + y.total + (y.grade ? " · " + y.grade.toLowerCase() : "") + " · " : "") + "rank " + rank + " · everything is locked"
    }
    return (service && service.alarmName ? service.alarmName : "that one") + " is locked until today's work is done"
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
      onVisibleChanged: if (visible) Qt.callLater(function() { keys.forceActiveFocus() })
      Item { id: keys; focus: true; Keys.onPressed: function(event) { root.service.close(); event.accepted = true } }

      // Dark enough to read over without needing compositor blur, which a plugin should not switch on for you.
      Rectangle { anchors.fill: parent; color: Util.alpha(Color.background, 0.84) }
      MatrixRain {
        anchors.fill: parent
        visible: root.alarm
        ink: root.kind === "granted" ? Color.accent : root.tone
        running: root.alarm && window.visible
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
    }
  }

  component Line: Text {
    color: Color.menu.text
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    textFormat: Text.PlainText
  }
}
