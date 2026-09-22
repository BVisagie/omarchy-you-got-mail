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

test('successful, partial and failed refreshes update account state without lying about freshness', () => {
  const p = setup();
  function payload(inboxes) {
    return JSON.stringify({ok: inboxes.some(box => box.ok), messages: [], unread: 0,
      inboxes, accountCount: inboxes.length});
  }
  p.applyPayload(payload([{id: 'a', ok: true, checkedAt: 100}, {id: 'b', ok: true, checkedAt: 110}]));
  assert.equal(p.allCheckedAt, 100);
  p.applyPayload(payload([{id: 'a', ok: true, checkedAt: 200}, {id: 'b', ok: false}]));
  assert.equal(p.allCheckedAt, 100);
  assert.equal(p.accountChecks.b, 110);
  p.applyPayload(payload([{id: 'a', ok: false}, {id: 'b', ok: false}]));
  assert.equal(p.inboxes.every(box => !box.ok), true);
  assert.equal(p.accountChecks.a, 200);
  assert.equal(p.failures.length, 2);
  p.applyPayload(payload([{id: 'a', ok: true, checkedAt: 300}, {id: 'b', ok: true, checkedAt: 305}]));
  assert.equal(p.allCheckedAt, 300);
  p.applyPayload(payload([{id: 'a', ok: true, checkedAt: 400}, {id: 'c', ok: false}]));
  assert.equal(p.allCheckedAt, 0); // Previous full check did not cover this configuration.
  p.applyPayload('not JSON');
  assert.equal(p.inboxes.every(box => !box.ok), true);
});

test('menu and help own navigation; Escape restores selection before closing', () => {
  const p = setup();
  p.markAllArmed = true;
  p.handleTextKey('m');
  assert.equal(p.auxiliaryView, 'accounts');
  assert.equal(p.markAllArmed, false);
  assert.equal(p.menuCursor, 0);
  p.handleTextKey('a');
  assert.equal(p.messages.length, 2);
  p.moveSelection(1);
  assert.equal(p.menuCursor, 1);
  p.handleTextKey('?');
  assert.equal(p.auxiliaryView, 'help');
  p.moveSelection(1);
  assert.equal(p.auxiliaryMenu.contentY, 40);
  p.cursor = 1;
  p.closeRequested();
  assert.equal(p.auxiliaryView, '');
  assert.equal(p.cursor, 0);
  assert.equal(p.opened, true);
  p.closeRequested();
  assert.equal(p.opened, false);
});

test('setup uses a quoted script path and opens no authentication inside the panel', () => {
  const p = setup();
  p.script = "/path with spaces/it's mail/bin/you-got-mail";
  let command;
  p.Util.execArgv = argv => { command = argv; };
  p.addAccount();
  assert.equal(command[0], 'omarchy-launch-floating-terminal-with-presentation');
  assert.equal(command[1], p.Util.shellQuote(p.script) + ' accounts add');
  assert.equal(p.opened, false);
});

test('opening one empty inbox does not invoke read or open every inbox', () => {
  const p = setup();
  p.updateAccounts([{id: 'a', account: 'Personal', ok: true, unread: 0,
    checkedAt: 100, searchUrl: 'https://example.test/a'}]);
  const opened = [];
  p.Util.execArgv = argv => opened.push(argv);
  p.activateMenu(p.accountMenu[0]);
  assert.equal(opened.length, 1);
  assert.equal(opened[0][1], 'https://example.test/a');
  assert.equal(p.readProc.running, false);
  assert.equal(p.unread, 2);
});

test('help lists the global and mail shortcuts the actual handlers support', () => {
  const p = setup();
  const help = Array.from(p.MailState.shortcuts(), item => item.key).join('\n');
  for (const key of ['a', 'A', 'i', 'n / p', 'm', '?', 'Esc']) assert.ok(help.includes(key));
  p.handleTextKey('r');
  assert.equal(p.listProc.running, true);
  p.handleTextKey('r');
  assert.equal(p.refreshPending, true);
});

test('an executable that cannot start restores the row and advances the read queue', () => {
  const p = setup();
  p.markCursorRead();
  p.markCursorRead();
  p.readProc.running = false;
  p.readStartFailed('work:b25l');
  assert.equal(p.unread, 1);
  assert.equal(p.pendingId, 'work:dHdv');
  p.readStartFailed('work:b25l'); // Stale callback must not settle the next action.
  assert.equal(p.pendingId, 'work:dHdv');
  p.readProc.running = false;
  p.readStartFailed('work:dHdv');
  assert.equal(p.unread, 2);
  assert.equal(p.pendingId, '');
  assert.equal(p.listProc.running, true);
  assert.match(p.actionWarning, /process failed/);
});

test('an omitted paging token is not the string undefined', () => {
  const p = setup();
  assert.equal(p.validToken(undefined), false);
  assert.equal(p.validToken(null), false);
  p.applyPayload(JSON.stringify({ok: true, messages: [], unread: 0, inboxes: []}));
  assert.equal(p.nextPage, '');
  assert.equal(p.reachable, true);
});
