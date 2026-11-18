.pragma library

// Pure state transitions shared by the panel and the headless tests.

// Text goes through a translator, T.t(key, english, args) and
// T.n(key, count, englishOne, englishOther). The panel passes one backed by
// i18n/*.json; without one (the headless tests) the English text is used,
// with %1, %2 filled in from args.
function fill(text, args) {
  return String(text).replace(/%(\d)/g, function(match, n) {
    var value = (args || [])[Number(n) - 1]
    return value === undefined ? match : String(value)
  })
}

var PLAIN = {
  t: function(key, english, args) { return fill(english, args) },
  n: function(key, count, one, other) { return fill(count === 1 ? one : other, [count]) }
}
function dismiss(messages, unread, dismissed, id) {
  if (dismissed[id]) return null
  var index = messages.findIndex(function(row) { return row.id === id })
  if (index < 0) return null
  var next = Object.assign({}, dismissed)
  next[id] = { message: messages[index], index: index }
  return {
    messages: messages.filter(function(row) { return row.id !== id }),
    unread: Math.max(0, unread - 1),
    dismissed: next
  }
}

function readError(text, exitCode, T) {
  T = T || PLAIN
  if (exitCode !== 0) return T.t("read.processFailed", "Could not mark as read (process failed).")
  try {
    var result = JSON.parse(text)
    if (result && result.ok === true) return ""
    if (result && typeof result.error === "string" && result.error.trim())
      return result.error.trim()
  } catch (_) {}
  return T.t("read.unexpected", "Could not mark as read (unexpected response).")
}

function readNotice(error, accountId, accountLabel) {
  var label = String(accountLabel || accountId)
  var lower = error.toLowerCase()
  if (lower.indexOf(accountId.toLowerCase() + ":") === 0
      || lower.indexOf(label.toLowerCase() + ":") === 0) return error
  return label + ": " + error
}

function settle(messages, unread, dismissed, id, error) {
  var saved = dismissed[id]
  var next = Object.assign({}, dismissed)
  delete next[id]
  var rows = messages.slice()
  if (error && saved && !rows.some(function(row) { return row.id === id })) {
    rows.splice(Math.min(saved.index, rows.length), 0, saved.message)
    rows.sort(function(a, b) { return (Number(b.ts) || 0) - (Number(a.ts) || 0) })
    unread += 1
  }
  return { messages: rows, unread: unread, dismissed: next }
}

function acceptsList(startRevision, currentRevision, requestedPage, currentPage) {
  return startRevision === currentRevision && requestedPage === currentPage
}

