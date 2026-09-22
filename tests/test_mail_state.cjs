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
