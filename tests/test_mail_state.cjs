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

const NOW = 1000;
const inbox = (id, ok = true) => ({id, ok});
const mail = (id, ts, account) => ({id, ts, account});
const fresh = result => Array.from(result.fresh);

test('the first page-1 list only records a baseline', () => {
  const first = state.arrivals(null, [inbox('work'), inbox('home')],
    [mail('work:a', 900), mail('home:h', 800)], true, NOW);
  assert.deepEqual(fresh(first), []);
});

test('one new ID is one arrival, and the same list again has none', () => {
  const boxes = [inbox('work')];
  const base = state.arrivals(null, boxes, [mail('work:a', 900)], false, NOW);
  const page = [mail('work:b', 950), mail('work:a', 900)];
  const arrived = state.arrivals(base.state, boxes, page, false, NOW + 60);
  assert.deepEqual(fresh(arrived), ['work:b']);
  assert.deepEqual(fresh(state.arrivals(arrived.state, boxes, page, false, NOW + 120)), []);
});

test('old mail marked unread again is below the mark and not new', () => {
  const boxes = [inbox('work')];
  const base = state.arrivals(null, boxes, [mail('work:a', 900)], false, NOW);
  const again = state.arrivals(base.state, boxes,
    [mail('work:a', 900), mail('work:old', 500)], false, NOW + 60);
  assert.deepEqual(fresh(again), []);
});

test('the newest message read elsewhere and marked unread again is still seen', () => {
  const boxes = [inbox('work')];
  const page = [mail('work:b', 950), mail('work:a', 900)];
  const base = state.arrivals(null, boxes, page, false, NOW);
  const read = state.arrivals(base.state, boxes, [mail('work:a', 900)], false, NOW + 60);
  const again = state.arrivals(read.state, boxes, page, false, NOW + 120);
  assert.deepEqual(fresh(read), []);
  assert.deepEqual(fresh(again), []);
});

test('older rows raised from page 2 by reading the busy account are not new', () => {
  const boxes = [inbox('busy'), inbox('quiet')];
  // Page 1 holds two rows; the quiet account's only unread mail is on page 2.
  const full = [mail('busy:c', 900), mail('busy:b', 800)];
  const raised = [mail('busy:a', 700), mail('quiet:q', 500)];
  const base = state.arrivals(null, boxes, full, true, NOW);
  assert.deepEqual(fresh(state.arrivals(base.state, boxes, raised, false, NOW + 60)), []);
  // After a page 1 that was not full, the same quiet row cannot have come from page 2.
  const short = state.arrivals(null, boxes, full, false, NOW);
  assert.deepEqual(fresh(state.arrivals(short.state, boxes, raised, false, NOW + 60)),
    ['quiet:q']);
});

test('a future-dated row cannot raise the mark past now + 300 s', () => {
  const boxes = [inbox('work')];
  const base = state.arrivals(null, boxes, [mail('work:a', 900)], false, NOW);
  const misdated = state.arrivals(base.state, boxes,
    [mail('work:future', 99999), mail('work:a', 900)], false, NOW);
  assert.deepEqual(fresh(misdated), ['work:future']);
  const real = state.arrivals(misdated.state, boxes,
    [mail('work:future', 99999), mail('work:real', NOW + 330), mail('work:a', 900)],
    false, NOW + 360);
  assert.deepEqual(fresh(real), ['work:real']);
});

test('an account that fails and recovers counts only mail that arrived meanwhile', () => {
  const both = [inbox('work'), inbox('home')];
  const base = state.arrivals(null, both,
    [mail('work:a', 900), mail('home:h', 800)], false, NOW);
  const failed = state.arrivals(base.state, [inbox('work', false), inbox('home')],
    [mail('home:h', 800)], false, NOW + 60);
  assert.deepEqual(fresh(failed), []);
  const recovered = state.arrivals(failed.state, both,
    [mail('work:new', 1100), mail('work:a', 900), mail('home:h', 800), mail('work:old', 500)],
    false, NOW + 600);
  assert.deepEqual(fresh(recovered), ['work:new']);
});

