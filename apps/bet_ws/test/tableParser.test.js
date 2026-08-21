const test = require('node:test');
const assert = require('node:assert/strict');

const { parseTimerValue, parseCountdownSeconds } = require('../lib/tableParser');

test('preserva snapshots positivos, zero e negativos do timer', () => {
  assert.equal(parseTimerValue('{"timer":{"type":"auto","value":"19"}}'), 19);
  assert.equal(parseTimerValue('{"timer":{"type":"auto","value":"0"}}'), 0);
  assert.equal(parseTimerValue('{"timer":{"type":"auto","value":"-11"}}'), -11);
});

test('contador de apostas aceita apenas snapshots não negativos', () => {
  assert.equal(parseCountdownSeconds('{"timer":{"type":"auto","value":"19"}}'), 19);
  assert.equal(parseCountdownSeconds('{"timer":{"type":"auto","value":"0"}}'), 0);
  assert.equal(parseCountdownSeconds('{"timer":{"type":"auto","value":"-11"}}'), null);
});
