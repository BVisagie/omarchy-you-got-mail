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