test('an account seen for the first time only records a baseline', () => {
  const base = state.arrivals(null, [inbox('work'), inbox('home', false)],
    [mail('work:a', 900)], false, NOW);
  // home has failed since start; added was just set up.
  const boxes = [inbox('work'), inbox('home'), inbox('added')];
  const first = state.arrivals(base.state, boxes,
    [mail('home:h', 950), mail('added:n', 940), mail('work:a', 900)], false, NOW + 60);
  assert.deepEqual(fresh(first), []);
  const later = state.arrivals(first.state, boxes,
    [mail('home:i', 1050), mail('added:o', 1040), mail('home:h', 950), mail('added:n', 940),
      mail('work:a', 900)], false, NOW + 120);
  assert.deepEqual(fresh(later), ['home:i', 'added:o']);
});

test('accounts that share a label keep separate state', () => {
  const boxes = [inbox('a'), inbox('b')];
  const base = state.arrivals(null, boxes,
    [mail('a:x', 950, 'Mail'), mail('b:y', 600, 'Mail')], false, NOW);
  const next = state.arrivals(base.state, boxes,
    [mail('a:x', 950, 'Mail'), mail('b:z', 700, 'Mail'), mail('b:y', 600, 'Mail')],
    false, NOW + 60);
  assert.deepEqual(fresh(next), ['b:z']);
});

test('two accounts that each receive one message give two arrivals', () => {
  const boxes = [inbox('work'), inbox('home')];
  const base = state.arrivals(null, boxes,
    [mail('work:a', 900), mail('home:h', 800)], false, NOW);
  const next = state.arrivals(base.state, boxes,
    [mail('work:b', 980), mail('home:i', 970), mail('work:a', 900), mail('home:h', 800)],
    false, NOW + 60);
  assert.deepEqual(fresh(next), ['work:b', 'home:i']);
});

test('account IDs that name Object properties still need a baseline', () => {
  const base = state.arrivals(null, [inbox('work')], [mail('work:a', 900)], false, NOW);
  const boxes = [inbox('work'), inbox('constructor'), inbox('toString'),
    inbox('hasOwnProperty')];
  const first = state.arrivals(base.state, boxes,
    [mail('constructor:c', 950), mail('toString:t', 940), mail('hasOwnProperty:h', 930),
      mail('work:a', 900)], false, NOW + 60);
  assert.deepEqual(fresh(first), []);
  const later = state.arrivals(first.state, boxes,
    [mail('constructor:d', 990), mail('constructor:c', 950), mail('toString:t', 940),
      mail('hasOwnProperty:h', 930), mail('work:a', 900)], false, NOW + 120);
  assert.deepEqual(fresh(later), ['constructor:d']);
});

test('an account dropped from inboxes loses its state and re-baselines on return', () => {
  const both = [inbox('work'), inbox('home')];
  const base = state.arrivals(null, both,
    [mail('work:a', 900), mail('home:h', 800)], false, NOW);
  const dropped = state.arrivals(base.state, [inbox('work')],
    [mail('work:a', 900)], false, NOW + 60);
  const back = state.arrivals(dropped.state, both,
    [mail('home:i', 950), mail('work:a', 900), mail('home:h', 800)], false, NOW + 120);
  assert.deepEqual(fresh(back), []);
});

test('arrivals leaves the previous state untouched', () => {
  const base = state.arrivals(null, [inbox('work'), inbox('home'), inbox('gone')],
    [mail('work:a', 900), mail('gone:g', 850), mail('home:h', 800)], true, NOW);
  const before = JSON.stringify(base.state);
  state.arrivals(base.state, [inbox('work'), inbox('home', false)],
    [mail('work:b', 950), mail('work:a', 900)], false, NOW + 60);
  assert.equal(JSON.stringify(base.state), before);
});

test('seen keeps the 200 most recently seen IDs, including those still on page 1', () => {
  const boxes = [inbox('work')];
  const pinned = mail('work:pinned', 900);
  let result = state.arrivals(null, boxes, [pinned, mail('work:m0', 900)], false, NOW);
  for (let k = 1; k <= 200; k++)
    result = state.arrivals(result.state, boxes, [pinned, mail(`work:m${k}`, 900)], false, NOW);
  // 202 IDs seen in all: m0 and m1 were seen longest ago; pinned is seen every time.
  const last = state.arrivals(result.state, boxes,
    [pinned, mail('work:m0', 900), mail('work:m1', 900), mail('work:m2', 900)], false, NOW);
  assert.deepEqual(fresh(last), ['work:m0', 'work:m1']);
});
