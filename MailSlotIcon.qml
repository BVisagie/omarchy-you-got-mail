import QtQuick
import QtQuick.Window
import qs.Commons

// Closed envelope, back view: landscape body, straight flap crease, wax
// seal. Not the front V-flap used by the other Gmail widget.
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

  readonly property real stroke: snap(Math.max(1.3, iconSize * 0.10))
  readonly property real inset: snap(stroke / 2)

  readonly property real bodyW: snap(iconSize - stroke)
  readonly property real bodyH: snap(iconSize * 0.64)
  readonly property real bodyX: inset
  readonly property real bodyY: snap((iconSize - bodyH) / 2)
  readonly property real bodyR: snap(Math.max(1.1, iconSize * 0.09))

  // Straight flap crease, broken in the middle for the seal.
  readonly property real creaseY: snap(bodyY + bodyH * 0.40)
  readonly property real creaseInset: snap(stroke * 1.7)

  readonly property real sealR: snap(Math.max(1.6, iconSize * 0.12))
  readonly property real sealX: snap(bodyX + bodyW / 2)
  readonly property real sealY: creaseY
  readonly property real sealGap: snap(sealR * 1.55)

  property real sealAmount: hasMail ? 1 : 0
  Behavior on sealAmount {
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
      ctx.strokeStyle = root.color
      ctx.fillStyle = root.color
      ctx.lineWidth = root.stroke
      ctx.lineJoin = "round"
      ctx.lineCap = "round"

      ctx.beginPath()
      roundRect(ctx, root.bodyX, root.bodyY, root.bodyW, root.bodyH, root.bodyR)
      ctx.stroke()

      var creaseLeft = root.bodyX + root.creaseInset
      var creaseRight = root.bodyX + root.bodyW - root.creaseInset
      var gap = root.sealAmount > 0.01 ? root.sealGap : 0
      ctx.beginPath()
      ctx.moveTo(creaseLeft, root.creaseY)
      ctx.lineTo(root.sealX - gap, root.creaseY)
      ctx.moveTo(root.sealX + gap, root.creaseY)
      ctx.lineTo(creaseRight, root.creaseY)
      ctx.stroke()

      if (root.sealAmount > 0.01) {
        ctx.globalAlpha = root.sealAmount
        ctx.beginPath()
        ctx.arc(root.sealX, root.sealY, root.sealR, 0, Math.PI * 2)
        ctx.fill()
        ctx.globalAlpha = 1
      }
    }
  }

  onColorChanged: canvas.requestPaint()
  onSealAmountChanged: canvas.requestPaint()
  onBodyWChanged: canvas.requestPaint()
  onDprChanged: canvas.requestPaint()
  Component.onCompleted: canvas.requestPaint()
}
