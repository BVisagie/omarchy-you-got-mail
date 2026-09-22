import QtQuick
import QtQuick.Controls
import qs.Commons

// A bounded list inside the existing card, shared by accounts and help.
ListView {
  id: root
  required property color foreground
  required property color accent
  required property string fontFamily
  property bool help: false
  property int cursor: -1
  property real maximumHeight: Style.space(400)
  signal activated(var entry)
  signal hovered(int index)

  height: Math.min(contentHeight, maximumHeight)
  clip: true
  spacing: Style.space(4)
  boundsBehavior: Flickable.StopAtBounds
  ScrollBar.vertical: ScrollBar {
    policy: root.contentHeight > root.height ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
  }

  function revealCursor() {
    if (cursor >= 0) positionViewAtIndex(cursor, ListView.Contain)
  }

  delegate: Rectangle {
    id: row
    required property var modelData
    required property int index
    width: root.width - Style.space(12)
    height: rowContent.implicitHeight + Style.space(12)
    radius: Style.cornerRadius
    color: !root.help && modelData.enabled && (root.cursor === index || mouse.containsMouse)
      ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.08) : "transparent"

    Column {
      id: rowContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(6)
      spacing: Style.space(3)

      Text {
        width: parent.width
        text: root.help ? row.modelData.key : row.modelData.title
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
        color: root.foreground
      }

      Text {
        width: parent.width
        text: root.help ? row.modelData.title : row.modelData.detail
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        color: root.foreground
        opacity: 0.7
      }

      Text {
        visible: !root.help
        width: parent.width
        text: row.modelData.action || ""
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        color: row.modelData.enabled ? root.accent : root.foreground
        opacity: row.modelData.enabled ? 1 : 0.5
      }
    }

    MouseArea {
      id: mouse
      anchors.fill: parent
      enabled: !root.help && row.modelData.enabled === true
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onContainsMouseChanged: if (containsMouse) root.hovered(row.index)
      onClicked: root.activated(row.modelData)
    }
  }
}
