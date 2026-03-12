// bot_auto.js
// Executor de apostas: conecta na mesa da Pragmatic via WebSocket,
// expõe:
//   - WebSocket de STATUS para o front (sugestao.html)
//   - API HTTP para login e para receber números e enviar a aposta.
//
// Novo fluxo:
//
//   1) Front faz POST HTTP para login:
//        POST /api/login  { email, password, slug? }
//      - Se OK, a API faz login na casa de apostas (via AUTH_BASE_URL)
//      - Gera um token de sessão interno e devolve para o front:
//        { ok: true, token: "<sessionToken>" }
//
//   2) Com o token em mãos, o front conecta no WS de status (STATUS_PORT).
//
//   3) Front envia mensagem no WS:
//        { type: "init_session", token, slug, gameId, rouletteId? }
//
//   4) Este bot, já autenticado (authToken em memória), usa o slug/gameId
//      para chamar /api/start-game, descobre a URL de WebSocket da mesa
//      (via Puppeteer) e conecta.
//
//   5) Quando a mesa emite <betsopen>, <betsclosingsoon>, <betsclosed>, <gameresult>,
//      o bot transmite eventos para TODOS os clientes do WS de status.
//
//   6) Quando o front quiser apostar, chama o HTTP:
//        POST /api/external-bet  { numbers: [0..36], chipValue? }
//
// ATENÇÃO:
//   - Este arquivo NÃO consulta API de sugestão e NÃO aposta sozinho.
//   - Apenas executa a aposta nos números recebidos quando as apostas estiverem abertas.
//
// Requisitos:
//   npm install dotenv axios ws express puppeteer
//
// Variáveis de ambiente usadas (apenas parâmetros gerais, não credenciais):
//   AUTH_BASE_URL  -> ex: https://auth.revesbot.com.br
//   AUTH_SLUG      -> slug default opcional (pode vir do front também)
//   AUTH_EMAIL     -> email default opcional (fallback se front não mandar)
//   AUTH_PASSWORD  -> password default opcional (fallback)
//   BASE_CHIP      -> valor padrão de ficha por número (ex: 0.5)
//   STATUS_PORT    -> porta do WS de status (default 4050)
//   BET_HTTP_PORT  -> porta do HTTP de aposta (default 4051)
//   ROULETTE_ID    -> id padrão da roleta (apenas para log/front)

require("dotenv").config();

const axios = require("axios");
const WebSocket = require("ws");
const puppeteer = require("puppeteer");
const express = require("express");
const { randomUUID } = require("crypto");

// =========================
// CONFIG GLOBAL (NÃO SESSÃO)
// =========================

const AUTH_BASE_URL =
  process.env.AUTH_BASE_URL || "https://auth.revesbot.com.br";

const DEFAULT_AUTH_EMAIL = process.env.AUTH_EMAIL || null;
const DEFAULT_AUTH_PASSWORD = process.env.AUTH_PASSWORD || null;
const DEFAULT_AUTH_SLUG = process.env.AUTH_SLUG || null;

const BASE_CHIP = Number(process.env.BASE_CHIP || 0.5);
const STATUS_PORT = Number(process.env.STATUS_PORT || 4050);
const BET_HTTP_PORT = Number(process.env.BET_HTTP_PORT || 4051);

const DEFAULT_ROULETTE_ID =
  process.env.ROULETTE_ID || "pragmatic-brazilian-roulette";

const RECONNECT_DELAY_MS = 2000;

// =========================
// ESTADO DA SESSÃO ATUAL
// =========================

// Credenciais/parametros atuais (vindos do login + front)
let sessionEmail = null;
let sessionPassword = null;
let sessionSlug = null;
let sessionGameId = null;
let sessionRouletteId = DEFAULT_ROULETTE_ID;

// Controle de login
let authToken = null;           // token do auth (casa de apostas)
let isLoggedIn = false;         // indica se já foi feito login com sucesso
let loginSessionToken = null;   // token exposto para o front (sessionId)

// Controle da mesa
let tableWs = null;        // WebSocket da mesa Pragmatic
let gameWsUrl = null;      // URL do WebSocket da mesa
let lastGameInfo = null;   // { game, table } extraído do <betsopen ...>
let isBetsOpen = false;    // flag se a mesa está aberta
let isConnectingSession = false; // evita corrida em init_session

