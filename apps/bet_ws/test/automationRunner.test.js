const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');

process.env.AUTOMATION_INTERNAL_TOKEN = 'test-token';
process.env.AUTOMATION_APP_URL = 'http://app.test';

const { AutomationRunner } = require('../lib/automationRunner');

class FakeSession extends EventEmitter {
  constructor() {
    super();
    this.gameInfo = { game: 'round-1', table: 'table-1' };
    this.betsOpen = false;
    this.sent = [];
  }

  bet(bets) {
    this.sent.push(bets);
  }

  emitState() {}
}

test('liquida aposta vencedora e para ao atingir a meta', async (t) => {
  const originalFetch = global.fetch;
  t.after(() => {
    global.fetch = originalFetch;
  });
  const events = [];
  global.fetch = async (url, options = {}) => {
    if (String(url).includes('/suggestion')) {
      return Response.json({ numbers: [1, 2] });
    }
    events.push(JSON.parse(options.body));
    return Response.json({ ok: true });
  };

  const session = new FakeSession();
  const runner = new AutomationRunner(session, {
    runId: 'run-1',
    gameId: '373',
    targetProfitCents: 1000,
    maxLossCents: 5000,
    chipValueCents: 50,
  });

  await runner.onBetsOpen();
  assert.deepEqual(session.sent, [{ 1: 0.5, 2: 0.5 }]);

  await runner.onResult(1);
  assert.equal(runner.netProfitCents, 1700);
  assert.equal(runner.status, 'stopped');
  assert.equal(events[0].event, 'round_settled');
  assert.equal(events[0].payoutCents, 1800);
  assert.equal(events[0].netProfitCents, 1700);
  assert.equal(events[1].event, 'run_stopped');
  assert.equal(events[1].reason, 'target_reached');
});

test('parada manual espera a liquidação da aposta pendente', async (t) => {
  const originalFetch = global.fetch;
  t.after(() => {
    global.fetch = originalFetch;
  });
  const events = [];
  global.fetch = async (url, options = {}) => {
    if (String(url).includes('/suggestion')) {
      return Response.json({ numbers: [7] });
    }
    events.push(JSON.parse(options.body));
    return Response.json({ ok: true });
  };

  const session = new FakeSession();
  const runner = new AutomationRunner(session, {
    runId: 'run-2',
    gameId: '373',
    targetProfitCents: 10000,
    maxLossCents: 10000,
    chipValueCents: 50,
  });

  await runner.onBetsOpen();
  const stopping = await runner.stop('user_stop');
  assert.equal(stopping.status, 'stopping');
  assert.equal(events.length, 0);

  await runner.onResult(0);
  assert.equal(runner.netProfitCents, -50);
  assert.equal(runner.status, 'stopped');
  assert.equal(events[0].event, 'round_settled');
  assert.equal(events[1].reason, 'user_stop');
});

