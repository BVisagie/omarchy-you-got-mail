import QtQuick
import QtQuick.Window
import qs.Commons

// Rural mailbox with a pivoting flag. Flag up (theme accent) means mail.
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

  readonly property real boxW: snap(iconSize * 0.76)
  readonly property real boxH: snap(iconSize * 0.50)
  readonly property real boxX: snap(iconSize * 0.02)
  readonly property real boxY: snap(iconSize * 0.40)
  readonly property real boxR: snap(Math.max(1.1, iconSize * 0.08))

  readonly property real stemLen: snap(iconSize * 0.46)
  readonly property real stemThick: snap(Math.max(1.7, iconSize * 0.11))
  readonly property real clothLen: snap(iconSize * 0.42)
  readonly property real clothThick: snap(Math.max(2.2, iconSize * 0.16))
  readonly property real pivotX: snap(boxX + boxW - stemThick * 0.20)
  readonly property real pivotY: snap(boxY + boxH * 0.16)

  property real flagAmount: hasMail ? 1 : 0
  Behavior on flagAmount {
    NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
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

      // Flag first so the box covers the pivot. Local +x is "along the stem";
      // rotate -90° for flag-up. Cloth hangs +y (down when the flag is down,
      // back over the box when the flag is up).
      ctx.fillStyle = root.flagColor
      ctx.save()
      ctx.translate(root.pivotX, root.pivotY)
      ctx.rotate(-Math.PI / 2 * root.flagAmount)
      ctx.beginPath()
      roundRect(ctx, 0, -root.stemThick / 2, root.stemLen, root.stemThick, root.stemThick / 2)
      ctx.fill()
      ctx.beginPath()
      // Cloth in local -y so a -90° raise puts it over the box, not out
      // to the right (which reads as a musical note).
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

      ctx.fillStyle = root.color
      ctx.beginPath()
      roundRect(ctx, root.boxX, root.boxY, root.boxW, root.boxH, root.boxR)
      ctx.fill()
    }
  }

  onColorChanged: canvas.requestPaint()
  onFlagColorChanged: canvas.requestPaint()
  onFlagAmountChanged: canvas.requestPaint()
  onBoxWChanged: canvas.requestPaint()
  onDprChanged: canvas.requestPaint()
  Component.onCompleted: canvas.requestPaint()
}
