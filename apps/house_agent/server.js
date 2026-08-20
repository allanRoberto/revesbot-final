// house-agent: resolve o link do jogo (e saldo) para casas do modo navegador
// (Esportiva, Bateu…), fazendo login headless que passa Cloudflare/Turnstile.
//
//   POST /game-link  { house, email, password, slug }  -> { gameURL, balance }
//
// Server-to-server: exige header X-Agent-Token == AGENT_TOKEN (o app injeta).
// Roda no servidor de mídia (tem Chromium e passa o Cloudflare).

const express = require('express');
const { getGameLink } = require('./lib/browserLogin');
const { domainFor } = require('./lib/houses');

const PORT = Number(process.env.HOUSE_AGENT_PORT || 4080);
const HOST = process.env.HOUSE_AGENT_HOST || '127.0.0.1';
const TOKEN = process.env.AGENT_TOKEN || null;

if (process.env.NODE_ENV === 'production' && !TOKEN) {
  throw new Error('AGENT_TOKEN é obrigatório em produção.');
}

// Uma operação headless de cada vez por padrão (Chromium é pesado); fila simples.
const MAX_CONCURRENT = Number(process.env.MAX_CONCURRENT || 2);
let running = 0;
const queue = [];
function withSlot(fn) {
  return new Promise((resolve, reject) => {
    const run = () => {
      running++;
      fn().then(resolve, reject).finally(() => {
        running--;
        const next = queue.shift();
        if (next) next();
      });
    };
    if (running < MAX_CONCURRENT) run();
    else queue.push(run);
  });
}

const app = express();
app.use(express.json());
app.use((req, res, next) => {
  if (req.path === '/health') return next();
  if (TOKEN && req.get('X-Agent-Token') !== TOKEN) {
    return res.status(401).json({ error: 'unauthorized' });
  }
  next();
});

app.get('/health', (_req, res) => res.json({ status: 'ok', running, queued: queue.length }));

app.post('/game-link', async (req, res) => {
  const { house, email, password, slug } = req.body || {};
  const domain = domainFor(house);
  if (!domain) return res.status(400).json({ error: 'casa não suportada no modo navegador.' });
  if (!email || !password || !slug) {
    return res.status(400).json({ error: 'email, password e slug são obrigatórios.' });
  }
  try {
    const out = await withSlot(() => getGameLink({ domain, email, password, slug }));
    return res.json({ ok: true, ...out });
  } catch (err) {
    console.error('[game-link]', house, err.message);
    return res.status(502).json({ error: err.message });
  }
});

const server = app.listen(PORT, HOST, () => {
  console.log(`house-agent ouvindo em http://${HOST}:${PORT} | auth=${TOKEN ? 'on' : 'off'}`);
});

function shutdown(signal) {
  console.log(`[shutdown] ${signal}`);
  server.close((error) => {
    if (error) {
      console.error('[shutdown]', error);
      process.exitCode = 1;
    }
  });
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
