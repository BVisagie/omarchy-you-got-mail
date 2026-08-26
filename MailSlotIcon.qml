import QtQuick
import QtQuick.Window
import qs.Commons

// Letterbox mark: a solid slot lip, and when there is mail a dog-eared
// note sitting on it. Outline vs fill so the two shapes stay separate.
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

  readonly property real lipW: snap(iconSize - stroke)
  readonly property real lipH: snap(Math.max(2.2, iconSize * 0.16))
  readonly property real lipX: snap((iconSize - lipW) / 2)
  readonly property real lipY: snap(iconSize - lipH - stroke / 2)
  readonly property real lipR: snap(lipH / 2)

  readonly property real paperW: snap(iconSize * 0.62)
  readonly property real paperH: snap(iconSize * 0.58)
  readonly property real paperX: snap((iconSize - paperW) / 2)
  readonly property real paperY: snap(stroke / 2)
  readonly property real fold: snap(Math.max(2.4, paperW * 0.34))
  // Overlap the lip so the note is in the slot, not perched on a stand.
  readonly property real air: snap(-lipH * 0.40)

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
      ctx.strokeStyle = root.color
      ctx.lineWidth = root.stroke
      ctx.lineJoin = "round"
      ctx.lineCap = "round"

      ctx.beginPath()
      roundRect(ctx, root.lipX, root.lipY, root.lipW, root.lipH, root.lipR)
      ctx.fill()

      if (root.paperAmount > 0.01) {
        var h = Math.min(root.paperH, root.lipY - root.air - root.paperY)
        if (h < root.stroke * 3)
          h = root.lipY + root.lipH * 0.4 - root.paperY
        var w = root.paperW
        var x = root.paperX
        var y = root.paperY
        var f = Math.min(root.fold, w * 0.45, h * 0.45)
        if (h > root.stroke * 3 && w > root.stroke * 3) {
          ctx.globalAlpha = root.paperAmount
          ctx.beginPath()
          ctx.moveTo(x, y + f * 0.15)
          ctx.lineTo(x, y + h)
          ctx.lineTo(x + w, y + h)
          ctx.lineTo(x + w, y + f)
          ctx.lineTo(x + w - f, y)
          ctx.lineTo(x + f * 0.15, y)
          ctx.closePath()
          ctx.stroke()
          ctx.beginPath()
          ctx.moveTo(x + w - f, y)
          ctx.lineTo(x + w - f, y + f)
          ctx.lineTo(x + w, y + f)
          ctx.stroke()
          ctx.globalAlpha = 1
        }
      }
    }
  }

  onColorChanged: canvas.requestPaint()
  onPaperAmountChanged: canvas.requestPaint()
  onLipWChanged: canvas.requestPaint()
  onDprChanged: canvas.requestPaint()
  Component.onCompleted: canvas.requestPaint()
}
