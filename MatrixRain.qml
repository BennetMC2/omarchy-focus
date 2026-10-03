import QtQuick
import qs.Commons

// Falling-glyph rain in the theme's own colours. Each frame veils the last one, which leaves the trails.
Canvas {
  id: rain
  property bool running: false
  property color ink: Color.accent
  property color head: Color.foreground
  property color veil: Color.background
  readonly property string glyphs: "0123456789ABCDEF<>/\\|{}[]=+-*#$%&@:;"
  readonly property int cell: Style.space(20)
  property var drops: []

  function restart() {
    var columns = Math.ceil(width / cell), fresh = []
    // Staggered starts, some already on screen, so the rain arrives at once instead of as a curtain.
    for (var i = 0; i < columns; i++) fresh.push(Math.floor(Math.random() * 46) - 30)
    drops = fresh
    if (!available) return
    var ctx = getContext("2d")
    if (ctx) { ctx.fillStyle = Qt.rgba(veil.r, veil.g, veil.b, 1); ctx.fillRect(0, 0, width, height) }
  }
  onRunningChanged: if (running) restart()
  onAvailableChanged: if (available && running) restart()
  onWidthChanged: if (running) restart()

  onPaint: {
    if (!available) return
    var ctx = getContext("2d")
    ctx.fillStyle = Qt.rgba(veil.r, veil.g, veil.b, 0.16)
    ctx.fillRect(0, 0, width, height)
    ctx.font = "bold " + Math.round(cell * 0.82) + "px '" + Style.font.family + "'"
    for (var i = 0; i < drops.length; i++) {
      var y = drops[i] * cell
      if (y > 0) {
        ctx.fillStyle = ink
        ctx.fillText(glyphs.charAt(Math.floor(Math.random() * glyphs.length)), i * cell, y - cell)
        ctx.fillStyle = head
        ctx.fillText(glyphs.charAt(Math.floor(Math.random() * glyphs.length)), i * cell, y)
      }
      drops[i] = y > height && Math.random() > 0.96 ? -Math.floor(Math.random() * 12) : drops[i] + 1
    }
  }
  Timer { interval: 40; running: rain.running && rain.visible; repeat: true; onTriggered: rain.requestPaint() }
}
