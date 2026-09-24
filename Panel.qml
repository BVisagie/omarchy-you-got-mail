import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "MailState.js" as MailState

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
  readonly property string iconMarkAll: "\uF2B6"
  readonly property string iconConfirm: "\uF00C"
  readonly property string iconPrev: "\uF053"
  readonly property string iconNext: "\uF054"
  readonly property string iconSoundOn: "\uF028"
  readonly property string iconSoundOff: "\uF026"

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color accent: Color.accent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  property var messages: []
  property int unread: 0
  property string email: ""
  property string searchUrl: ""
  property var inboxes: []
  // Failed accounts, each with a short message and maybe a fix action.
  property var failures: []
  property bool reachable: true
  property bool needsSignIn: false
  property string errorText: ""
  property string warningText: ""
  property string pendingId: ""
  property var readQueue: []
  property var dismissedIds: ({})
  readonly property bool readBusy: pendingId !== "" || readQueue.length > 0
  property int mailboxRevision: 0
  property int listRevision: 0
  property string listPage: ""
  property string readOutput: ""
  property bool readOutputReady: false
  property bool readExited: false
  property bool readStarted: false
  property int readExitCode: 0
  property bool markAllArmed: false
  property bool markAllBusy: false
  property bool refreshPending: false
  property bool reconciling: false
  property string actionWarning: ""
  property int cursor: -1

  property string pageToken: ""
  property var pageStack: []
  property string nextPage: ""
  property int accountCount: 0
  readonly property bool hasPrev: pageStack.length > 0
  readonly property bool hasNext: nextPage !== ""

  property double now: 0
  property string auxiliaryView: ""
  property int menuCursor: -1
  property string savedMessageId: ""
  property var accountChecks: ({})
  property double allCheckedAt: 0
  property string accountSignature: ""
  // New-mail detection state from MailState.arrivals; null until the first page 1.
  property var arrivalState: null
  readonly property var accountMenu: MailState.accountEntries(inboxes, accountChecks, now)
  readonly property var shortcutHelp: MailState.shortcuts()

  function showView(view) {
    cancelMarkAllConfirm()
    if (auxiliaryView === view) view = ""
    if (auxiliaryView === "" && cursor >= 0 && cursor < messages.length)
      savedMessageId = messages[cursor].id
    auxiliaryView = view
    if (view === "accounts") {
      menuCursor = MailState.moveMenu(accountMenu, -1, 1)
    } else if (view === "") {
      var found = messages.findIndex(function(message) { return message.id === root.savedMessageId })
      if (found >= 0) cursor = found
    }
    auxiliaryMenu.contentY = 0
    keyCatcher.forceActiveFocus()
  }

  function addAccount() {
    Util.execArgv(["omarchy-launch-floating-terminal-with-presentation",
                   Util.shellQuote(root.script) + " accounts add"])
    close()
  }

  function activateMenu(entry) {
    if (!entry || !entry.enabled) return
    if (entry.kind === "inbox") {
      if (openBrowser(entry.url)) close()
    } else if (entry.kind === "add") addAccount()
    else if (entry.kind === "guide") {
      if (openBrowser("https://github.com/BVisagie/omarchy-you-got-mail/blob/main/docs/ACCOUNTS.md")) close()
    }
  }

  function moveSelection(delta) {
    if (auxiliaryView === "accounts") {
      menuCursor = MailState.moveMenu(accountMenu, menuCursor, delta)
      auxiliaryMenu.revealCursor()
    } else if (auxiliaryView === "help") {
      auxiliaryMenu.contentY = Math.max(0, Math.min(
        Math.max(0, auxiliaryMenu.contentHeight - auxiliaryMenu.height),
        auxiliaryMenu.contentY + delta * Style.space(40)))
    } else moveCursor(delta)
  }

  function activateSelection() {
    if (auxiliaryView === "accounts") activateMenu(accountMenu[menuCursor])
    else if (auxiliaryView === "") activateCursor()
  }

  function closeRequested() {
    if (auxiliaryView !== "") showView("")
    else if (markAllArmed) cancelMarkAllConfirm()
    else close()
  }

  function handleTextKey(t) {
    if (t === "?") { showView("help"); return }
    if (t === "m") { showView("accounts"); return }
    if (t === "s") { toggleSound(); return }
    if (t === "r") { refresh(); return }
    if (auxiliaryView !== "") {
      if (t === "o") activateSelection()
      return
    }
    var onCursor = root.cursor >= 0 && root.cursor < root.messages.length
    if (t === "o" && onCursor)
      root.openMessage(root.messages[root.cursor])
    else if (t === "i" && root.hasOpenableInbox)
      root.openSearch()
    else if (t === "a")
      root.markCursorRead()
    else if (t === "A")
      root.requestMarkAll()
    else if (t === "n")
      root.goNextPage()
    else if (t === "p")
      root.goPrevPage()
  }

  function freshnessText() {
    return allCheckedAt > 0
      ? "Last full check: " + MailState.checkLabel(allCheckedAt, now).replace(/^Checked /, "")
      : "No successful check of all accounts yet"
  }

  function updateAccounts(reported) {
    var menuKey = (accountMenu[menuCursor] || {}).key
    var signature = reported.map(function(box) { return box.id || "" }).sort().join(":")
    if (signature !== accountSignature) allCheckedAt = 0
    accountSignature = signature
    var result = MailState.updateChecks(accountChecks, reported)
    accountChecks = result.checks
    if (result.allCheckedAt > 0) allCheckedAt = result.allCheckedAt
    inboxes = reported
    if (auxiliaryView === "accounts") {
      var found = accountMenu.findIndex(function(entry) { return entry.key === menuKey && entry.enabled })
      menuCursor = found >= 0 ? found : MailState.moveMenu(accountMenu, -1, 1)
    }
  }

  function staleAccounts(message) {
    updateAccounts(inboxes.map(function(box) {
      return Object.assign({}, box, {ok: false, unread: 0, searchUrl: "", message: message})
    }))
  }

  readonly property int badgeCount: unread
  readonly property bool hasUnread: unread > 0
  readonly property bool hasAlert: !reachable || warningText !== "" || needsSignIn || actionWarning !== ""
  // A failed refresh keeps the last unread count; don't let it hide the alert.
  readonly property bool showAlertBadge: hasAlert && (unread === 0 || !reachable)
  readonly property color alertColor: bar ? bar.urgent : Color.urgent

  readonly property int badgeWidth: (badgeCount > 0 || showAlertBadge)
    ? Math.max(Style.space(12), String(showAlertBadge ? "!" : badgeCount).length * Style.space(6) + Style.space(8))
    : 0
  readonly property int barContentWidth: Style.bar.iconFont + badgeWidth + Style.space(5)
  readonly property int barSlot: barContentWidth + Style.space(10)

  implicitWidth: bar && bar.vertical ? (bar ? bar.barSize : Style.bar.sizeHorizontal) : barSlot
  implicitHeight: bar && bar.vertical ? barSlot : (bar ? bar.barSize : Style.bar.sizeHorizontal)

  function validToken(t) {
    return typeof t === "string" && /^[A-Za-z0-9_-]{1,512}$/.test(t)
  }

  function validId(id) {
    return /^[A-Za-z0-9][A-Za-z0-9._-]{0,32}:[A-Za-z0-9_-]{1,512}$/.test(String(id))
  }

  function validUrl(url) {
    return MailState.validUrl(url)
  }

  function validAccountId(id) {
    return /^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/.test(String(id))
  }

  readonly property bool hasSignInAction: {
    for (var i = 0; i < failures.length; i++) {
      var action = (failures[i] || {}).action || {}
      if (action.kind === "signin") return true
    }
    return false
  }

  // `accounts login` needs a TTY, so it runs in a floating terminal. The
  // launcher hands its args to `bash -c`: the script path is quoted and the
  // id must match ACCOUNT_ID_RE, so nothing from a payload reaches the shell.
  function runSignIn(id) {
    if (!validAccountId(id)) return
    Util.execArgv(["omarchy-launch-floating-terminal-with-presentation",
                   Util.shellQuote(root.script) + " accounts login " + id])
    close()
  }

  function copyCommand(text) {
    var value = String(text || "")
    if (value === "") return
    Util.execArgv(["wl-copy", "--", value])
  }

  function openBrowser(url) {
    if (!validUrl(url)) return false
    // The bar process is not a login shell; bare xdg-open is silent.
    // omarchy-launch-browser runs the default browser via uwsm.
    Util.execArgv(["omarchy-launch-browser", url])
    return true
  }

  // One call per refresh with every new ID; `chime` dedupes across widget
  // copies and applies the cooldown and Do Not Disturb.
  function playChime(ids) {
    var valid = ids.filter(function(id) { return validId(id) })
    if (!root.soundEnabled || valid.length === 0) return
    var argv = [root.script, "chime", "--cooldown", String(root.soundCooldownSec),
                "--volume", String(root.soundVolume)]
    if (root.soundFile !== "") argv.push("--file", root.soundFile)
    Util.execArgv(argv.concat(["--"], valid))
  }

  // Applied locally first so the panel redraws at once, then written to this
  // widget's shell.json entry, which comes back to every copy through the bar.
  // Without the shell API the change lasts for this session only.
  function persistSettings(values) {
    var entry = { id: root.moduleName }
    for (var existing in root.settings) if (existing !== "id") entry[existing] = root.settings[existing]
    for (var key in values) entry[key] = values[key]
    root.settings = entry
    if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
  }

  // Turning the sound on plays it once so you know what you will hear. No `--`
  // makes it the manual test: Do Not Disturb applies, the cooldown does not.
  function toggleSound() {
    var next = !root.soundEnabled
    persistSettings({ soundEnabled: next })
    if (!next) return
    var argv = [root.script, "chime", "--volume", String(root.soundVolume)]
    if (root.soundFile !== "") argv.push("--file", root.soundFile)
    Util.execArgv(argv)
  }

  readonly property int pageSize: {
    var n = parseInt(setting("max", 25), 10)
    if (!(n > 0)) n = 25
    return Math.max(1, Math.min(50, n))
  }
  readonly property int refreshMs: {
    var n = parseInt(setting("refreshIntervalSec", 60), 10)
    if (!(n > 0)) n = 60
    return Math.max(15, Math.min(3600, n)) * 1000
  }
  // shell.json is edited by hand: accept true, "true" and 1.
  readonly property bool soundEnabled: {
    var value = setting("soundEnabled", false)
    return value === true || value === "true" || value === 1
  }
  readonly property int soundCooldownSec: {
    var n = parseInt(setting("soundCooldownSec", 60), 10)
    if (!(n >= 0)) n = 60
    return Math.max(0, Math.min(3600, n))
  }
  readonly property int soundVolume: {
    var n = parseInt(setting("soundVolume", 100), 10)
    if (!(n >= 0)) n = 100
    return Math.max(0, Math.min(100, n))
  }
  readonly property string soundFile: String(setting("soundFile", "") || "").trim()

  function refresh() {
    if (root.markAllBusy) return
    if (root.readBusy) {
      root.refreshPending = true
      return
    }
    if (listProc.running) {
      root.refreshPending = true
      return
    }
    root.refreshPending = false
    var argv = [root.script, "list", "--limit", String(root.pageSize)]
    if (pageToken !== "" && validToken(pageToken)) argv.push("--page", pageToken)
    root.listRevision = root.mailboxRevision
    root.listPage = root.pageToken
    listProc.command = argv
    listProc.running = true
  }

  function goNextPage() {
    if (!hasNext || listProc.running || root.readBusy || root.markAllBusy || root.reconciling) return
    var stack = pageStack.slice()
    stack.push(pageToken)
    pageStack = stack
    pageToken = nextPage
    cursor = -1
    refresh()
  }

  function goPrevPage() {
    if (!hasPrev || listProc.running || root.readBusy || root.markAllBusy || root.reconciling) return
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
    if (root.needsSignIn && (root.unread === 0 || !root.reachable)) return "Sign-in needed"
    if (root.unread === 1) return "1 unread"
    return root.unread + " unread"
  }

  function countLabel() {
    if (root.unread === 1) return "1 unread"
    return root.unread + " unread"
  }

  function mailTooltip() {
    if (root.actionWarning !== "") return root.actionWarning
    if (!root.reachable)
      return root.errorText !== "" ? root.errorText : "Mail unreachable"
    var warn = root.warningText
    if (root.hasUnread)
      return warn !== "" ? (countLabel() + " · " + warn) : countLabel()
    if (warn !== "") return warn
    return "No unread mail"
  }

  function barTooltip() {
    var parts = [mailTooltip(), freshnessText()]
    for (var i = 0; i < inboxes.length; i++) {
      var box = inboxes[i]
      if (box.ok === false)
        parts.push((box.account || box.id) + ": " + MailState.checkLabel(accountChecks[box.id], now))
    }
    return parts.join("\n")
  }

  function dismissLocal(id) {
    var result = MailState.dismiss(messages, unread, dismissedIds, id)
    if (!result) return false
    root.mailboxRevision += 1
    messages = result.messages
    unread = result.unread
    dismissedIds = result.dismissed
    if (cursor > messages.length - 1) cursor = messages.length - 1
    return true
  }

  function showActionWarning(message) {
    var notice = String(message || "")
    if (root.actionWarning === notice) return
    root.actionWarning = notice
  }

  function finishRead() {
    // Process exit and stdout completion may arrive in either order.
    if (!root.readExited || !root.readOutputReady || root.pendingId === "") return
    var id = root.pendingId
    var saved = root.dismissedIds[id]
    var error = MailState.readError(root.readOutput, root.readExitCode)
    var result = MailState.settle(messages, unread, dismissedIds, id, error)
    root.mailboxRevision += 1
    messages = result.messages
    unread = result.unread
    dismissedIds = result.dismissed
    if (error) {
      var accountId = id.split(":")[0]
      var account = saved ? saved.message.account : accountId
      showActionWarning(MailState.readNotice(error, accountId, account))
    }
    root.pendingId = ""
    root.readExited = false
    root.readOutputReady = false
    if (cursor < 0 && messages.length > 0) cursor = 0
    if (root.readQueue.length > 0) root.pumpRead()
    else root.refresh()
  }

  function readStartFailed(id) {
    // Quickshell emits runningChanged, but no exited signal, on exec failure.
    // The captured ID prevents a deferred callback from settling the next read.
    if (root.pendingId !== id || root.readStarted || readProc.running) return
    root.readOutputReady = true
    root.readExited = true
    root.readExitCode = -1
    root.finishRead()
  }

  function openableInboxUrls() {
    var urls = []
    var seen = {}
    var list = root.inboxes || []
    if (list.length === 0 && validUrl(root.searchUrl))
      list = [{ unread: root.unread, searchUrl: root.searchUrl }]
    for (var i = 0; i < list.length; i++) {
      var box = list[i] || {}
      var n = parseInt(box.unread, 10)
      if (!(n > 0)) continue
      var url = box.searchUrl || ""
      if (!validUrl(url) || seen[url]) continue
      seen[url] = true
      urls.push(url)
    }
    return urls
  }

  readonly property bool hasOpenableInbox: openableInboxUrls().length > 0

  function enqueueRead(id) {
    var q = root.readQueue.slice()
    q.push(id)
    root.readQueue = q
    root.pumpRead()
  }

  function pumpRead() {
    if (readProc.running || root.readQueue.length === 0) return
    var q = root.readQueue.slice()
    var id = q.shift()
    root.readQueue = q
    root.pendingId = id
    root.readOutput = ""
    root.readOutputReady = false
    root.readExited = false
    root.readStarted = false
    root.readExitCode = 0
    readProc.command = [root.script, "read", id]
    readProc.running = true
  }

  function openMessage(message) {
    if (root.markAllBusy || root.reconciling) return
    if (!message || !validId(message.id)) return
    var url = message.url || ""
    if (url !== "") {
      if (!openBrowser(url)) return
    }
    if (!dismissLocal(message.id)) return
    enqueueRead(message.id)
    close()
  }

  function markCursorRead() {
    if (root.markAllBusy || root.reconciling) return
    if (cursor < 0 || cursor >= messages.length) return
    var message = messages[cursor]
    if (!message || !validId(message.id)) return
    cancelMarkAllConfirm()
    if (!dismissLocal(message.id)) return
    enqueueRead(message.id)
  }

  function openSearch() {
    var urls = openableInboxUrls()
    if (urls.length === 0) return
    for (var i = 0; i < urls.length; i++)
      openBrowser(urls[i])
    close()
  }

  function cancelMarkAllConfirm() {
    markAllArmed = false
    if (markAllArmTimer.running) markAllArmTimer.stop()
  }

  function requestMarkAll() {
    if (!root.hasUnread || !root.reachable || listProc.running || root.readBusy
        || root.markAllBusy || root.reconciling) return
    if (!root.markAllArmed) {
      root.markAllArmed = true
      markAllArmTimer.restart()
      return
    }
    root.cancelMarkAllConfirm()
    root.markAllBusy = true
    readAllProc.command = [root.script, "read-all"]
    readAllProc.running = true
  }

  function applyReadAllPayload(text) {
    root.markAllBusy = false
    root.cancelMarkAllConfirm()
    root.dismissedIds = ({})
    try {
      var data = JSON.parse(text)
      var marked = parseInt(data.marked, 10)
      if (!(marked > 0)) marked = 0
      if (data.ok === true) {
        showActionWarning(data.warning)
        root.reconciling = true
        firstPage()
        refresh()
        return
      }
      showActionWarning(data.error || "could not mark all as read")
      if (marked > 0) {
        root.reconciling = true
        firstPage()
        refresh()
      }
    } catch (e) {
      showActionWarning("unexpected output from you-got-mail")
    }
  }

  function moveCursor(delta) {
    if (root.reconciling || messages.length === 0) return
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
    if (!MailState.acceptsList(root.listRevision, root.mailboxRevision, root.listPage, root.pageToken)) {
      root.refreshPending = true
      return
    }
    try {
      var data = JSON.parse(text)
      if (!root.refreshPending) root.reconciling = false
      reachable = data.ok === true
      errorText = data.error || ""
      warningText = reachable ? (data.warning || "") : ""
      needsSignIn = data.needsSignIn === true
      var failed = []
      var reported = data.inboxes || []
      root.now = Date.now() / 1000
      updateAccounts(reported)
      accountCount = data.accountCount || reported.length
      for (var f = 0; f < reported.length; f++) {
        if (reported[f] && reported[f].ok === false) failed.push(reported[f])
      }
      failures = failed
      if (!needsSignIn) {
        var boxes = data.inboxes || []
        for (var b = 0; b < boxes.length; b++) {
          if (boxes[b] && boxes[b].needsSignIn) {
            needsSignIn = true
            break
          }
        }
      }
      // Keep actionWarning across this refresh: a write can fail while list still works.
      if (!reachable) return
      var incoming = data.messages || []
      var kept = []
      var dropped = 0
      for (var i = 0; i < incoming.length; i++) {
        var row = incoming[i]
        if (row && root.dismissedIds[row.id]) dropped += 1
        else kept.push(row)
      }
      var selectedId = cursor >= 0 && cursor < messages.length ? messages[cursor].id : ""
      messages = kept
      var selectedIndex = messages.findIndex(function(message) { return message.id === selectedId })
      if (selectedIndex >= 0) cursor = selectedIndex
      unread = Math.max(0, (data.unread || 0) - dropped)
      email = data.email || ""
      searchUrl = data.searchUrl || ""
      nextPage = validToken(data.nextPage) ? data.nextPage : ""
      if (cursor > messages.length - 1) cursor = messages.length - 1
      if (cursor < 0 && messages.length > 0) cursor = 0
      // Only page 1 shows what is new; paging never chimes or moves the state.
      if (root.listPage === "") {
        var arrived = MailState.arrivals(root.arrivalState, reported, kept,
                                         validToken(data.nextPage), root.now)
        root.arrivalState = arrived.state
        playChime(arrived.fresh)
      }
    } catch (e) {
      if (!root.refreshPending) root.reconciling = false
      reachable = false
      failures = []
      errorText = "unexpected output from you-got-mail"
      staleAccounts(errorText)
    }
  }

  onOpenedChanged: {
    if (opened) {
      now = Date.now() / 1000
      refresh()
    } else {
      auxiliaryView = ""
      menuCursor = -1
      cursor = -1
      firstPage()
      cancelMarkAllConfirm()
    }
  }

  Component.onCompleted: now = Date.now() / 1000

  Process {
    id: listProc
    stdout: StdioCollector {
      onStreamFinished: root.applyPayload(text)
    }
    onExited: if (root.refreshPending) root.refresh()
  }

  Process {
    id: readProc
    onStarted: root.readStarted = true
    onRunningChanged: if (!running && root.pendingId !== "") {
      var id = root.pendingId
      Qt.callLater(function() { root.readStartFailed(id) })
    }
    stdout: StdioCollector {
      onStreamFinished: {
        root.readOutput = text
        root.readOutputReady = true
        root.finishRead()
      }
    }
    onExited: function(exitCode, exitStatus) {
      root.readExitCode = exitStatus === 0 ? exitCode : -1
      root.readExited = true
      root.finishRead()
    }
  }

  Process {
    id: readAllProc
    stdout: StdioCollector {
      onStreamFinished: root.applyReadAllPayload(text)
    }
  }

  Timer {
    interval: root.refreshMs
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: {
      root.now = Date.now() / 1000
      root.refresh()
    }
  }

  Timer {
    interval: 15000
    running: true
    repeat: true
    onTriggered: root.now = Date.now() / 1000
  }

  Timer {
    id: markAllArmTimer
    interval: 4000
    repeat: false
    onTriggered: root.markAllArmed = false
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    opacity: root.hasAlert ? 0.5 : 1
    slotSize: root.barSlot
    opticalSize: root.barContentWidth
    tooltipText: root.barTooltip()

    iconComponent: Component {
      Item {
        Row {
          anchors.centerIn: parent
          spacing: Style.space(5)

          MailSlotIcon {
            anchors.verticalCenter: parent.verticalCenter
            iconSize: Style.bar.iconCanvas
            color: button.foreground
            flagColor: button.foreground
            hasMail: root.hasUnread && root.reachable
          }

          Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.badgeCount > 0 || root.showAlertBadge
            height: Style.space(12)
            width: root.badgeWidth
            radius: height / 2
            color: root.showAlertBadge
              ? Qt.rgba(root.alertColor.r, root.alertColor.g, root.alertColor.b, 0.18)
              : Qt.rgba(button.foreground.r, button.foreground.g,
                        button.foreground.b, 0.14)

            Text {
              anchors.centerIn: parent
              text: root.showAlertBadge ? "!" : root.badgeCount
              textFormat: Text.PlainText
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              renderType: Text.NativeRendering
              color: root.showAlertBadge ? root.alertColor : button.foreground
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
      onCloseRequested: root.closeRequested()
      onMoveRequested: function(dx, dy) { if (dy !== 0) root.moveSelection(dy) }
      onActivateRequested: root.activateSelection()
      onDeleteRequested: root.actionWarning = ""
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) { root.handleTextKey(t) }

      Column {
        id: content
        anchors.fill: parent
        spacing: Style.space(6)

        Item {
          id: panelHeading
          width: parent.width
          height: Math.max(heading.implicitHeight, headerActions.implicitHeight)

          Column {
            id: heading
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: headerActions.left
            anchors.rightMargin: Style.space(8)
            spacing: Style.space(1)

            PanelSectionHeader {
              width: parent.width
              text: root.auxiliaryView === "help" ? "Shortcuts"
                : (root.auxiliaryView === "accounts" ? "Accounts" : root.titleText())
              textFormat: Text.PlainText
              elide: Text.ElideRight
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Text {
              width: parent.width
              visible: root.email !== "" && root.auxiliaryView === ""
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
            spacing: Style.space(2)

            PanelActionButton {
              visible: root.auxiliaryView !== ""
              iconText: root.iconPrev
              tooltipText: "Back to unread mail (Esc)"
              foreground: root.foreground
              hoverColor: root.accent
              onClicked: root.showView("")
            }

            PanelActionButton {
              iconText: root.soundEnabled ? root.iconSoundOn : root.iconSoundOff
              tooltipText: root.soundEnabled
                ? "Turn off the new-mail sound (s)"
                : "Turn on the new-mail sound (s)"
              foreground: root.soundEnabled ? root.accent : root.foreground
              hoverColor: root.accent
              onClicked: root.toggleSound()
            }

            PanelActionButton {
              iconText: "\uF0C0"
              tooltipText: "Accounts and setup (m)"
              foreground: root.foreground
              hoverColor: root.accent
              onClicked: root.showView("accounts")
            }

            PanelActionButton {
              iconText: "\uF128"
              tooltipText: "Keyboard shortcuts (?)"
              foreground: root.foreground
              hoverColor: root.accent
              onClicked: root.showView("help")
            }

            PanelActionButton {
              id: markAllButton
              visible: root.auxiliaryView === "" && root.hasUnread && root.reachable
              enabled: root.hasUnread && root.reachable
                && !listProc.running && !root.readBusy && !root.markAllBusy && !root.reconciling
              iconText: root.markAllArmed || root.markAllBusy
                ? root.iconConfirm : root.iconMarkAll
              tooltipText: root.markAllBusy
                ? "Marking unread mail as read…"
                : (root.markAllArmed
                  ? "Click again to confirm"
                  : "Mark all unread as read (A)")
              foreground: root.foreground
              hoverColor: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.iconSmall
              onClicked: root.requestMarkAll()
            }

            PanelActionButton {
              id: openMailButton
              visible: root.auxiliaryView === "" && root.hasOpenableInbox
              enabled: root.hasOpenableInbox && !root.markAllBusy
              iconText: root.iconExternal
              tooltipText: root.accountCount > 1
                ? "Open each unread inbox in the browser (i)"
                : "Open unread in browser (i)"
              foreground: root.foreground
              hoverColor: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.iconSmall
              onClicked: root.openSearch()
            }
          }
        }

        Item {
          id: freshnessRow
          width: parent.width
          height: Math.max(freshnessLabel.implicitHeight, refreshButton.height)

          Text {
            id: freshnessLabel
            anchors.left: parent.left
            anchors.right: refreshButton.left
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            text: listProc.running ? "Checking mail…" : root.freshnessText()
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            color: root.foreground
            opacity: 0.65
          }

          PanelActionButton {
            id: refreshButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            iconText: "\uF021"
            tooltipText: "Refresh mail (r)"
            enabled: !root.markAllBusy
            foreground: root.foreground
            hoverColor: root.accent
            onClicked: root.refresh()
          }
        }

        PanelSeparator { width: parent.width }

        PanelMenu {
          id: auxiliaryMenu
          width: parent.width
          visible: root.auxiliaryView !== ""
          help: root.auxiliaryView === "help"
          model: help ? root.shortcutHelp : root.accountMenu
          cursor: root.menuCursor
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          maximumHeight: Math.max(Style.space(60), panel.availableCardHeight
            - panel.verticalContentInset - panelHeading.height - freshnessRow.height - Style.space(24))
          onActivated: function(entry) { root.activateMenu(entry) }
          onHovered: function(index) { root.menuCursor = index }
        }

        Column {
          id: mailContent
          width: parent.width
          spacing: Style.space(6)
          visible: root.auxiliaryView === ""


          Item {
            width: parent.width
            height: staleWarning.visible ? staleWarning.implicitHeight + Style.space(6) : 0
            visible: !root.reachable && root.failures.length === 0

            Text {
              id: staleWarning
              anchors.verticalCenter: parent.verticalCenter
              width: parent.width
              text: root.errorText !== ""
                ? root.errorText
                : "Could not reach mail. Showing the last list."
              textFormat: Text.PlainText
              wrapMode: Text.WordWrap
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              color: bar ? bar.urgent : Color.urgent
            }
          }

          Column {
            id: failureList
            width: parent.width
            visible: root.failures.length > 0
            spacing: Style.space(6)
            bottomPadding: visible ? Style.space(3) : 0

            Repeater {
              model: root.failures

              FailureNotice {
                required property var modelData
                width: failureList.width
                failure: Object.assign({}, modelData, {
                  message: (modelData.message || modelData.error || "Could not reach mail.")
                    + "\n" + MailState.checkLabel(root.accountChecks[modelData.id], root.now)
                })
                foreground: root.foreground
                urgent: bar ? bar.urgent : Color.urgent
                accent: root.accent
                fontFamily: root.fontFamily
                onRunSignIn: function(accountId) { root.runSignIn(accountId) }
                onCopyCommand: function(text) { root.copyCommand(text) }
                onOpenUrl: function(url) { if (root.openBrowser(url)) root.close() }
              }
            }
          }

          Item {
            width: parent.width
            height: (root.actionWarning !== "" && !root.markAllBusy && !root.reconciling)
              ? Math.max(actionWarningLabel.implicitHeight, dismissWarning.height) + Style.space(6) : 0
            visible: root.actionWarning !== "" && !root.markAllBusy && !root.reconciling

            Text {
              id: actionWarningLabel
              anchors.verticalCenter: parent.verticalCenter
              anchors.left: parent.left
              anchors.right: dismissWarning.left
              anchors.rightMargin: Style.space(6)
              text: root.actionWarning
              textFormat: Text.PlainText
              wrapMode: Text.Wrap
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              color: bar ? bar.urgent : Color.urgent
            }

            PanelActionButton {
              id: dismissWarning
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              iconText: "\uF00D"
              tooltipText: "Dismiss action error (x)"
              foreground: root.foreground
              onClicked: root.actionWarning = ""
            }
          }

          Item {
            width: parent.width
            height: root.markAllArmed
              ? markAllConfirmLabel.implicitHeight + Style.space(6) : 0
            visible: root.markAllArmed

            Text {
              id: markAllConfirmLabel
              anchors.verticalCenter: parent.verticalCenter
              width: parent.width
              text: "Press A again to mark " + root.unread + " unread as read"
              textFormat: Text.PlainText
              elide: Text.ElideRight
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              color: bar ? bar.urgent : Color.urgent
            }
          }

          Item {
            width: parent.width
            height: (root.markAllBusy || root.reconciling)
              ? markAllBusyLabel.implicitHeight + Style.space(6) : 0
            visible: root.markAllBusy || root.reconciling

            Text {
              id: markAllBusyLabel
              anchors.verticalCenter: parent.verticalCenter
              width: parent.width
              text: root.markAllBusy
                ? "Marking unread mail as read…"
                : "Refreshing unread mail…"
              textFormat: Text.PlainText
              elide: Text.ElideRight
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              color: Qt.darker(root.foreground, 1.6)
            }
          }

          ListView {
            id: list
            width: parent.width
            visible: root.messages.length > 0
            clip: true
            opacity: (root.markAllBusy || root.reconciling) ? 0.4 : 1
            enabled: !root.markAllBusy && !root.reconciling
            model: root.messages
            spacing: Style.space(1)
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.VerticalFlick
            interactive: contentHeight > height && !root.markAllBusy && !root.reconciling
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            readonly property int cap: {
              var chrome = panelHeading.height + freshnessRow.height + Style.space(30)
              if (root.hasPrev || root.hasNext) chrome += Style.space(38)
              if (staleWarning.visible) chrome += staleWarning.implicitHeight + Style.space(6)
              if (failureList.visible) chrome += failureList.height + Style.space(6)
              if (root.actionWarning !== "" && !root.markAllBusy && !root.reconciling)
                chrome += Math.max(actionWarningLabel.implicitHeight, dismissWarning.height) + Style.space(6)
              if (root.markAllArmed)
                chrome += markAllConfirmLabel.implicitHeight + Style.space(6)
              if (root.markAllBusy || root.reconciling)
                chrome += markAllBusyLabel.implicitHeight + Style.space(6)
              return Math.max(Style.space(40),
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
                onClicked: if (!root.markAllBusy) root.openMessage(row.modelData)
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
                          width: chipText.width + Style.space(8)
                          radius: Style.space(3)
                          color: Qt.rgba(root.foreground.r, root.foreground.g,
                                         root.foreground.b, 0.14)

                          Text {
                            id: chipText
                            anchors.centerIn: parent
                            text: parent.modelData
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            wrapMode: Text.NoWrap
                            maximumLineCount: 1
                            width: Math.min(implicitWidth, Style.space(64))
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
                      width: Math.max(Style.space(40),
                                      line.width - (chips.visible ? chips.width + line.spacing : 0))
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
                enabled: root.hasPrev && !root.readBusy && !root.markAllBusy && !root.reconciling
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
                enabled: root.hasNext && !root.readBusy && !root.markAllBusy && !root.reconciling
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
            height: root.messages.length === 0 && (root.warningText === "" || !root.reachable)
              ? Style.space(60) : 0
            visible: root.messages.length === 0 && (root.warningText === "" || !root.reachable)

            Text {
              anchors.centerIn: parent
              width: parent.width - Style.space(20)
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
              text: root.reachable
                ? "You're all caught up."
                : (root.hasSignInAction
                  ? "Sign in above, then middle-click the icon to refresh."
                  : "Fix sign-in from a terminal, then middle-click the icon.")
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
}