// ============================
// COOKIE MANAGER
// ============================

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
      const [nameValue] = cookie.split(";");
      if (!nameValue) return;
      const [name, value] = nameValue.split("=");
      if (!name) return;
      this.cookies[name.trim()] = value ? value.trim() : "";
    });
  }

  getCookieHeader() {
    const parts = Object.entries(this.cookies).map(
      ([name, value]) => `${name}=${value}`
    );
    return parts.join("; ");
  }
}

const cookieManager = new CookieManager();

// =========================
// AUXILIARES DE LOGIN / WS
// =========================

async function loginAndGetToken(email, password) {
  const finalEmail = email || sessionEmail || DEFAULT_AUTH_EMAIL;
  const finalPassword = password || sessionPassword || DEFAULT_AUTH_PASSWORD;

  if (!finalEmail || !finalPassword) {
    throw new Error(
      "Credenciais não definidas. Envie email/password em /api/login ou configure AUTH_EMAIL/AUTH_PASSWORD."
    );
  }

  console.log("[auth] Fazendo login no AUTH_BASE_URL...");
  const url = `${AUTH_BASE_URL}/api/auth/login`;
  const payload = { email: finalEmail, password: finalPassword };

  const response = await axios.post(url, payload, {
    timeout: 15000,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
  });

  cookieManager.extractCookies(response.headers["set-cookie"] || []);

  const data = response.data || {};
  const token = data.token || data.access_token || null;

  if (!token) {
    console.warn(
      "[auth] Login OK, mas nenhum token foi retornado. Verifique a API."
    );
  } else {
    console.log("[auth] Login OK. Token recebido.");
  }

  // Atualiza credenciais em memória (para fallback futuro, se necessário)
  sessionEmail = finalEmail;
  sessionPassword = finalPassword;

  return token;
}

// Abre o iframe da mesa com Puppeteer e intercepta a URL
// do WebSocket da Pragmatic.
async function getWebSocketUrlWithPuppeteer(gameLink) {
  console.log("[puppeteer] Abrindo página do jogo para capturar WebSocket...");

  const browser = await puppeteer.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  try {
    const page = await browser.newPage();
    await page.setUserAgent(
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    );

    const webSocketUrls = [];

    await page.evaluateOnNewDocument(() => {
      const originalWebSocket = window.WebSocket;
      window.WebSocket = new Proxy(originalWebSocket, {
        construct(target, args) {
          const url = args[0];
          window.__wsUrls = window.__wsUrls || [];
          window.__wsUrls.push(url);
          return new target(...args);
        },
      });
    });

    page.on("websocket", (ws) => {
      webSocketUrls.push(ws.url());
    });

    await page.goto(gameLink, {
      waitUntil: "networkidle2",
      timeout: 60000,
    });

    await new Promise((resolve) => setTimeout(resolve, 3000));

    const capturedUrls = await page.evaluate(() => window.__wsUrls || []);
    const allUrls = [...new Set([...capturedUrls, ...webSocketUrls])];

    if (allUrls.length === 0) {
      throw new Error(
        "Nenhuma URL de WebSocket encontrada na página do jogo."
      );
    }

    const pragmaticUrl =
      allUrls.find(
        (url) =>
          url.includes("pragmatic") ||
          url.includes("game?") ||
          url.includes("gs")
      ) || allUrls[0];

    console.log("[puppeteer] WebSocket da mesa capturado:", pragmaticUrl);
    return pragmaticUrl;
  } finally {
    await browser.close();
  }
}

// Usa o auth para obter o link do jogo (iframe) e, em seguida,
// captura a URL do WebSocket com o Puppeteer.
async function getGameWebSocketUrl(gameId, token) {
  if (!gameId) {
    throw new Error(
      "gameId não definido. Envie em init_session ou configure AUTH_GAME_ID."
    );
  }

  const slug = sessionSlug || DEFAULT_AUTH_SLUG;
  console.log("[auth] Buscando URL do WebSocket do game...");
  const url = slug
    ? `${AUTH_BASE_URL}/api/start-game/${slug}/${gameId}`
    : `${AUTH_BASE_URL}/api/start-game/${gameId}`;

  const response = await axios.get(url, {
    timeout: 15000,
    headers: {
      Accept: "application/json",
      Authorization: token ? `Bearer ${token}` : undefined,
      Cookie: cookieManager.getCookieHeader() || undefined,
    },
  });

  cookieManager.extractCookies(response.headers["set-cookie"] || []);

  const data = response.data || {};
  const gameLink =
    data.gameUrl || data.iframeUrl || data.url || data.link || null;

  if (!gameLink) {
    console.error(
      "[auth] Resposta do /api/start-game não possui gameUrl/iframeUrl."
    );
    throw new Error("gameUrl/iframeUrl não encontrado na resposta do auth.");
  }

  console.log("[auth] Link do jogo obtido:", gameLink);
  const wsUrl = await getWebSocketUrlWithPuppeteer(gameLink);
  return wsUrl;
}

