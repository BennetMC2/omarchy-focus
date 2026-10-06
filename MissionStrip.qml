import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons

// While locked, a thin line under the bar keeps the main task in view. Click it to open Bouncer.
Variants {
  id: strip
  property var service: null
  readonly property var snapshot: service ? service.state : ({})
  readonly property var main: (snapshot.tasks || []).filter(function(t) { return t.main })[0] || null
  readonly property bool shown: !!service && service.stripPreview || !!service && service.ready && !!snapshot.started && !!snapshot.locked && !!(snapshot.settings || {}).strip && !service.screenLocked
  readonly property color tone: (snapshot.settings || {}).strictness === "lockdown" ? Color.urgent : Color.accent
  model: Quickshell.screens
  delegate: PanelWindow {
    required property var modelData
    screen: modelData
    visible: strip.shown
    anchors { top: true; left: true; right: true }
    implicitHeight: Style.space(24)
    exclusiveZone: implicitHeight
    color: Color.background
    WlrLayershell.namespace: "local-focus-strip"
    WlrLayershell.layer: WlrLayer.Top
    Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: Math.max(1, Style.space(1)); color: Util.alpha(strip.tone, 0.5) }
    Row {
      anchors { left: parent.left; leftMargin: Style.space(14); verticalCenter: parent.verticalCenter }
      spacing: Style.space(10)
      Text { text: "LOCKED"; color: strip.tone; font.family: Style.font.family; font.pixelSize: Style.font.caption; font.weight: Font.Bold; font.letterSpacing: Style.space(2); anchors.verticalCenter: parent.verticalCenter }
      Text {
        text: strip.main ? (strip.main.status === "passed" ? "✓ " : "★ ") + strip.main.text : ""
        color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall; textFormat: Text.PlainText
        elide: Text.ElideRight; width: Math.min(implicitWidth, parent.parent.width * 0.6); anchors.verticalCenter: parent.verticalCenter
      }
    }
    Text {
      anchors { right: parent.right; rightMargin: Style.space(14); verticalCenter: parent.verticalCenter }
      text: ((strip.snapshot.total || 0) - (strip.snapshot.completed || 0)) + " to go"
      color: Color.muted; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
    }
    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: strip.service.openHome() }
  }
}
