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

test('read errors label the account once in both the banner and tooltip', () => {
  for (const [label, error, expected] of [
    ['Office', 'work: timed out', 'work: timed out'],
    ['Office', 'Office: provider exited 1', 'Office: provider exited 1'],
    ['Office', 'WORK: invalid JSON', 'WORK: invalid JSON'],
    ['Office', 'work: no output', 'work: no output'],
    ['Office', 'Permission denied', 'Office: Permission denied'],
    ['Office', 'workshop: rejected', 'Office: workshop: rejected'],
    ['Work [EU]', 'Work [EU]: rejected', 'Work [EU]: rejected'],
    ['', 'Permission denied', 'work: Permission denied'],
  ]) {
    const p = setup();
    p.messages[0].account = label;
    p.markCursorRead();
    complete(p, JSON.stringify({ok: false, error}));
    assert.equal(p.actionWarning, expected);
    assert.equal(p.mailTooltip(), expected);
    assert.equal(p.unread, 2);
  }
});

test('action notices replace stale errors and preserve multiline messages once', () => {
  const p = setup();
  p.actionWarning = 'Old error';
  const warning = 'Work: timed out\nHome: needs sign-in';
  p.showActionWarning(warning);
  p.showActionWarning(warning);
  assert.equal(p.actionWarning, warning);
  p.showActionWarning('Work: permission denied');
  assert.equal(p.actionWarning, 'Work: permission denied');
});

test('clean mark-all success clears an earlier action error', () => {
  const p = setup();
  p.actionWarning = 'Work: old read error';
  p.markAllBusy = true;
  p.applyReadAllPayload('{"ok":true,"marked":2}');
  assert.equal(p.actionWarning, '');
  assert.equal(p.markAllBusy, false);
  assert.equal(p.reconciling, true);
  assert.equal(p.listProc.running, true);
});