// =========================
// PARSE DE MENSAGENS DA MESA
// =========================

function parseWinningNumber(message) {
  const text = message.toString();

  let m = text.match(/<gameresult[^>]*score="(\d+)"/i);
  if (m) {
    return parseInt(m[1], 10);
  }

  m = text.match(/<winning[^>]*number="(\d+)"/i);
  if (m) {
    return parseInt(m[1], 10);
  }

  return null;
}

function isBetsOpenMessage(message) {
  const text = message.toString().toLowerCase();
  return text.includes("<betsopen");
}

function isBetsClosingSoonMessage(message) {
  const text = message.toString().toLowerCase();
  return text.includes("<betsclosingsoon");
}

function isBetsClosedMessage(message) {
  const text = message.toString().toLowerCase();
  return text.includes("<betsclosed");
}

function parseBetsOpenMessage(xmlMessage) {
  const gameMatch = xmlMessage.match(/game="([^"]+)"/);
  const tableMatch = xmlMessage.match(/table="([^"]+)"/);
  return gameMatch && tableMatch
    ? { game: gameMatch[1], table: tableMatch[1] }
    : null;
}

// =========================
// WS DE STATUS PARA O FRONT
// =========================

let wssStatus = null;

function startStatusWebSocketServer() {
  if (wssStatus) return;

  wssStatus = new WebSocket.Server({ port: STATUS_PORT });
  console.log(
    `[status-ws] Servidor de status ouvindo em ws://0.0.0.0:${STATUS_PORT}`
  );

  wssStatus.on("connection", (client) => {
    console.log("[status-ws] Cliente conectado");

    // Envia status inicial da sessão
    client.send(
      JSON.stringify({
        type: "status_init",
        hasSession: !!gameWsUrl,
        isLoggedIn,
        isBetsOpen,
        lastGameInfo,
        rouletteId: sessionRouletteId,
      })
    );

    client.on("message", (raw) => {
      let msg = null;
      try {
        msg = JSON.parse(raw.toString());
      } catch (e) {
        console.warn("[status-ws] Mensagem inválida (não é JSON).");
        return;
      }

      if (!msg || typeof msg !== "object") return;

      if (msg.type === "init_session") {
        // Agora init_session exige token de sessão (retornado em /api/login)
        handleInitSession(msg, client);
      } else {
        console.log("[status-ws] Mensagem desconhecida:", msg.type);
      }
    });

    client.on("close", () => {
      console.log("[status-ws] Cliente desconectado");
    });
  });
}

function broadcastStatus(event) {
  if (!wssStatus || !wssStatus.clients) return;
  const payload = JSON.stringify(event);

  wssStatus.clients.forEach((client) => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(payload);
    }
  });
}

// =========================
// LÓGICA DE CONEXÃO NA MESA
// =========================

function handleTableMessage(data) {
  const text = data.toString();

  if (isBetsOpenMessage(text)) {
    const info = parseBetsOpenMessage(text);
    lastGameInfo = info;
    isBetsOpen = true;

    console.log(
      `[mesa] Apostas ABERTAS. game=${info?.game || "?"} table=${
        info?.table || "?"
      }`
    );

    broadcastStatus({
      type: "bets_open",
      game: info?.game || null,
      table: info?.table || null,
    });

    return;
  }

  if (isBetsClosingSoonMessage(text)) {
    console.log("[mesa] Apostas ENCERRANDO...");
    broadcastStatus({ type: "bets_closing_soon" });
    return;
  }

  if (isBetsClosedMessage(text)) {
    console.log("[mesa] Apostas FECHADAS.");
    isBetsOpen = false;
    broadcastStatus({ type: "bets_closed" });
    return;
  }

  const numero = parseWinningNumber(text);
  if (numero !== null && !Number.isNaN(numero)) {
    console.log(`[mesa] Número sorteado: ${numero}`);
    broadcastStatus({ type: "round_result", number: numero });
    return;
  }
}

