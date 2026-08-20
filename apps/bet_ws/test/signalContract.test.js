const test = require('node:test');
const assert = require('node:assert/strict');
const { normalizeAutomaticSignal } = require('../lib/signalContract');

test('normaliza o contrato futuro da central de sinais', () => {
  const signal = normalizeAutomaticSignal({
    signal_id: 'signal-123',
    roulette_id: 'pragmatic-auto-roulette',
    bet: [7, '7', 11, 99],
    timestamp: '2026-07-29T12:00:00.000Z',
  });
  assert.equal(signal.signalId, 'signal-123');
  assert.equal(signal.rouletteId, 'pragmatic-auto-roulette');
  assert.deepEqual(signal.numbers, [7, 11]);
});

test('rejeita sinais sem números válidos', () => {
  assert.throws(
    () =>
      normalizeAutomaticSignal({
        id: 'signal-empty',
        roulette_id: 'pragmatic-auto-roulette',
        numbers: [],
      }),
    /signal_numbers_required/,
  );
});

