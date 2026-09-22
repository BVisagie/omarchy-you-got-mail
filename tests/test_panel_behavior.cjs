const assert = require('node:assert/strict');
const {test} = require('node:test');
const panelHarness = require('./panel_harness.cjs');

function setup() {
  const p = panelHarness();
  p.messages = [
    {id: 'work:b25l', ts: 30, account: 'Work', url: 'https://example.test/one'},
    {id: 'work:dHdv', ts: 20, account: 'Work', url: 'https://example.test/two'},
  ];
  p.unread = 2;
  return p;
}

function complete(p, text, code = 0) {
  p.readProc.running = false;
  p.readExitCode = code;
  p.readExited = true;
  p.finishRead(); // Exit arrives before stdout.
  assert.notEqual(p.pendingId, '');
  p.readOutput = text;
  p.readOutputReady = true;
  p.finishRead();
}

test('panel queues reads, recovers only failed action and refreshes after draining', () => {
  const p = setup();
  p.markCursorRead();
  p.markCursorRead();
  p.requestMarkAll();
  assert.equal(p.markAllArmed, false);
  assert.equal(p.unread, 0);
  p.refresh();
  assert.equal(p.listProc.running, false);
  complete(p, '{"ok":false,"error":"No permission"}');
  assert.equal(p.unread, 1);
  assert.equal(p.pendingId, 'work:dHdv');
  assert.equal(p.listProc.running, false);
  complete(p, '{"ok":true}');
  assert.equal(p.pendingId, '');
  assert.equal(p.listProc.running, true);
  assert.match(p.actionWarning, /Work: No permission/);
  assert.deepEqual(Array.from(p.messages, row => row.id), ['work:b25l']);
});

test('browser handoff closes panel but preserves pending action and late error', () => {
  const p = setup();
  let opened = 0;
  p.Util.execArgv = () => { opened++; };
  p.openMessage(p.messages[0]);
  assert.equal(opened, 1);
  assert.equal(p.opened, false);
  assert.ok(p.dismissedIds['work:b25l']);
  complete(p, '', 1);
  p.opened = true;
  p.openedChanged();
  assert.ok(p.actionWarning);
  assert.equal(p.unread, 2);
  assert.equal(opened, 1);
  p.close();
  assert.ok(p.actionWarning);
});

test('pre-action list response cannot undo rollback or reinsert successful reads', () => {
  const p = setup();
  p.refresh();
  const response = JSON.stringify({ok: true, unread: 2, messages: p.messages});
  p.markCursorRead();
  complete(p, '{"ok":true}');
  p.applyPayload(response);
  assert.equal(p.unread, 1);
  assert.equal(p.messages.length, 1);
  assert.equal(p.refreshPending, true);
});

test('stdout arriving before exit does not settle early', () => {
  const p = setup();
  p.markCursorRead();
  p.readOutput = '{"ok":false,"error":"Rejected"}';
  p.readOutputReady = true;
  p.finishRead();
  assert.equal(p.unread, 1);
  p.readProc.running = false;
  p.readExited = true;
  p.finishRead();
  assert.equal(p.unread, 2);
  assert.match(p.actionWarning, /Rejected/);
});
