import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// You've Got Mail: unread only. Click a row to open that message.
//
// Data comes from `bin/you-got-mail`. The script talks to a provider; this
// file only draws the pile and opens the URL the provider already built.
// No token is handled here.
//
// Every string below the header comes from a mail someone else wrote, so each
// Text carries `textFormat: Text.PlainText`.
Panel {
  id: root

  moduleName: "bvisagie.you-got-mail"
  ipcTarget: "bvisagie.you-got-mail"

  readonly property string script:
    Qt.resolvedUrl("bin/you-got-mail").toString().replace(/^file:\/\//, "")

  readonly property string iconExternal: "\uF08E"
  readonly property string iconPrev: "\uF053"
  readonly property string iconNext: "\uF054"

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color accent: Color.accent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  property var messages: []
  property int unread: 0
  property string email: ""
  property string searchUrl: ""
  property bool reachable: true
  property string errorText: ""
  property string pendingId: ""
  property int cursor: -1

  property string pageToken: ""
  property var pageStack: []
  property string nextPage: ""
  property int accountCount: 0
  readonly property bool hasPrev: pageStack.length > 0
  readonly property bool hasNext: nextPage !== ""

  property double now: 0

  readonly property int badgeCount: unread
  readonly property bool hasUnread: unread > 0

  readonly property int badgeWidth: badgeCount > 0
    ? Math.max(Style.space(12), String(badgeCount).length * Style.space(6) + Style.space(8))
    : 0
  readonly property int barContentWidth: Style.bar.iconFont + badgeWidth + Style.space(5)
  readonly property int barSlot: barContentWidth + Style.space(10)

  implicitWidth: bar && bar.vertical ? (bar ? bar.barSize : Style.bar.sizeHorizontal) : barSlot
  implicitHeight: bar && bar.vertical ? barSlot : (bar ? bar.barSize : Style.bar.sizeHorizontal)

  function validToken(t) {
    return /^[A-Za-z0-9_-]{1,512}$/.test(String(t))
  }

  function validId(id) {
    return /^[A-Za-z0-9][A-Za-z0-9._-]{0,32}:[A-Za-z0-9_-]{1,512}$/.test(String(id))
  }

  function validUrl(url) {
    return /^https:\/\/[A-Za-z0-9.-]+(?::\d+)?(?:[/?#][^\s]*)?$/.test(String(url))
  }

  function refresh() {
    if (listProc.running) return
    var argv = [root.script, "list"]
    if (pageToken !== "" && validToken(pageToken)) argv.push("--page", pageToken)
    listProc.command = argv
    listProc.running = true
  }

  function goNextPage() {
    if (!hasNext || listProc.running) return
    var stack = pageStack.slice()
    stack.push(pageToken)
    pageStack = stack
    pageToken = nextPage
    cursor = -1
    refresh()
  }

  function goPrevPage() {
    if (!hasPrev || listProc.running) return
    var stack = pageStack.slice()
    pageToken = stack.pop()
    pageStack = stack
    cursor = -1
    refresh()
  }

  function firstPage() {
    pageToken = ""
    pageStack = []
    cursor = -1
  }

  function titleText() {
    if (root.unread === 1) return "1 unread"
    return root.unread + " unread"
  }

  function dismissLocal(id) {
    var next = []
    for (var i = 0; i < messages.length; i++) {
      if (messages[i].id !== id) next.push(messages[i])
    }
    messages = next
    if (unread > 0) unread -= 1
    if (cursor > messages.length - 1) cursor = messages.length - 1
  }

  function openMessage(message) {
    if (!message || !validId(message.id)) return
    var url = message.url || ""
    if (url !== "" && validUrl(url))
      Quickshell.execDetached(["xdg-open", url])
    dismissLocal(message.id)
    pendingId = message.id
    readProc.command = [root.script, "read", message.id]
    readProc.running = true
    close()
  }

  function openSearch() {
    var url = root.searchUrl
    if (!validUrl(url)) return
    Quickshell.execDetached(["xdg-open", url])
    close()
  }

  function moveCursor(delta) {
    if (messages.length === 0) return
    var next = cursor + delta
    if (next < 0) next = 0
    if (next > messages.length - 1) next = messages.length - 1
    cursor = next
    list.positionViewAtIndex(next, ListView.Contain)
  }

  function activateCursor() {
    if (cursor < 0 || cursor >= messages.length) return
    openMessage(messages[cursor])
  }

  function ageLabel(ts) {
    if (!ts || ts <= 0) return ""
    var seconds = Math.max(0, root.now - ts)
    if (seconds < 60) return "now"
    if (seconds < 3600) return Math.floor(seconds / 60) + "m"
    if (seconds < 86400) return Math.floor(seconds / 3600) + "h"
    if (seconds < 604800) return Math.floor(seconds / 86400) + "d"
    if (seconds < 2592000) return Math.floor(seconds / 604800) + "w"
    return Qt.formatDate(new Date(ts * 1000), "d MMM")
  }

  function oneLine(value) {
    return String(value || "").replace(/\s+/g, " ").trim()
  }

  function applyPayload(text) {
    try {
      var data = JSON.parse(text)
      reachable = data.ok === true
      errorText = data.error || ""
      if (!reachable) return
      messages = data.messages || []
      unread = data.unread || 0
      email = data.email || ""
      searchUrl = data.searchUrl || ""
      accountCount = data.accountCount || 0
      nextPage = validToken(data.nextPage) ? data.nextPage : ""
      if (cursor > messages.length - 1) cursor = messages.length - 1
    } catch (e) {
      reachable = false
      errorText = "unexpected output from you-got-mail"
    }
  }

  onOpenedChanged: {
    if (opened) {
      now = Date.now() / 1000
      refresh()
    } else {
      cursor = -1
      firstPage()
    }
  }

  Component.onCompleted: now = Date.now() / 1000

  Process {
    id: listProc
    stdout: StdioCollector {
      onStreamFinished: root.applyPayload(text)
    }
  }

  Process {
    id: readProc
    onExited: function(exitCode) {
      root.pendingId = ""
      root.refresh()
    }
  }

  Timer {
    interval: 60000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: {
      root.now = Date.now() / 1000
      root.refresh()
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    opacity: root.reachable ? 1 : 0.5
    slotSize: root.barSlot
    opticalSize: root.barContentWidth
    tooltipText: ""

    iconComponent: Component {
      Item {
        Row {
          anchors.centerIn: parent
          spacing: Style.space(5)

          MailSlotIcon {
            anchors.verticalCenter: parent.verticalCenter
            iconSize: Style.bar.iconCanvas
            color: root.opened ? root.accent : root.foreground
            flagColor: (root.hasUnread && root.reachable) ? root.accent : root.foreground
            hasMail: root.hasUnread && root.reachable
          }

          Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.reachable && root.badgeCount > 0
            height: Style.space(12)
            width: root.badgeWidth
            radius: height / 2
            color: root.accent

            Text {
              anchors.centerIn: parent
              text: root.badgeCount
              textFormat: Text.PlainText
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              renderType: Text.NativeRendering
              color: Color.background
            }
          }
        }
      }
    }

    onPressed: function(b) {
      if (b === Qt.RightButton) {
        root.openSearch()
      } else if (b === Qt.MiddleButton) {
        root.refresh()
      } else {
        root.toggle()
      }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onMoveRequested: function(dx, dy) { if (dy !== 0) root.moveCursor(dy) }
      onActivateRequested: root.activateCursor()
      onTextKey: function(t) {
        var onCursor = root.cursor >= 0 && root.cursor < root.messages.length
        if (t === "o" && onCursor)
          root.openMessage(root.messages[root.cursor])
        else if (t === "n")
          root.goNextPage()
        else if (t === "p")
          root.goPrevPage()
      }

      Column {
        id: content
        anchors.fill: parent
        spacing: Style.space(6)

        Item {
          width: parent.width
          height: Math.max(heading.implicitHeight, openMailButton.height)

          Column {
            id: heading
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: headerActions.left
            anchors.rightMargin: Style.space(8)
            spacing: Style.space(1)

            PanelSectionHeader {
              width: parent.width
              text: root.titleText()
              textFormat: Text.PlainText
              elide: Text.ElideRight
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Text {
              width: parent.width
              visible: root.email !== ""
              text: root.email
              textFormat: Text.PlainText
              elide: Text.ElideRight
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              color: Qt.darker(root.foreground, 1.6)
            }
          }

          Row {
            id: headerActions
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter

            PanelActionButton {
              id: openMailButton
              iconText: root.iconExternal
              tooltipText: "Open unread in browser"
              foreground: root.foreground
              hoverColor: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.iconSmall
              onClicked: root.openSearch()
            }
          }
        }

        PanelSeparator { width: parent.width }

        Item {
          width: parent.width
          height: root.reachable ? 0 : staleWarning.implicitHeight + Style.space(6)
          visible: !root.reachable

          Text {
            id: staleWarning
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            text: root.errorText !== ""
              ? root.errorText
              : "Could not reach mail. Showing the last list."
            textFormat: Text.PlainText
            elide: Text.ElideRight
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            color: bar ? bar.urgent : Color.urgent
          }
        }

        ListView {
          id: list
          width: parent.width
          visible: root.messages.length > 0
          clip: true
          model: root.messages
          spacing: Style.space(1)
          boundsBehavior: Flickable.StopAtBounds
          flickableDirection: Flickable.VerticalFlick
          interactive: contentHeight > height
          ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

          readonly property int cap: {
            var chrome = Style.space(70)
            if (root.hasPrev || root.hasNext) chrome += Style.space(38)
            if (!root.reachable) chrome += Style.space(24)
            return Math.max(Style.space(200),
                            panel.availableCardHeight - panel.verticalContentInset - chrome)
          }
          height: Math.min(contentHeight, cap)

          delegate: Rectangle {
            id: row
            required property var modelData
            required property int index

            readonly property bool active: root.cursor === row.index || rowMouse.containsMouse

            width: list.width - (list.interactive ? Style.space(10) : 0)
            height: rowContent.implicitHeight + Style.space(10)
            radius: Style.cornerRadius
            opacity: root.pendingId === modelData.id ? 0.4 : 1
            color: active
              ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.08)
              : "transparent"

            Behavior on color { ColorAnimation { duration: 80 } }

            MouseArea {
              id: rowMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onContainsMouseChanged: if (containsMouse) root.cursor = row.index
              onClicked: root.openMessage(row.modelData)
            }

            Column {
              id: rowContent
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.leftMargin: Style.space(6)
              anchors.rightMargin: Style.space(6)
              spacing: Style.space(2)

              Item {
                width: parent.width
                height: subject.implicitHeight

                Row {
                  id: line
                  anchors.left: parent.left
                  anchors.right: age.left
                  anchors.rightMargin: Style.space(6)
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(5)

                  Row {
                    id: chips
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(3)
                    visible: {
                      var labs = row.modelData.labels || []
                      var acc = row.modelData.account || ""
                      return labs.length > 0 || (root.accountCount > 1 && acc !== "")
                    }

                    Repeater {
                      model: {
                        var labs = (row.modelData.labels || []).slice()
                        var acc = row.modelData.account || ""
                        if (acc && root.accountCount > 1) labs.unshift(acc)
                        return labs.slice(0, 2)
                      }

                      Rectangle {
                        required property string modelData
                        anchors.verticalCenter: parent.verticalCenter
                        height: chipText.implicitHeight + Style.space(3)
                        width: chipText.implicitWidth + Style.space(8)
                        radius: Style.space(3)
                        color: Qt.rgba(root.foreground.r, root.foreground.g,
                                       root.foreground.b, 0.14)

                        Text {
                          id: chipText
                          anchors.centerIn: parent
                          text: parent.modelData
                          textFormat: Text.PlainText
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.caption
                          color: Qt.darker(root.foreground, 1.35)
                        }
                      }
                    }
                  }

                  Text {
                    id: subject
                    anchors.verticalCenter: parent.verticalCenter
                    width: line.width - (chips.visible ? chips.width + line.spacing : 0)
                    text: root.oneLine(row.modelData.subject)
                    textFormat: Text.PlainText
                    wrapMode: Text.NoWrap
                    maximumLineCount: 1
                    elide: Text.ElideRight
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                    color: root.foreground
                  }
                }

                Text {
                  id: age
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  text: root.ageLabel(row.modelData.ts)
                  textFormat: Text.PlainText
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  color: Qt.darker(root.foreground, 1.7)
                }
              }

              Row {
                width: parent.width
                spacing: 0

                Text {
                  id: fromLabel
                  text: row.modelData.from || ""
                  textFormat: Text.PlainText
                  elide: Text.ElideRight
                  width: Math.min(implicitWidth, parent.width * 0.5)
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                  color: Qt.darker(root.foreground, 1.15)
                }

                Text {
                  text: {
                    var body = root.oneLine(row.modelData.snippet)
                    if (body === "") return ""
                    return (fromLabel.text !== "" ? "  -  " : "") + body
                  }
                  textFormat: Text.PlainText
                  wrapMode: Text.NoWrap
                  maximumLineCount: 1
                  elide: Text.ElideRight
                  width: parent.width - fromLabel.width
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  color: Qt.darker(root.foreground, 1.7)
                }
              }
            }
          }
        }

        Item {
          width: parent.width
          height: (root.hasPrev || root.hasNext) ? pagerRow.implicitHeight + Style.space(8) : 0
          visible: root.hasPrev || root.hasNext

          Row {
            id: pagerRow
            anchors.centerIn: parent
            spacing: Style.space(10)

            PanelActionButton {
              iconText: root.iconPrev
              tooltipText: "Previous page"
              enabled: root.hasPrev
              opacity: enabled ? 1 : 0.3
              foreground: root.foreground
              hoverColor: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.iconSmall
              onClicked: root.goPrevPage()
            }

            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "page " + (root.pageStack.length + 1)
              textFormat: Text.PlainText
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              color: Qt.darker(root.foreground, 1.7)
            }

            PanelActionButton {
              iconText: root.iconNext
              tooltipText: "Next page"
              enabled: root.hasNext
              opacity: enabled ? 1 : 0.3
              foreground: root.foreground
              hoverColor: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.iconSmall
              onClicked: root.goNextPage()
            }
          }
        }

        Item {
          width: parent.width
          height: root.messages.length === 0 ? Style.space(60) : 0
          visible: root.messages.length === 0

          Text {
            anchors.centerIn: parent
            width: parent.width - Style.space(20)
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: root.reachable
              ? "You're all caught up."
              : (root.errorText !== "" ? root.errorText : "Mail unreachable")
            textFormat: Text.PlainText
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            color: root.foreground
            opacity: 0.6
          }
        }
      }
    }
  }
}
