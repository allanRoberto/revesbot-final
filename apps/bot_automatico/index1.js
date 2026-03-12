import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import cookieParser from 'cookie-parser';
import axios from 'axios';
import { createServer } from 'http';
import WebSocket, { WebSocketServer } from 'ws';
import puppeteer from 'puppeteer';
import { randomUUID } from 'crypto';
import url from 'url';

// =========================
// CONFIGURAÇÕES
// =========================

const AUTH_BASE_URL = process.env.AUTH_BASE_URL || 'https://auth.revesbot.com.br';
const PORT = Number(process.env.PORT || 3090);

// =========================
// GERENCIADOR DE COOKIES
// =========================

class CookieManager {
  constructor() {
    this.cookies = {};
  }

  extractCookies(setCookieHeaders) {
    if (!setCookieHeaders) return;

    const cookieArray = Array.isArray(setCookieHeaders)
      ? setCookieHeaders
      : [setCookieHeaders];

    cookieArray.forEach((cookie) => {
      if (!cookie) return;
      const [nameValue] = cookie.split(';');
      if (!nameValue) return;
      const [name, value] = nameValue.split('=');
      if (!name) return;
      this.cookies[name.trim()] = (value || '').trim();
    });
  }

  getCookieHeader() {
    const parts = Object.entries(this.cookies).map(
      ([name, value]) => `${name}=${value}`
    );
    return parts.join('; ');
  }
}

// =========================
/* SESSÕES EM MEMÓRIA
// =========================
//
// sessions: Map<sessionToken, {
//   email: string,
//   password: string,
//   authToken: string,
//   cookies: CookieManager,
//   tables: Map<tableKey, TableConnection>
// }>
//
// TableConnection:
// {
//   slug: string,
//   gameId: string,
//   wsUrl: string,
//   ws: WebSocket,
//   isBetsOpen: boolean,
//   game: string | null,
//   table: string | null,
//   clients: Set<WebSocket>
// }
*/

const sessions = new Map();

// =========================
// FUNÇÕES DE LOGIN E JOGO
// =========================

async function loginAtAuth(email, password, cookieManager) {
  const urlLogin = `${AUTH_BASE_URL}/api/auth/login`;
  const payload = { email, password };

  const response = await axios.post(urlLogin, payload, {
    timeout: 15000,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
  });

  cookieManager.extractCookies(response.headers['set-cookie'] || []);

  const data = response.data || {};
  const token = data.token || data.access_token || null;

  if (!token) {
    throw new Error('Login OK, mas nenhum token foi retornado pelo serviço de auth.');
  }

  return token;
}

async function getWebSocketUrlWithPuppeteer(gameLink) {
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  try {
    const page = await browser.newPage();
    await page.setUserAgent(
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    );

    const webSocketUrls = [];

    await page.evaluateOnNewDocument(() => {
      const originalWebSocket = window.WebSocket;
      window.WebSocket = new Proxy(originalWebSocket, {
        construct(target, args) {
          const url = args[0];
          console.log('WS_INTERCEPTED:', url);
          window.__wsUrls = window.__wsUrls || [];
          window.__wsUrls.push(url);
          return new target(...args);
        },
      });
    });

    page.on('console', (msg) => {
      const text = msg.text();
      if (text.includes('WS_INTERCEPTED:')) {
        const url = text.split('WS_INTERCEPTED:')[1].trim();
        webSocketUrls.push(url);
      }
    });

    page.on('websocket', (ws) => {
      webSocketUrls.push(ws.url());
    });

    await page.goto(gameLink, { waitUntil: 'networkidle2', timeout: 60000 });
    await new Promise((resolve) => setTimeout(resolve, 3000));

    const capturedUrls = await page.evaluate(() => window.__wsUrls || []);
    const allUrls = [...new Set([...capturedUrls, ...webSocketUrls])];

    if (allUrls.length === 0) {
      throw new Error('Nenhuma URL de WebSocket encontrada na página do jogo.');
    }

    const pragmaticUrl =
      allUrls.find(
        (u) =>
          u.includes('pragmatic') ||
          u.includes('livecasino') ||
          u.includes('game'),
      ) || allUrls[0];

    return pragmaticUrl;
  } finally {
    await browser.close();
  }
}

async function getGameLink(slug, gameId, session) {
  const urlStartGame = `${AUTH_BASE_URL}/api/start-game/${slug}/${gameId}`;

  const response = await axios.get(urlStartGame, {
    timeout: 15000,
    headers: {
      Accept: 'application/json',
      Authorization: session.authToken ? `Bearer ${session.authToken}` : undefined,
      Cookie: session.cookies.getCookieHeader() || undefined,
    },
  });

  session.cookies.extractCookies(response.headers['set-cookie'] || []);

  const data = response.data || {};
  const gameLink =
    data.gameUrl || data.iframeUrl || data.url || data.link || null;

  if (!gameLink) {
    throw new Error('gameUrl/iframeUrl não encontrado na resposta do /api/start-game.');
  }

  return gameLink;
}

