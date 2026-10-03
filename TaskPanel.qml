import QtQuick

Item {
  id: root
  property var shell: null
  property var service: null
  function open(payload) { if (service) service.opened() }
  // The host calls close() from shell.hide(); never call shell.hide() back.
  function close() { if (service) service.dismissed() }
  FocusOverlay { service: root.service }
}