function validUrl(url) {
  return /^https:\/\/[A-Za-z0-9.-]+(?::\d+)?(?:[/?#][^\s]*)?$/.test(String(url))
}

function updateChecks(previous, inboxes) {
  var checks = {}
  var allCheckedAt = 0
  var complete = inboxes.length > 0
  for (var i = 0; i < inboxes.length; i++) {
    var box = inboxes[i]
    if (!box || !box.id) { complete = false; continue }
    var checked = Number(box.checkedAt)
    if (box.ok === true && isFinite(checked) && checked > 0) {
      checks[box.id] = checked
      allCheckedAt = allCheckedAt ? Math.min(allCheckedAt, checked) : checked
    } else {
      checks[box.id] = previous[box.id] || 0
      complete = false
    }
  }
  return { checks: checks, allCheckedAt: complete ? allCheckedAt : 0 }
}

// Decides which rows of a reachable page-1 list are new mail. State is kept
// per account ID (the part of a row ID before ":"), as { seen, mark }, plus
// the shared floor: the oldest ts of the previous page 1 when it was full.
// A failing account's rows are missing from page 1, so the shared floor
// can't vouch for them: from its first failed call its entry holds, as
// held.floor (null for none), the floor that call judged by, which was set
// by a page that still had its rows. Its rows are judged by that floor on
// the call it is back.
function arrivals(state, inboxes, messages, pageFull, now) {
  var before = state && state.accounts ? state.accounts : {}
  var floor = state && typeof state.floor === "number" ? state.floor : null
  function baseline(accountId) {
    return Object.prototype.hasOwnProperty.call(before, accountId) ? before[accountId] : null
  }
  var fresh = []
  var pages = Object.create(null)
  var oldest = null
  for (var i = 0; i < messages.length; i++) {
    var row = messages[i]
    if (!row || !row.id) continue
    var id = String(row.id)
    var accountId = id.split(":")[0]
    var ts = Number(row.ts)
    if (!isFinite(ts)) ts = 0
    var known = baseline(accountId)
    var limit = known && known.held ? known.held.floor : floor
    if (known && known.seen.indexOf(id) < 0
        && (known.mark === null || ts >= known.mark)
        && (limit === null || ts > limit))
      fresh.push(id)
    var page = pages[accountId] || (pages[accountId] = { ids: [], newest: null })
    page.ids.push(id)
    // A row dated after now + 300 s is misdated; left on page 1, it would
    // hold the mark ahead of real time and silence the account.
    if (ts <= now + 300 && (page.newest === null || ts > page.newest)) page.newest = ts
    oldest = oldest === null ? ts : Math.min(oldest, ts)
  }
  var accounts = {}
  for (var b = 0; b < inboxes.length; b++) {
    var box = inboxes[b]
    if (!box || !box.id) continue
    var old = baseline(box.id)
    // A failed account keeps its state and the floor it holds; one never ok
    // yet gets no baseline.
    if (box.ok === true) accounts[box.id] = remember(old, pages[box.id])
    else if (old && old.held) accounts[box.id] = old
    else if (old) accounts[box.id] = { seen: old.seen, mark: old.mark, held: { floor: floor } }
  }
  return {
    state: { accounts: accounts, floor: pageFull && oldest !== null ? oldest : null },
    fresh: fresh
  }
}

// Moves an ok account's page-1 IDs to the recent end of the 200 it keeps,
// raises its mark to its newest row dated no later than now + 300 s and
// drops any floor it held while failing.
function remember(entry, page) {
  var seen = entry ? entry.seen : []
  var mark = entry ? entry.mark : null
  if (page) {
    seen = seen.filter(function(id) { return page.ids.indexOf(id) < 0 }).concat(page.ids)
    if (page.newest !== null) mark = mark === null ? page.newest : Math.max(mark, page.newest)
  }
  return { seen: seen.slice(-200), mark: mark }
}

// How long ago, in the words that follow "Checked" or "Last full check".
function ago(checkedAt, now, T) {
  T = T || PLAIN
  var age = Math.max(0, now - checkedAt)
  if (age < 60) return T.t("ago.now", "just now")
  if (age < 3600) return T.n("ago.minutes", Math.floor(age / 60), "%1 minute ago", "%1 minutes ago")
  if (age < 86400) return T.n("ago.hours", Math.floor(age / 3600), "%1 hour ago", "%1 hours ago")
  return T.n("ago.days", Math.floor(age / 86400), "%1 day ago", "%1 days ago")
}

function checkLabel(checkedAt, now, T) {
  T = T || PLAIN
  if (!(checkedAt > 0)) return T.t("check.never", "Not checked successfully yet")
  return T.t("check.when", "Checked %1", [ago(checkedAt, now, T)])
}

function accountEntries(inboxes, checks, now, T) {
  T = T || PLAIN
  var entries = []
  var labels = Object.create(null)
  for (var n = 0; n < inboxes.length; n++) {
    var name = String(inboxes[n].account || inboxes[n].id || T.t("account.fallback", "Account"))
    labels[name] = (labels[name] || 0) + 1
  }
  for (var i = 0; i < inboxes.length; i++) {
    var box = inboxes[i] || {}
    var available = box.ok === true && validUrl(box.searchUrl)
    var count = Math.max(0, Number(box.unread) || 0)
    var status = box.ok === true ? T.n("count.unread", count, "%1 unread", "%1 unread") : T.t("account.unavailable", "Unavailable")
    var label = String(box.account || box.id || T.t("account.fallback", "Account"))
    // IDs disambiguate account labels without exposing addresses or credentials.
    if (box.id && labels[label] > 1) label += " · " + box.id
    entries.push({
      key: "account:" + box.id,
      title: label,
      detail: status + " · " + checkLabel(checks[box.id], now, T)
        + (box.ok === false ? "\n" + String(box.message || box.error || T.t("account.unreachable", "Could not reach this account.")) : ""),
      action: available ? T.t("account.openInbox", "Open inbox")
        : (box.ok === true ? T.t("account.noWebmail", "No webmail URL configured") : T.t("account.inboxUnavailable", "Inbox unavailable")),
      enabled: available,
      kind: "inbox",
      url: available ? box.searchUrl : ""
    })
  }
  entries.push({key: "add", title: T.t("account.add", "Add account"), detail: T.t("account.addDetail", "Set up a mailbox in a terminal"),
                action: T.t("account.addAction", "Open setup"), enabled: true, kind: "add"})
  entries.push({key: "guide", title: T.t("account.guide", "Setup guide"), detail: T.t("account.guideDetail", "Provider instructions and sign-in help"),
                action: T.t("account.guideAction", "Open guide"), enabled: true, kind: "guide"})
  return entries
}

function moveMenu(entries, index, delta) {
  var next = index + delta
  while (next >= 0 && next < entries.length) {
    if (entries[next].enabled) return next
    next += delta
  }
  return index
}

// Keyboard keys stay as they are; the words around them are translated.
function shortcuts(T) {
  T = T || PLAIN
  return [
    {key: "↑ ↓ / j k", title: T.t("help.move", "Move through mail or account actions")},
    {key: "Enter / Space / o", title: T.t("help.open", "Open the selected message or account action")},
    {key: "a", title: T.t("help.markOne", "Mark the selected message as read")},
    {key: "A", title: T.t("help.markAll", "Mark all unread as read; press twice to confirm")},
    {key: "i", title: T.t("help.openUnread", "Open every inbox with unread mail")},
    {key: "n / p", title: T.t("help.pages", "Next / previous page")},
    {key: "m", title: T.t("help.accounts", "Accounts and setup")},
    {key: "?", title: T.t("help.help", "Show or hide shortcut help")},
    {key: T.t("help.refreshKeys", "r / middle-click"), title: T.t("help.refresh", "Refresh mail")},
    {key: "s", title: T.t("help.sound", "Turn the new-mail sound on or off")},
    {key: "x / ×", title: T.t("help.dismiss", "Dismiss an action error")},
    {key: "Tab / Shift+Tab", title: T.t("help.panels", "Switch to the next / previous bar panel")},
    {key: "Esc", title: T.t("help.back", "Back to mail, cancel confirmation, or close")},
    {key: T.t("help.clickIconKey", "Click bar icon"), title: T.t("help.clickIcon", "Open or close the panel")},
    {key: T.t("help.rightClickIconKey", "Right-click icon"), title: T.t("help.openUnread", "Open every inbox with unread mail")},
    {key: T.t("help.clickMessageKey", "Click message"), title: T.t("help.clickMessage", "Open in browser and mark as read")}
  ]
}
