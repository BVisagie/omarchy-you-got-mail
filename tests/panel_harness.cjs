const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Execute the actual panel methods against fake process/UI objects. No mail,
// compositor, browser or account configuration is touched by these tests.
module.exports = function panelHarness() {
  const source = fs.readFileSync(path.join(__dirname, '../Panel.qml'), 'utf8');
  const state = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../MailState.js'), 'utf8')
    .replace(/^\.pragma library\s*/, ''), state);
  const panel = vm.createContext({
    MailState: state,
    messages: [], unread: 0, dismissedIds: {}, pendingId: '', readQueue: [],
    mailboxRevision: 0, listRevision: 0, listPage: '', pageToken: '', pageStack: [],
    nextPage: '', accountCount: 0, cursor: 0, opened: true,
    markAllBusy: false, markAllArmed: false, reconciling: false,
    readExited: false, readOutputReady: false, readOutput: '', readExitCode: 0,
    readStarted: false,
    refreshPending: false, actionWarning: '', warningText: '', failures: [],
    inboxes: [], accountChecks: {}, allCheckedAt: 0, accountSignature: '', now: 0,
    auxiliaryView: '', menuCursor: -1, savedMessageId: '',
    auxiliaryMenu: {contentY: 0, contentHeight: 500, height: 100, revealCursor() {}},
    keyCatcher: {forceActiveFocus() {}}, Style: {space(value) {return value;}},
    reachable: true, hasUnread: true, pageSize: 25, script: '/test/you-got-mail',
    arrivalState: null, soundEnabled: false, soundCooldownSec: 60, soundVolume: 100, soundFile: '',
    listProc: {running: false}, readProc: {running: false}, readAllProc: {running: false},
    markAllArmTimer: {running: false, stop() {}, restart() {}},
    list: {positionViewAtIndex() {}}, ListView: {Contain: 0},
    close() { panel.opened = false; panel.openedChanged(); },
    Util: {execArgv() {}, shellQuote(value) { return "'" + value.replaceAll("'", "'\\''") + "'"; }},
  });
  panel.root = panel;
  Object.defineProperty(panel, 'readBusy', {get() { return panel.pendingId !== '' || panel.readQueue.length > 0; }});
  Object.defineProperty(panel, 'hasPrev', {get() { return panel.pageStack.length > 0; }});
  Object.defineProperty(panel, 'accountMenu', {get() {
    return state.accountEntries(panel.inboxes, panel.accountChecks, panel.now);
  }});
  const methods = [...source.matchAll(/^  function \w+\([^\n]*\) \{[\s\S]*?^  \}/gm)]
    .map(match => match[0]).join('\n');
  vm.runInContext(methods, panel);
  const changed = source.match(/  onOpenedChanged: (\{[\s\S]*?^  \})/m)[1];
  vm.runInContext('function openedChanged() ' + changed, panel);
  return panel;
};