// =========================
// PARSE DE MENSAGENS XML
// =========================

function parseBetsOpenInfo(xml) {
  const gameMatch = xml.match(/game="([^"]+)"/);
  const tableMatch = xml.match(/table="([^"]+)"/);
  return {
    game: gameMatch ? gameMatch[1] : null,
    table: tableMatch ? tableMatch[1] : null,
  };
}

function isBetsOpenMessage(text) {
  const t = text.toLowerCase();
  return t.includes('<betsopen');
}

function isBetsClosedMessage(text) {
  const t = text.toLowerCase();
  return t.includes('<betsclosed');
}

// =========================
// WEBSOCKET DA MESA (UPSTREAM)
// =========================

function attachTableWebSocketHandlers(session, tableConn) {
  const { ws } = tableConn;

  ws.on('open', () => {
    console.log(
      `[table-ws] Conectado à mesa slug=${tableConn.slug} gameId=${tableConn.gameId}`,
    );
  });

  ws.on('message', (data) => {
    const text = data.toString();

    if (isBetsOpenMessage(text)) {
      const info = parseBetsOpenInfo(text);
      tableConn.isBetsOpen = true;
      tableConn.game = info.game;
      tableConn.table = info.table;
      console.log(
        `[table-ws] Apostas ABERTAS (game=${info.game || '?'} table=${
          info.table || '?'
        })`,
      );
    } else if (isBetsClosedMessage(text)) {
      tableConn.isBetsOpen = false;
      console.log('[table-ws] Apostas FECHADAS');
    }

    // Repassa a mensagem bruta para todos os clientes conectados nessa mesa
    tableConn.clients.forEach((client) => {
      if (client.readyState === 1) {
        client.send(text);
      }
    });
  });

  ws.on('close', (code, reason) => {
    console.log(
      `[table-ws] Conexão fechada (slug=${tableConn.slug}, gameId=${
        tableConn.gameId
      }) code=${code} reason=${reason.toString()}`,
    );
    tableConn.isBetsOpen = false;
    tableConn.ws = null;
  });

  ws.on('error', (err) => {
    console.error(
      `[table-ws] Erro na mesa slug=${tableConn.slug} gameId=${tableConn.gameId}:`,
      err.message,
    );
  });
}

async function ensureTableConnection(sessionToken, slug, gameId, clientWs) {
  const session = sessions.get(sessionToken);
  if (!session) {
    throw new Error('Sessão não encontrada. Faça login primeiro.');
  }

  const tableKey = `${slug}:${gameId}`;
  let tableConn = session.tables.get(tableKey);

  if (tableConn && tableConn.ws && tableConn.ws.readyState === 1) {
    tableConn.clients.add(clientWs);
    return tableConn;
  }

  // Sempre garante um login fresco com as credenciais salvas
  session.authToken = await loginAtAuth(
    session.email,
    session.password,
    session.cookies,
  );

  const gameLink = await getGameLink(slug, gameId, session);
  const wsUrl = await getWebSocketUrlWithPuppeteer(gameLink);

  const ws = new WebSocket(wsUrl);

  tableConn = {
    slug,
    gameId,
    wsUrl,
    ws,
    isBetsOpen: false,
    game: null,
    table: null,
    clients: new Set(),
  };

  tableConn.clients.add(clientWs);
  session.tables.set(tableKey, tableConn);
  attachTableWebSocketHandlers(session, tableConn);

  return tableConn;
}

// =========================
// EXPRESS + HTTP SERVER
// =========================

const app = express();

app.use(
  cors({
    origin: true,
    credentials: true,
  }),
);
app.use(express.json({ limit: '10mb' }));
app.use(cookieParser());

// POST /login
// body: { email, password }
app.post('/login', async (req, res) => {
  try {
    const { email, password } = req.body || {};
    if (!email || !password) {
      return res.status(400).json({
        error: 'missing_credentials',
        message: 'Informe email e password no corpo da requisição.',
      });
    }

    const cookies = new CookieManager();
    const authToken = await loginAtAuth(email, password, cookies);

    const sessionToken = randomUUID();
    sessions.set(sessionToken, {
      email,
      password,
      authToken,
      cookies,
      tables: new Map(),
    });

    console.log(`[login] Sessão criada para ${email}, token=${sessionToken}`);

    return res.json({
      ok: true,
      token: sessionToken,
    });
  } catch (err) {
    console.error('[login] Erro:', err);
    return res.status(401).json({
      error: 'login_failed',
      message: err.message || 'Falha ao autenticar.',
    });
  }
});