function connectTableWebSocket() {
  if (!gameWsUrl) {
    console.error("[ws] gameWsUrl não definido. Não é possível conectar à mesa.");
    return;
  }

  console.log("[ws] Conectando ao WebSocket da mesa:", gameWsUrl);
  tableWs = new WebSocket(gameWsUrl);

  tableWs.on("open", () => {
    console.log("[ws] Conexão com a mesa ESTABELECIDA.");
    broadcastStatus({ type: "session_connected" });
  });

  tableWs.on("message", (data) => {
    handleTableMessage(data);
  });

  tableWs.on("close", (code, reason) => {
    console.log(
      `[ws] Conexão com a mesa FECHADA. code=${code} reason=${reason.toString()}`
    );
    broadcastStatus({
      type: "session_disconnected",
      code,
      reason: reason.toString(),
    });
    // tenta reconectar se ainda houver sessão configurada
    if (sessionGameId && authToken && !isConnectingSession) {
      setTimeout(connectTableWebSocket, RECONNECT_DELAY_MS);
    }
  });

  tableWs.on("error", (err) => {
    console.error("[ws] Erro no WebSocket da mesa:", err.message);
  });
}

// =========================
// INIT DA SESSÃO (via WS)
// =========================

async function handleInitSession(msg, client) {
  if (isConnectingSession) {
    client.send(
      JSON.stringify({
        type: "session_error",
        message: "Já existe uma sessão em processo de conexão.",
      })
    );
    return;
  }

  try {
    isConnectingSession = true;

    // Valida login prévio
    if (!isLoggedIn || !authToken || !loginSessionToken) {
      throw new Error(
        "Usuário não autenticado. Faça login em /api/login antes de iniciar a sessão."
      );
    }

    if (!msg.token || msg.token !== loginSessionToken) {
      throw new Error("Token de sessão inválido ou expirado.");
    }

    // fecha WS antigo, se houver
    if (tableWs) {
      try {
        tableWs.close();
      } catch (_) {}
      tableWs = null;
    }

    // reseta estado da mesa
    lastGameInfo = null;
    isBetsOpen = false;

    // atualiza parametros vindos do front
    sessionSlug = msg.slug || sessionSlug || DEFAULT_AUTH_SLUG;
    sessionGameId = msg.gameId || null;
    sessionRouletteId =
      msg.rouletteId || sessionRouletteId || DEFAULT_ROULETTE_ID;

    if (!sessionGameId) {
      throw new Error(
        "gameId não informado em init_session e AUTH_GAME_ID não está configurado."
      );
    }

    client.send(
      JSON.stringify({
        type: "session_starting",
        slug: sessionSlug,
        gameId: sessionGameId,
        rouletteId: sessionRouletteId,
      })
    );

    broadcastStatus({
      type: "session_config_updated",
      slug: sessionSlug,
      gameId: sessionGameId,
      rouletteId: sessionRouletteId,
    });

    // Já estamos logados (authToken em memória), apenas obtemos ws da mesa
    gameWsUrl = await getGameWebSocketUrl(sessionGameId, authToken);

    broadcastStatus({
      type: "session_ready",
      wsUrl: gameWsUrl,
    });

    // Conecta na mesa
    connectTableWebSocket();
  } catch (err) {
    console.error("[session] Erro em init_session:", err.message);
    client.send(
      JSON.stringify({
        type: "session_error",
        message: err.message || "Erro ao iniciar sessão.",
      })
    );
  } finally {
    isConnectingSession = false;
  }
}

// =========================
// ENVIO DE APOSTA (EXECUTOR)
// =========================

function generateChecksumTimestamp() {
  return Date.now().toString();
}

// bets: array de números (0-36)
// chipValue: valor de cada ficha
function sendBet(bets, chipValue) {
  if (!tableWs || tableWs.readyState !== WebSocket.OPEN) {
    throw new Error("WebSocket da mesa não está aberto.");
  }

  if (!isBetsOpen) {
    throw new Error("Apostas NÃO estão abertas no momento.");
  }

  if (!lastGameInfo) {
    throw new Error("Informações da mesa (game/table) desconhecidas.");
  }

  const valorAposta = Number(chipValue);
  if (!Number.isFinite(valorAposta) || valorAposta <= 0) {
    throw new Error("Valor de ficha inválido.");
  }

  const checksum = generateChecksumTimestamp();

  const betsXML = bets
    .map((num) => {
      const n = Number(num);
      if (!Number.isFinite(n) || n < 0 || n > 36) {
        throw new Error(`Número de aposta inválido: ${num}`);
      }
      const betCode = n === 0 ? 2 : n + 3;
      return `<bet amt="${valorAposta}" bc="${betCode}" ck="${checksum}" />`;
    })
    .join("");

  const message =
    `<command channel="table-${lastGameInfo.table}" >` +
    `<lpbet gm="roulette_desktop" gId="${lastGameInfo.game}" ck="${checksum}">` +
    betsXML +
    `</lpbet></command>`;

  console.log(
    `🎲 Enviando aposta | Números=[${bets.join(
      ", "
    )}] | Valor por número=${valorAposta}`
  );

  tableWs.send(message);
}

