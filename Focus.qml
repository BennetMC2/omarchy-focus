import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Item {
  id: root
  property var bar: null
  readonly property var shell: bar ? bar.shell : null
  property var settings: ({})
  readonly property var service: shell ? shell.serviceFor("local.focus") : null
  readonly property var state: service ? service.state : ({completed: 0, total: 0, locked: true})
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  WidgetButton {
    id: button
    bar: root.bar
    text: "       " + (root.state.completed || 0) + "/" + (root.state.total || 0)
    tooltipText: root.state.setup === false ? "Focus · say hello" : root.state.recovered ? "Focus · recovery, blocking off" : !root.state.started ? "Focus · not started" : root.state.locked ? "Focus · " + ((root.state.total || 0) - (root.state.completed || 0)) + " left" : "Focus · unlocked"
    active: root.service && root.service.view !== ""
    onPressed: {
      if (root.service) root.service.view ? root.service.close() : root.service.openHome()
      else opener.running = true
    }
    Canvas {
      id: ring
      width: 27; height: 27
      anchors.left: parent.left; anchors.leftMargin: 7; anchors.verticalCenter: parent.verticalCenter
      property real progress: root.state.total ? root.state.completed / root.state.total : 0
      onProgressChanged: requestPaint()
      Connections { target: Color; function onAccentChanged() { ring.requestPaint() } function onMutedChanged() { ring.requestPaint() } }
      onPaint: {
        var ctx = getContext("2d")
        ctx.reset(); ctx.lineWidth = 2
        ctx.strokeStyle = Color.muted; ctx.beginPath(); ctx.arc(13.5, 13.5, 12, 0, Math.PI * 2); ctx.stroke()
        ctx.strokeStyle = Color.accent; ctx.beginPath(); ctx.arc(13.5, 13.5, 12, -Math.PI/2, -Math.PI/2 + progress * Math.PI * 2); ctx.stroke()
      }
      Text {
        anchors.centerIn: parent
        text: root.state.locked ? "󰌾" : "󰌿"
        color: Color.accent
        font.family: Style.font.family; font.pixelSize: 15
        rotation: root.state.locked ? 0 : -12
        Behavior on rotation { NumberAnimation { duration: 200 } }
        scale: root.state.locked ? 1 : 1.12
        Behavior on scale { NumberAnimation { duration: 200 } }
      }
    }
  }
  Process { id: opener; command: ["omarchy-shell", "local.focus", "open"] }
}