test('mark-all warning, failure and malformed output replace earlier action errors', () => {
  for (const [output, expected] of [
    ['{"ok":true,"marked":1,"warning":"Home: unavailable"}', 'Home: unavailable'],
    ['{"ok":false,"marked":0,"error":"Work: rejected"}', 'Work: rejected'],
    ['not JSON', 'unexpected output from you-got-mail'],
  ]) {
    const p = setup();
    p.actionWarning = 'Work: old read error';
    p.applyReadAllPayload(output);
    assert.equal(p.actionWarning, expected);
    assert.equal(p.mailTooltip(), expected);
  }
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

// New-mail sound: the panel feeds page-1 rows to MailState.arrivals and hands
// the fresh IDs to `you-got-mail chime`.
const accounts = [{id: 'work', ok: true, checkedAt: 100}, {id: 'home', ok: true, checkedAt: 100}];

function soundPanel(settings = {}) {
  const p = panelHarness();
  Object.assign(p, {soundEnabled: true}, settings);
  const chimes = [];
  p.Util.execArgv = argv => chimes.push(Array.from(argv));
  return {p, chimes};
}

function list(rows, extra = {}) {
  return JSON.stringify(Object.assign({ok: true, unread: rows.length, inboxes: accounts,
    messages: rows.map(([id, ts]) => ({id, ts, subject: 'Hello'}))}, extra));
}

const chimed = argv => argv.slice(argv.indexOf('--') + 1);

test('the panel calls chime with the arrival IDs, only on page 1', () => {
  const {p, chimes} = soundPanel();
  p.applyPayload(list([['work:old', 10]]));
  p.applyPayload(list([['work:new', 20], ['work:old', 10]]));
  assert.deepEqual(chimes, [
    ['/test/you-got-mail', 'chime', '--cooldown', '60', '--volume', '100', '--', 'work:new'],
  ]);
  p.listPage = p.pageToken = 'page2';
  p.applyPayload(list([['work:newer', 30]]));
  assert.equal(chimes.length, 1);
});

test('paging returns none and leaves the arrival state unchanged', () => {
  const {p, chimes} = soundPanel();
  p.applyPayload(list([['work:old', 10]]));
  const before = p.arrivalState;
  p.listPage = p.pageToken = 'page2';
  p.applyPayload(list([['work:new', 20]], {nextPage: 'page3'}));
  assert.deepEqual(Array.from(p.messages, row => row.id), ['work:new']); // Accepted and shown.
  assert.equal(p.arrivalState, before);
  assert.equal(chimes.length, 0);
});

test('nothing is called while soundEnabled is off, but the state still updates', () => {
  const {p, chimes} = soundPanel({soundEnabled: false});
  p.applyPayload(list([['work:old', 10]]));
  const baseline = p.arrivalState;
  assert.notEqual(baseline, null);
  p.applyPayload(list([['work:new', 20], ['work:old', 10]]));
  assert.equal(chimes.length, 0);
  assert.notEqual(p.arrivalState, baseline);
  p.soundEnabled = true;
  p.applyPayload(list([['work:new', 20], ['work:old', 10]]));
  assert.equal(chimes.length, 0); // work:new was recorded while the sound was off.
});

test('a payload rejected by acceptsList leaves the arrival state unchanged', () => {
  const {p, chimes} = soundPanel();
  p.applyPayload(list([['work:old', 10]]));
  const before = p.arrivalState;
  p.mailboxRevision += 1; // A read finished while this list was in flight.
  p.applyPayload(list([['work:new', 20], ['work:old', 10]]));
  assert.equal(p.refreshPending, true);
  assert.equal(p.arrivalState, before);
  assert.equal(chimes.length, 0);
  p.listRevision = p.mailboxRevision; // The follow-up refresh is accepted.
  p.applyPayload(list([['work:new', 20], ['work:old', 10]]));
  assert.deepEqual(chimes.map(chimed), [['work:new']]);
});

test('a dismissed ID is neither announced nor passed to chime', () => {
  const {p, chimes} = soundPanel();
  p.applyPayload(list([['work:old', 10]]));
  p.dismissedIds = {'work:gone': {message: {id: 'work:gone', ts: 20}, index: 0}};
  p.applyPayload(list([['work:gone', 20], ['work:old', 10]]));
  assert.equal(chimes.length, 0);
  p.applyPayload(list([['work:new', 30], ['work:gone', 20], ['work:old', 10]]));
  assert.deepEqual(chimes.map(chimed), [['work:new']]);
});

test('two accounts that each receive one message still mean one chime', () => {
  const {p, chimes} = soundPanel();
  p.applyPayload(list([['work:old', 10], ['home:old', 5]]));
  p.applyPayload(list([['home:new', 40], ['work:new', 30], ['work:old', 10], ['home:old', 5]]));
  assert.deepEqual(chimes.map(chimed), [['home:new', 'work:new']]);
});

test('chime gets --cooldown and --volume from the settings, and --file only when set', () => {
  const {p, chimes} = soundPanel({soundCooldownSec: 0, soundVolume: 35, soundFile: '~/Sounds/mail.ogg'});
  p.applyPayload(list([['work:old', 10]]));
  p.applyPayload(list([['work:new', 20], ['work:old', 10]]));
  assert.deepEqual(chimes, [['/test/you-got-mail', 'chime', '--cooldown', '0', '--volume', '35',
    '--file', '~/Sounds/mail.ogg', '--', 'work:new']]);
  p.soundFile = '';
  p.applyPayload(list([['work:newer', 30], ['work:new', 20], ['work:old', 10]]));
  assert.deepEqual(chimes[1], ['/test/you-got-mail', 'chime', '--cooldown', '0', '--volume', '35',
    '--', 'work:newer']);
});

test('IDs that fail validId are not passed, and no valid ID means no call', () => {
  const {p, chimes} = soundPanel();
  p.applyPayload(list([['work:old', 10]]));
  p.applyPayload(list([['work:bad id', 30], ['work:good', 20], ['work:old', 10]]));
  assert.deepEqual(chimes.map(chimed), [['work:good']]);
  p.applyPayload(list([['work:bad!', 40], ['work:bad id', 30], ['work:good', 20], ['work:old', 10]]));
  assert.equal(chimes.length, 1);
});

test('the first payload after start records a baseline and makes no call', () => {
  const {p, chimes} = soundPanel();
  assert.equal(p.arrivalState, null);
  p.applyPayload(list([['work:one', 20], ['home:two', 10]]));
  assert.equal(chimes.length, 0);
  assert.deepEqual(Object.keys(p.arrivalState.accounts).sort(), ['home', 'work']);
});

test('unreachable and unparsable payloads leave the arrival state unchanged', () => {
  const {p, chimes} = soundPanel();
  p.applyPayload(list([['work:old', 10]]));
  const before = p.arrivalState;
  p.applyPayload(JSON.stringify({ok: false, error: 'offline', inboxes: [{id: 'work', ok: false}],
    messages: [{id: 'work:new', ts: 20}]}));
  assert.equal(p.arrivalState, before);
  p.applyPayload('not JSON');
  assert.equal(p.arrivalState, before);
  assert.equal(chimes.length, 0);
  p.applyPayload(list([['work:new', 20], ['work:old', 10]])); // Mail from the outage chimes once.
  assert.deepEqual(chimes.map(chimed), [['work:new']]);
});
