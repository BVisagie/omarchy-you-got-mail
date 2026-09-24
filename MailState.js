.pragma library

// Pure state transitions shared by the panel and the headless tests.
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

function readError(text, exitCode) {
  if (exitCode !== 0) return "Could not mark as read (process failed)."
  try {
    var result = JSON.parse(text)
    if (result && result.ok === true) return ""
    if (result && typeof result.error === "string" && result.error.trim())
      return result.error.trim()
  } catch (_) {}
  return "Could not mark as read (unexpected response)."
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

function checkLabel(checkedAt, now) {
  if (!(checkedAt > 0)) return "Not checked successfully yet"
  var age = Math.max(0, now - checkedAt)
  if (age < 60) return "Checked just now"
  if (age < 3600) return "Checked " + Math.floor(age / 60) + "m ago"
  if (age < 86400) return "Checked " + Math.floor(age / 3600) + "h ago"
  return "Checked " + Math.floor(age / 86400) + "d ago"
}

function accountEntries(inboxes, checks, now) {
  var entries = []
  var labels = Object.create(null)
  for (var n = 0; n < inboxes.length; n++) {
    var name = String(inboxes[n].account || inboxes[n].id || "Account")
    labels[name] = (labels[name] || 0) + 1
  }
  for (var i = 0; i < inboxes.length; i++) {
    var box = inboxes[i] || {}
    var available = box.ok === true && validUrl(box.searchUrl)
    var status = box.ok === true ? (Math.max(0, Number(box.unread) || 0) + " unread") : "Unavailable"
    var label = String(box.account || box.id || "Account")
    // IDs disambiguate account labels without exposing addresses or credentials.
    if (box.id && labels[label] > 1) label += " · " + box.id
    entries.push({
      key: "account:" + box.id,
      title: label,
      detail: status + " · " + checkLabel(checks[box.id], now)
        + (box.ok === false ? "\n" + String(box.message || box.error || "Could not reach this account.") : ""),
      action: available ? "Open inbox" : (box.ok === true ? "No webmail URL configured" : "Inbox unavailable"),
      enabled: available,
      kind: "inbox",
      url: available ? box.searchUrl : ""
    })
  }
  entries.push({key: "add", title: "Add account", detail: "Set up a mailbox in a terminal", action: "Open setup", enabled: true, kind: "add"})
  entries.push({key: "guide", title: "Setup guide", detail: "Provider instructions and sign-in help", action: "Open guide", enabled: true, kind: "guide"})
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

function shortcuts() {
  return [
    {key: "↑ ↓ / j k", title: "Move through mail or account actions"},
    {key: "Enter / Space / o", title: "Open the selected message or account action"},
    {key: "a", title: "Mark the selected message as read"},
    {key: "A", title: "Mark all unread as read; press twice to confirm"},
    {key: "i", title: "Open every inbox with unread mail"},
    {key: "n / p", title: "Next / previous page"},
    {key: "m", title: "Accounts and setup"},
    {key: "?", title: "Show or hide shortcut help"},
    {key: "r / middle-click", title: "Refresh mail"},
    {key: "s", title: "Turn the new-mail sound on or off"},
    {key: "x / ×", title: "Dismiss an action error"},
    {key: "Tab / Shift+Tab", title: "Switch to the next / previous bar panel"},
    {key: "Esc", title: "Back to mail, cancel confirmation, or close"},
    {key: "Click bar icon", title: "Open or close the panel"},
    {key: "Right-click icon", title: "Open every inbox with unread mail"},
    {key: "Click message", title: "Open in browser and mark as read"}
  ]
}
