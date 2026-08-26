import QtQuick
import QtQuick.Window
import qs.Commons

// Letterbox mark: a door slot, empty or with a letter in the slit.
// One fill colour so it follows any theme. Canvas so the slit is a real
// punch-through (not a second glyph) and stays sharp at 1× and 2×.
Item {
  id: root

  property real iconSize: Style.bar.iconCanvas
  property color color: Color.foreground
  property bool hasMail: false

  width: iconSize
  height: iconSize
  implicitWidth: iconSize
  implicitHeight: iconSize

  readonly property real dpr: {
    var win = Window.window
    return (win && win.devicePixelRatio > 0) ? win.devicePixelRatio : 1
  }

  function snap(v) {
    return Math.round(v * root.dpr) / root.dpr
  }

  readonly property real plateW: snap(iconSize * 1.00)
  readonly property real plateH: snap(Math.max(4.5, iconSize * 0.38))
  readonly property real plateX: snap((iconSize - plateW) / 2)
  readonly property real plateY: snap(iconSize * 0.52)
  readonly property real plateR: snap(Math.min(plateH * 0.26, plateW * 0.08))

  readonly property real holeH: snap(Math.max(2.25, plateH * 0.44))
  readonly property real holeW: snap(plateW * 0.80)
  readonly property real holeX: snap(plateX + (plateW - holeW) / 2)
  readonly property real holeY: snap(plateY + (plateH - holeH) / 2)
  readonly property real holeR: snap(holeH / 2)

  readonly property real paperW: snap(Math.max(2.4, holeW * 0.32))
  readonly property real paperH: snap(iconSize * 0.42)
  readonly property real paperX: snap((iconSize - paperW) / 2)
  readonly property real paperR: snap(Math.max(0.8, paperW * 0.18))
  readonly property real paperY: snap(holeY + holeH * 0.70 - paperH)

  property real paperAmount: hasMail ? 1 : 0
  Behavior on paperAmount {
    NumberAnimation { duration: 140; easing.type: Easing.InOutQuad }
  }

  layer.enabled: true
  layer.smooth: true
  layer.samples: 8
  layer.textureSize: Qt.size(
    Math.max(1, Math.round(width * dpr)),
    Math.max(1, Math.round(height * dpr))
  )

  Canvas {
    id: canvas
    anchors.fill: parent
    antialiasing: true
    renderTarget: Canvas.FramebufferObject
    renderStrategy: Canvas.Cooperative

    function roundRect(ctx, x, y, w, h, r) {
      r = Math.min(r, w / 2, h / 2)
      if (r <= 0.25) {
        ctx.rect(x, y, w, h)
        return
      }
      ctx.moveTo(x + r, y)
      ctx.lineTo(x + w - r, y)
      ctx.arcTo(x + w, y, x + w, y + r, r)
      ctx.lineTo(x + w, y + h - r)
      ctx.arcTo(x + w, y + h, x + w - r, y + h, r)
      ctx.lineTo(x + r, y + h)
      ctx.arcTo(x, y + h, x, y + h - r, r)
      ctx.lineTo(x, y + r)
      ctx.arcTo(x, y, x + r, y, r)
      ctx.closePath()
    }

    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      ctx.clearRect(0, 0, width, height)
      ctx.fillStyle = root.color

      // Plate first, then punch the slit so it is real empty space.
      ctx.beginPath()
      roundRect(ctx, root.plateX, root.plateY, root.plateW, root.plateH, root.plateR)
      ctx.fill()

      ctx.globalCompositeOperation = "destination-out"
      ctx.beginPath()
      roundRect(ctx, root.holeX, root.holeY, root.holeW, root.holeH, root.holeR)
      ctx.fill()

      // Letter behind the plate: visible in the slit and in the air above.
      if (root.paperAmount > 0.01) {
        ctx.globalCompositeOperation = "destination-over"
        ctx.globalAlpha = root.paperAmount
        ctx.beginPath()
        roundRect(ctx, root.paperX, root.paperY, root.paperW, root.paperH, root.paperR)
        ctx.fill()
        ctx.globalAlpha = 1
      }

      ctx.globalCompositeOperation = "source-over"
    }
  }

  onColorChanged: canvas.requestPaint()
  onPaperAmountChanged: canvas.requestPaint()
  onPlateWChanged: canvas.requestPaint()
  onDprChanged: canvas.requestPaint()
  Component.onCompleted: canvas.requestPaint()
}
