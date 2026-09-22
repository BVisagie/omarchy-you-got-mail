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
    {key: "x / ×", title: "Dismiss an action error"},
    {key: "Tab / Shift+Tab", title: "Switch to the next / previous bar panel"},
    {key: "Esc", title: "Back to mail, cancel confirmation, or close"},
    {key: "Click bar icon", title: "Open or close the panel"},
    {key: "Right-click icon", title: "Open every inbox with unread mail"},
    {key: "Click message", title: "Open in browser and mark as read"}
  ]
}
