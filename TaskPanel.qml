import QtQuick

// Hosts the full-screen takeovers. The card itself is the dropdown in Focus.qml.
Item {
  id: root
  property var shell: null
  property var service: null
  function open(payload) {}
  // The host calls close() from shell.hide(); never call shell.hide() back.
  function close() { if (service) service.overlayClosed() }
  FocusOverlay { service: root.service }
}
