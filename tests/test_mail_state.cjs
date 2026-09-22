const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const state = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../MailState.js'), 'utf8')
  .replace(/^\.pragma library\s*/, ''), state);
const rows = [
  {id: 'work:one', ts: 30, account: 'Work'},
  {id: 'work:two', ts: 20, account: 'Work'},
  {id: 'home:three', ts: 10, account: 'Home'},
];
const ids = result => Array.from(result.messages, row => row.id);

test('successful action stays removed until authoritative refresh', () => {
  const removed = state.dismiss(rows, 10, {}, 'work:one');
  const result = state.settle(removed.messages, removed.unread, removed.dismissed,
    'work:one', state.readError('{"ok":true}', 0));
  assert.deepEqual(ids(result), ['work:two', 'home:three']);
  assert.equal(result.unread, 9);
  assert.equal(Object.keys(result.dismissed).length, 0);
});

test('failure JSON with a successful exit restores row and count', () => {
  const removed = state.dismiss(rows, 10, {}, 'work:one');
  const error = state.readError('{"ok":false,"error":"Permission denied"}', 0);
  assert.equal(error, 'Permission denied');
  const result = state.settle(removed.messages, removed.unread, removed.dismissed,
    'work:one', error);
  assert.deepEqual(ids(result), rows.map(row => row.id));
  assert.equal(result.unread, 10);
  const repeated = state.settle(result.messages, result.unread, result.dismissed,
    'work:one', error);
  assert.equal(repeated.unread, 10);
});

test('missing, malformed, non-object and failed process results fail closed', () => {
  for (const text of ['', 'broken', 'null', '[]', '{}', '{"ok":"true"}'])
    assert.ok(state.readError(text, 0));
  assert.ok(state.readError('{"ok":true}', 1));
});

test('mixed queued actions restore only failed messages without double decrement', () => {
  const first = state.dismiss(rows, 3, {}, 'work:one');
  assert.equal(state.dismiss(first.messages, first.unread, first.dismissed, 'work:one'), null);
  const second = state.dismiss(first.messages, first.unread, first.dismissed, 'work:two');
  const failed = state.settle(second.messages, second.unread, second.dismissed, 'work:one', 'failed');
  const done = state.settle(failed.messages, failed.unread, failed.dismissed, 'work:two', '');
  assert.deepEqual(ids(done), ['work:one', 'home:three']);
  assert.equal(done.unread, 2);
});

test('old refreshes cannot overwrite actions or a changed page', () => {
  assert.equal(state.acceptsList(0, 1, '', ''), false);
  assert.equal(state.acceptsList(1, 2, '', ''), false);
  assert.equal(state.acceptsList(2, 2, '25', ''), false);
  assert.equal(state.acceptsList(2, 2, '', ''), true);
});

test('account checks distinguish partial success, total outage and recovery', () => {
  const first = state.updateChecks({}, [
    {id: 'a', ok: true, checkedAt: 100}, {id: 'b', ok: true, checkedAt: 105},
  ]);
  assert.equal(first.allCheckedAt, 100);
  const partial = state.updateChecks(first.checks, [
    {id: 'a', ok: true, checkedAt: 200}, {id: 'b', ok: false},
  ]);
  assert.equal(partial.checks.b, 105);
  assert.equal(partial.allCheckedAt, 0);
  const failed = state.updateChecks(partial.checks, [{id: 'a', ok: false}, {id: 'b', ok: false}]);
  assert.equal(failed.checks.a, 200);
  assert.equal(failed.checks.b, 105);
  const recovered = state.updateChecks(failed.checks, [
    {id: 'a', ok: true, checkedAt: 300}, {id: 'b', ok: true, checkedAt: 310},
  ]);
  assert.equal(recovered.allCheckedAt, 300);
});

test('check labels use a controlled clock and cope with unset and future checks', () => {
  assert.equal(state.checkLabel(0, 1000), 'Not checked successfully yet');
  assert.equal(state.checkLabel(1000, 1000), 'Checked just now');
  assert.equal(state.checkLabel(1000, 1720), 'Checked 12m ago');
  assert.equal(state.checkLabel(1000, 8200), 'Checked 2h ago');
  assert.equal(state.checkLabel(1000, 173800), 'Checked 2d ago');
  assert.equal(state.checkLabel(2000, 1000), 'Checked just now');
});

test('accounts with duplicate names, zero unread and unavailable webmail remain distinct', () => {
  const entries = state.accountEntries([
    {id: 'a', account: 'Mail', ok: true, unread: 0, searchUrl: 'https://example.test/a'},
    {id: 'b', account: 'Mail', ok: true, unread: 3, searchUrl: ''},
    {id: 'c', account: 'Mail', ok: false, unread: 0, searchUrl: 'https://example.test/c'},
    {id: 'd', account: 'Mail', ok: true, searchUrl: 'file:///tmp/mail'},
  ], {}, 1000);
  assert.notEqual(entries[0].title, entries[1].title);
  assert.equal(entries[0].enabled, true);
  assert.match(entries[0].detail, /^0 unread/);
  assert.equal(entries[1].enabled, false);
  assert.match(entries[2].detail, /^Unavailable/);
  assert.equal(entries[2].enabled, false);
  assert.equal(entries[3].enabled, false);
  assert.equal(state.moveMenu(entries, 0, 1), 4); // Skip unavailable inboxes to Add account.
  assert.equal(state.moveMenu(entries, 4, -1), 0);
});
