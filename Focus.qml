import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// The bar icon and the dropdown that hangs from it.
Panel {
  id: root
  readonly property var shell: bar ? bar.shell : null
  readonly property var service: shell ? shell.serviceFor("local.focus") : null
  readonly property var state: service ? service.state : ({completed: 0, total: 0, locked: true})
  readonly property string screenName: button.QsWindow.window && button.QsWindow.window.screen ? button.QsWindow.window.screen.name : ""
  // With a bar on every monitor, only the one Focus was opened on shows the dropdown.
  readonly property bool wanted: !!service && service.view === "open" && !service.screenLocked
    && (service.screenName === "" || screenName === "" || service.screenName === screenName)
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  onWantedChanged: wanted ? open() : close()
  // Closed from outside (a click elsewhere, another bar panel): tell the service.
  onOpenedChanged: if (!opened && wanted) service.dismissed()

  WidgetButton {
    id: button
    bar: root.bar
    text: "    " + (root.state.completed || 0) + "/" + (root.state.total || 0)
    tooltipText: root.state.setup === false ? "Focus · say hello" : root.state.recovered ? "Focus · recovery, blocking off" : !root.state.started ? "Focus · not started" : root.state.locked ? "Focus · " + ((root.state.total || 0) - (root.state.completed || 0)) + " left" : "Focus · unlocked"
    active: root.opened
    onPressed: {
      if (root.service) root.service.view ? root.service.close() : root.service.openHome(root.screenName)
      else opener.running = true
    }
    // One small dot: solid while locked, hollow once you are through.
    Rectangle {
      width: Style.space(9); height: width; radius: width / 2
      anchors.left: parent.left; anchors.leftMargin: Style.space(9); anchors.verticalCenter: parent.verticalCenter
      color: root.state.locked ? root.barForeground : "transparent"
      border.width: Math.max(1, Style.space(1.5)); border.color: root.barForeground
      Behavior on color { ColorAnimation { duration: 200 } }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: card.prompt
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(card.implicitHeight, Style.space(760))
    FocusCard {
      id: card
      anchors.fill: parent
      service: root.service
      active: root.opened
    }
  }

  Process { id: opener; command: ["omarchy-shell", "local.focus", "open"] }
}