// =========================
// API HTTP PARA LOGIN + APOSTA
// =========================

function startBetHttpServer() {
  const app = express();
  app.use(express.json());

  // Rota de login: retorna token de sessão para uso no WebSocket
  app.post("/api/login", async (req, res) => {
    try {
      const { email, password, slug } = req.body || {};

      // Atualiza slug (pode ser default global)
      sessionSlug = slug || DEFAULT_AUTH_SLUG;

      // Faz login na casa de apostas via AUTH_BASE_URL
      const token = await loginAndGetToken(email, password);

      if (!token) {
        return res.status(500).json({
          error: "no_token",
          message:
            "Login realizado, mas nenhum token foi retornado pelo serviço de auth.",
        });
      }

      authToken = token;
      isLoggedIn = true;
      loginSessionToken = randomUUID();

      console.log(
        `[api] Login de usuário OK. sessionToken=${loginSessionToken}`
      );

      return res.json({
        ok: true,
        token: loginSessionToken,
      });
    } catch (err) {
      console.error("[api] Erro em /api/login:", err);
      isLoggedIn = false;
      authToken = null;
      loginSessionToken = null;
      return res.status(401).json({
        error: "login_failed",
        message: err.message || "Falha ao autenticar usuário.",
      });
    }
  });

  app.get("/health", (req, res) => {
    res.json({
      status: "ok",
      hasSession: !!gameWsUrl,
      isLoggedIn,
      isBetsOpen,
      lastGameInfo,
      rouletteId: sessionRouletteId,
    });
  });

  // POST /api/external-bet
  // body: { numbers: [int], chipValue?: number }
  app.post("/api/external-bet", (req, res) => {
    try {
      if (!gameWsUrl) {
        return res.status(409).json({
          error: "no_session",
          message:
            "Nenhuma sessão ativa. Envie init_session pelo WebSocket de status primeiro.",
        });
      }

      const { numbers, chipValue } = req.body || {};

      if (!Array.isArray(numbers) || numbers.length === 0) {
        return res.status(400).json({
          error: "invalid_numbers",
          message:
            "Campo 'numbers' é obrigatório e deve ser um array com ao menos 1 número.",
        });
      }

      const valor = chipValue !== undefined ? Number(chipValue) : BASE_CHIP;

      if (!isBetsOpen) {
        return res.status(409).json({
          error: "bets_not_open",
          message: "Apostas não estão abertas no momento.",
        });
      }

      sendBet(numbers, valor);

      return res.json({
        ok: true,
        numbers,
        chipValue: valor,
        gameInfo: lastGameInfo,
      });
    } catch (err) {
      console.error("[api] Erro ao processar /api/external-bet:", err);
      return res.status(500).json({
        error: "internal_error",
        message: err.message || "Erro interno ao enviar aposta.",
      });
    }
  });

  app.listen(BET_HTTP_PORT, () => {
    console.log(
      `[api] Servidor de apostas ouvindo em http://0.0.0.0:${BET_HTTP_PORT}`
    );
  });
}

// =========================
// ENTRADA PRINCIPAL
// =========================

function main() {
  console.log("=========== bot_auto (EXECUTOR) ===========");
  console.log("AUTH_BASE_URL:", AUTH_BASE_URL);
  console.log("DEFAULT_ROULETTE_ID:", DEFAULT_ROULETTE_ID);
  console.log("STATUS_PORT:", STATUS_PORT);
  console.log("BET_HTTP_PORT:", BET_HTTP_PORT);

  // Sobe os servidores. O login é feito em /api/login
  // e a sessão da mesa é criada quando o front envia init_session
  // pelo WebSocket de status.
  startStatusWebSocketServer();
  startBetHttpServer();
}

main();