// POST /bet
// body: { token, slug, gameId, numbers: number[], chipValue?: number }
app.post('/bet', async (req, res) => {
  try {
    const { token, slug, gameId, numbers, chipValue } = req.body || {};

    if (!token || !slug || !gameId) {
      return res.status(400).json({
        error: 'missing_params',
        message: 'Campos token, slug e gameId são obrigatórios.',
      });
    }

    const session = sessions.get(token);
    if (!session) {
      return res.status(401).json({
        error: 'invalid_session',
        message: 'Sessão inválida. Faça login novamente.',
      });
    }

    if (!Array.isArray(numbers) || numbers.length === 0) {
      return res.status(400).json({
        error: 'invalid_numbers',
        message: "Campo 'numbers' deve ser um array com ao menos 1 número.",
      });
    }

    const value = chipValue !== undefined ? Number(chipValue) : 0.5;
    if (!Number.isFinite(value) || value <= 0) {
      return res.status(400).json({
        error: 'invalid_chip_value',
        message: 'chipValue inválido.',
      });
    }

    const tableKey = `${slug}:${gameId}`;
    const tableConn = session.tables.get(tableKey);

    if (!tableConn || !tableConn.ws || tableConn.ws.readyState !== 1) {
      return res.status(409).json({
        error: 'table_not_connected',
        message:
          'Mesa não está conectada. Conecte primeiro via WebSocket antes de apostar.',
      });
    }

    if (!tableConn.isBetsOpen) {
      return res.status(409).json({
        error: 'bets_closed',
        message: 'Apostas não estão abertas no momento.',
      });
    }

    if (!tableConn.game || !tableConn.table) {
      return res.status(409).json({
        error: 'missing_game_info',
        message:
          'Informações da mesa (game/table) ainda não foram recebidas. Aguarde o próximo <betsopen>.',
      });
    }

    const betsXml = numbers
      .map((n) => {
        const num = Number(n);
        if (!Number.isFinite(num) || num < 0 || num > 36) {
          throw new Error(`Número inválido para aposta: ${n}`);
        }
        return `<bet outcome="straightup" number="${num}" stake="${value.toFixed(
          2,
        )}" />`;
      })
      .join('');

    const checksum = Date.now().toString();

    const xml = `<lpbet checksum="${checksum}" game="${tableConn.game}" table="${tableConn.table}">
${betsXml}
</lpbet>`;

    console.log('[bet] Enviando aposta:\n', xml);

    tableConn.ws.send(xml);

    return res.json({
      ok: true,
      slug,
      gameId,
      numbers,
      chipValue: value,
    });
  } catch (err) {
    console.error('[bet] Erro:', err);
    return res.status(500).json({
      error: 'internal_error',
      message: err.message || 'Erro interno ao enviar aposta.',
    });
  }
});

// HEALTHCHECK SIMPLES
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    sessions: sessions.size,
  });
});

// =========================
// WEBSOCKET SERVER
// =========================
//
// URL de conexão esperada pelo front:
//   ws://HOST:PORT/ws?token=...&slug=...&gameId=...
//
// - token: retornado pela rota /login
// - slug: slug da mesa (ex: pragmatic-brazilian-roulette)
// - gameId: id da mesa

const server = createServer(app);
const wss = new WebSocketServer({ server });

wss.on('connection', async (ws, req) => {
  try {
    const parsed = url.parse(req.url, true);
    const { token, slug, gameId } = parsed.query || {};

    if (!token || !slug || !gameId) {
      console.warn('[ws] Conexão sem token/slug/gameId. Fechando.');
      ws.close(1008, 'Parâmetros obrigatórios ausentes.');
      return;
    }

    const session = sessions.get(token);
    if (!session) {
      console.warn('[ws] Sessão inválida para token:', token);
      ws.close(1008, 'Sessão inválida. Faça login novamente.');
      return;
    }

    console.log(
      `[ws] Novo cliente conectado. token=${token} slug=${slug} gameId=${gameId}`,
    );

    // Garante que a conexão com a mesa esteja ativa
    const tableConn = await ensureTableConnection(token, slug, gameId, ws);

    // Quando o cliente fechar, removemos da lista de clientes dessa mesa
    ws.on('close', () => {
      tableConn.clients.delete(ws);
      console.log(
        `[ws] Cliente desconectado. slug=${slug} gameId=${gameId}`,
      );
    });

    ws.on('error', (err) => {
      console.error('[ws] Erro no cliente WS:', err.message);
    });
  } catch (err) {
    console.error('[ws] Erro na conexão WS:', err);
    try {
      ws.close(1011, 'Erro interno no servidor.');
    } catch (_) {}
  }
});

// =========================
// INICIALIZAÇÃO
// =========================

server.listen(PORT, () => {
  console.log(`HTTP + WS server rodando na porta ${PORT}`);
  console.log(`AUTH_BASE_URL: ${AUTH_BASE_URL}`);
});