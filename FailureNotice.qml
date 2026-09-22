import QtQuick
import qs.Commons
import qs.Ui

// One failed account: the message, and the fix when there is one.
// A sign-in shows the exact command; click it (or ▶) to run it in a
// terminal, or ⧉ to copy it. A missing tool links to the setup guide.
// The panel does the running and copying; this file only draws and signals.
Column {
  id: root

  property var failure: ({})
  property color foreground: Color.foreground
  property color urgent: Color.urgent
  property color accent: Color.accent
  property string fontFamily: Style.font.family

  readonly property string iconRun: ""
  readonly property string iconCopy: ""
  readonly property string iconCopied: ""

  readonly property var action: (failure && failure.action) || ({})
  readonly property bool isSignIn: action.kind === "signin" && String(action.command || "") !== ""
  readonly property bool isSetup: action.kind === "setup" && String(action.url || "") !== ""
  property bool copied: false

  signal runSignIn(string accountId)
  signal copyCommand(string text)
  signal openUrl(string url)

  spacing: Style.space(3)

  Timer {
    id: copiedTimer
    interval: 1500
    onTriggered: root.copied = false
  }

  Text {
    width: parent.width
    text: String(root.failure.message || root.failure.error || "")
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    font.family: root.fontFamily
    font.pixelSize: Style.font.body
    color: root.urgent
  }

  Item {
    width: parent.width
    height: visible ? Math.max(commandChip.height, actions.height) : 0
    visible: root.isSignIn

    Rectangle {
      id: commandChip
      anchors.left: parent.left
      anchors.right: actions.left
      anchors.rightMargin: Style.space(4)
      anchors.verticalCenter: parent.verticalCenter
      height: commandText.implicitHeight + Style.space(8)
      radius: Style.cornerRadius
      color: chipMouse.containsMouse
        ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.14)
        : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.07)

      Behavior on color { ColorAnimation { duration: 60 } }

      Text {
        id: commandText
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Style.space(6)
        anchors.rightMargin: Style.space(6)
        text: String(root.action.command || "")
        textFormat: Text.PlainText
        wrapMode: Text.WrapAnywhere
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        color: chipMouse.containsMouse ? root.accent : root.foreground
      }

      MouseArea {
        id: chipMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.runSignIn(String(root.failure.id || ""))
      }

      PanelToolTip {
        visible: chipMouse.containsMouse
        text: "Sign in in a terminal"
        fontFamily: root.fontFamily
      }
    }

    Row {
      id: actions
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(2)

      PanelActionButton {
        iconText: root.iconRun
        tooltipText: "Sign in in a terminal"
        foreground: root.foreground
        hoverColor: root.accent
        fontFamily: root.fontFamily
        fontSize: Style.font.iconSmall
        onClicked: root.runSignIn(String(root.failure.id || ""))
      }

      PanelActionButton {
        iconText: root.copied ? root.iconCopied : root.iconCopy
        tooltipText: root.copied ? "Copied" : "Copy command"
        foreground: root.foreground
        hoverColor: root.accent
        fontFamily: root.fontFamily
        fontSize: Style.font.iconSmall
        onClicked: {
          root.copyCommand(String(root.action.command || ""))
          root.copied = true
          copiedTimer.restart()
        }
      }
    }
  }

  Text {
    visible: root.isSetup
    text: "Open setup guide"
    textFormat: Text.PlainText
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.underline: setupMouse.containsMouse
    color: setupMouse.containsMouse ? root.accent : root.foreground

    MouseArea {
      id: setupMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.openUrl(String(root.action.url || ""))
    }
  }
}
