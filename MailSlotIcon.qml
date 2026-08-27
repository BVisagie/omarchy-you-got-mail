import QtQuick
import QtQuick.Window
import qs.Commons

// Rural mailbox: arched outline, post, and a pivoting flag. Flag up means mail.
// Stroke, not a filled blob, so the silhouette keeps contrast on a transparent
// bar and on light, dark, or mixed wallpapers. Every flag pose stays inside
// the optical canvas.
Item {
  id: root

  property real iconSize: Style.bar.iconCanvas
  property color color: Color.foreground
  property color flagColor: color
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

  function snapStroke(v) {
    return Math.max(1, Math.round(v * root.dpr)) / root.dpr
  }

  readonly property real stroke: snapStroke(Math.max(1.5, iconSize * 0.12))
  readonly property real pad: snap(Math.max(stroke / 2, 0.5))

  readonly property real bodyW: {
    var minFlag = stroke * 1.8
    return snap(Math.min(iconSize * 0.66, iconSize - pad * 2 - minFlag))
  }
  readonly property real archR: snap(bodyW / 2)
  readonly property real postH: snap(Math.max(stroke * 1.2, iconSize * 0.14))
  readonly property real bodyRectH: {
    var maxH = iconSize - pad * 2 - postH - archR
    return snap(Math.max(stroke * 2, Math.min(iconSize * 0.26, maxH)))
  }
  readonly property real bodyH: snap(archR + bodyRectH)
  readonly property real bodyX: snap(pad)
  readonly property real bodyY: snap(Math.max(pad, iconSize - pad - postH - bodyH))

  readonly property real postX: snap(bodyX + archR)
  readonly property real postY: snap(bodyY + bodyH)

  readonly property real pivotX: snap(bodyX + bodyW - stroke * 0.2)
  readonly property real pivotY: snap(bodyY + archR * 0.42)

  // 1.42 ≈ √2 so the cloth corner stays inside the canvas at 45°.
  readonly property real flagLen: {
    var up = Math.max(0, pivotY - pad)
    var right = Math.max(0, iconSize - pad - pivotX)
    var left = Math.max(0, pivotX - pad)
    return snap(Math.max(0, Math.min(iconSize * 0.30, up / 1.42, right, left)))
  }
  readonly property real stemLen: flagLen
  readonly property real clothLen: flagLen
  readonly property real stemThick: snap(Math.min(stemLen, Math.max(1.6, Math.min(iconSize * 0.14, stemLen * 0.46))))
  readonly property real clothThick: snap(Math.min(stemLen, Math.max(2.0, Math.min(iconSize * 0.18, stemLen * 0.58))))

  readonly property real doorW: snap(bodyW * 0.42)
  readonly property real doorY: snap(bodyY + archR + bodyRectH * 0.38)

  property real flagAmount: hasMail ? 1 : 0
  Behavior on flagAmount {
    NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
  }

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
      ctx.lineCap = "round"
      ctx.lineJoin = "round"

      // Flag first so the body stroke covers the pivot. Local +x is along the
      // stem; rotate -90° for flag-up. Cloth sits in local -y so a raise puts
      // it over the box instead of out to the right.
      ctx.fillStyle = root.flagColor
      ctx.save()
      ctx.translate(root.pivotX, root.pivotY)
      ctx.rotate(-Math.PI / 2 * root.flagAmount)
      ctx.beginPath()
      roundRect(ctx, 0, -root.stemThick / 2, root.stemLen, root.stemThick, root.stemThick / 2)
      ctx.fill()
      ctx.beginPath()
      roundRect(
        ctx,
        root.stemLen - root.clothThick,
        -root.clothLen,
        root.clothThick,
        root.clothLen,
        root.clothThick / 2
      )
      ctx.fill()
      ctx.restore()

      ctx.strokeStyle = root.color
      ctx.fillStyle = root.color
      ctx.lineWidth = root.stroke

      var r = root.archR
      var x = root.bodyX
      var y = root.bodyY
      var w = root.bodyW
      var h = root.bodyH
      ctx.beginPath()
      ctx.arc(x + r, y + r, r, Math.PI, 0, false)
      ctx.lineTo(x + w, y + h)
      ctx.lineTo(x, y + h)
      ctx.closePath()
      ctx.stroke()

      ctx.lineWidth = root.stroke
      ctx.beginPath()
      ctx.moveTo(root.postX, root.postY)
      ctx.lineTo(root.postX, root.postY + root.postH)
      ctx.stroke()

      ctx.lineWidth = root.snapStroke(Math.max(1.2, root.stroke * 0.85))
      var doorX = root.snap(x + (w - root.doorW) / 2)
      ctx.beginPath()
      ctx.moveTo(doorX, root.doorY)
      ctx.lineTo(doorX + root.doorW, root.doorY)
      ctx.stroke()
    }
  }

  onColorChanged: canvas.requestPaint()
  onFlagColorChanged: canvas.requestPaint()
  onFlagAmountChanged: canvas.requestPaint()
  onIconSizeChanged: canvas.requestPaint()
  onBodyWChanged: canvas.requestPaint()
  onFlagLenChanged: canvas.requestPaint()
  onDprChanged: canvas.requestPaint()
  Component.onCompleted: canvas.requestPaint()
}
