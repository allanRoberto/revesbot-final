// Serviço bet_ws: captura o WebSocket da mesa e envia apostas (lpbet), por sessão.
//
// O app (apps/app) resolve o link da mesa (startGame, já autenticado) e chama:
//   POST   /session            { gameLink, rouletteId }  -> { sessionId }
//   GET    /session/:id/state                            -> estado da mesa
//   POST   /session/:id/bet    { numbers, chipValue }    -> envia aposta real
//   DELETE /session/:id                                  -> encerra a sessão
//
// Segurança: aceita só chamadas com o header X-Bet-Token == BET_WS_TOKEN
// (o app injeta esse token server-side; nunca vai ao browser).

const express = require('express');
const { SessionManager } = require('./lib/sessionManager');

const PORT = Number(process.env.BET_WS_PORT || 4060);
const HOST = process.env.BET_WS_HOST || '127.0.0.1';
const BASE_CHIP = Number(process.env.BASE_CHIP || 0.5);
const SHARED_TOKEN = process.env.BET_WS_TOKEN || null;

if (process.env.NODE_ENV === 'production' && !SHARED_TOKEN) {
  throw new Error('BET_WS_TOKEN é obrigatório em produção.');
}

const manager = new SessionManager();
const app = express();
app.use(express.json());

// Auth simples entre app <-> serviço (server-to-server).
app.use((req, res, next) => {
  if (req.path === '/health') return next();
  if (SHARED_TOKEN && req.get('X-Bet-Token') !== SHARED_TOKEN) {
    return res.status(401).json({ error: 'unauthorized' });
  }
  next();
});

app.get('/health', (_req, res) => res.json({ status: 'ok', service: 'bet-ws' }));

function ownedSession(req, res) {
  const ownerKey = req.get('X-Bet-Owner');
  if (!ownerKey) {
    res.status(403).json({ error: 'owner_required' });
    return null;
  }
  const session = manager.get(req.params.id, ownerKey);
  if (!session) {
    res.status(404).json({ error: 'session_not_found' });
    return null;
  }
  return session;
}

app.post('/session', async (req, res) => {
  try {
    const { gameLink, rouletteId, clientKey } = req.body || {};
    if (!gameLink) {
      return res.status(400).json({ error: 'gameLink é obrigatório.' });
    }
    const session = await manager.create({ gameLink, rouletteId, clientKey });
    return res.json(session.state());
  } catch (err) {
    console.error('[POST /session]', err.message);
    return res.status(500).json({ error: err.message });
  }
});

app.get('/session/:id/state', (req, res) => {
  const session = ownedSession(req, res);
  if (!session) return;
  return res.json(session.state());
});

// SSE: empurra o estado da mesa (fase, últimos números) em tempo real.
app.get('/session/:id/events', (req, res) => {
  const session = ownedSession(req, res);
  if (!session) return;

  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });

  const send = (event, data) => {
    res.write(`event: ${event}\n`);
    res.write(`data: ${JSON.stringify(data)}\n\n`);
  };

  send('state', session.state()); // snapshot inicial
  const onState = (s) => send('state', s);
  const onResult = (n) => send('result', { number: n });
  const onLog = (l) => send('log', l);
  session.on('state', onState);
  session.on('result', onResult);
  session.on('log', onLog);

  // keep-alive (evita timeout de proxies)
  const ping = setInterval(() => res.write(': ping\n\n'), 15000);

  req.on('close', () => {
    clearInterval(ping);
    session.off('state', onState);
    session.off('result', onResult);
    session.off('log', onLog);
  });
});

app.post('/session/:id/bet', (req, res) => {
  const session = ownedSession(req, res);
  if (!session) return;
  if (session.automation && ['running', 'stopping'].includes(session.automation.status)) {
    return res.status(409).json({ error: 'Desligue o automático antes de apostar manualmente.' });
  }
  try {
    const { bets, numbers, chipValue } = req.body || {};
    // Formato novo: { bets: { numero: valor } }. Legado: { numbers, chipValue }.
    let slip = bets;
    if (!slip && Array.isArray(numbers)) {
      const value = chipValue !== undefined ? Number(chipValue) : BASE_CHIP;
      slip = Object.fromEntries(numbers.map((n) => [n, value]));
    }
    const result = session.bet(slip || {});
    return res.json({ ok: true, ...result, state: session.state() });
  } catch (err) {
    return res.status(409).json({ error: err.message });
  }
});

app.post('/session/:id/automation/start', (req, res) => {
  const session = ownedSession(req, res);
  if (!session) return;
  try {
    const state = session.startAutomation(req.body || {});
    return res.json({ ok: true, automation: state, state: session.state() });
  } catch (err) {
    return res.status(409).json({ error: err.message });
  }
});

app.post('/session/:id/automation/stop', async (req, res) => {
  const session = ownedSession(req, res);
  if (!session) return;
  try {
    const state = await session.stopAutomation('user_stop');
    return res.json({ ok: true, automation: state, state: session.state() });
  } catch (err) {
    return res.status(409).json({ error: err.message });
  }
});

app.delete('/session/:id', (req, res) => {
  const session = ownedSession(req, res);
  if (!session) return;
  const ok = manager.destroy(req.params.id);
  return res.json({ ok });
});

const server = app.listen(PORT, HOST, () => {
  console.log(`bet_ws ouvindo em http://${HOST}:${PORT}`);
  console.log(`BASE_CHIP=${BASE_CHIP} | auth=${SHARED_TOKEN ? 'on' : 'off'}`);
});

function shutdown(signal) {
  console.log(`[shutdown] ${signal}`);
  server.close(() => manager.destroyAll());
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
