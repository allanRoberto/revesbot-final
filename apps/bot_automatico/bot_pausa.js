// bot_auto_novo.js
// Bot automático: consulta API de sugestão, aposta, lê resultado pelo WS da mesa,
// controla GALE e repete o ciclo.
// Ajustes:
// 1) Em reconexão de WS: refaz login + reobtém WS URL.
// 2) NÃO reseta tentativas/estado ao reconectar (continua do attempt atual).
// 3) NOVO: Detector de alinhamento de região (previsto vs real) com PAUSA/RETOMADA.
//
// Requisitos:
//   npm install dotenv axios ws puppeteer

require("dotenv").config();
const axios = require("axios");
const WebSocket = require("ws");
const puppeteer = require("puppeteer");

// =========================
// CONFIGURAÇÕES (ENV / FIXO)
// =========================

const AUTH_BASE_URL =
  process.env.AUTH_BASE_URL || "https://auth.revesbot.com.br";
const ANALYSIS_BASE_URL =
  process.env.ANALYSIS_BASE_URL || "http://127.0.0.1:8001";
const AUTH_EMAIL = process.env.AUTH_EMAIL || "allan.rsti@gmail.com";
const AUTH_PASSWORD = process.env.AUTH_PASSWORD || "419300@Al";

const GAME_ID = process.env.GAME_ID || "556";
const ROULETTE_ID =
  process.env.ROULETTE_ID || "pragmatic-speed-roulette-1";

const SUGGESTION_QTD = Number(process.env.SUGGESTION_QTD || 12);
const BASE_CHIP = Number(process.env.BASE_CHIP || 0.5);
const MAX_GALES = Number(process.env.MAX_GALES || 6);
const USE_MARTINGALE =
  (process.env.USE_MARTINGALE || "true") === "true";

const RECONNECT_DELAY_MS = 1000;

// =========================
// NOVO: CONFIG DO ALINHAMENTO
// =========================
const ALIGN_WINDOW_K = Number(process.env.ALIGN_WINDOW_K || 10); // últimos K resultados reais
const PAUSE_DIST = Number(process.env.PAUSE_DIST || 5); // distância (casas na roda) p/ pausar
const PAUSE_STREAK = Number(process.env.PAUSE_STREAK || 1); // quantos giros seguidos p/ pausar
const RESUME_DIST = Number(process.env.RESUME_DIST || 1); // distância p/ retomar
const RESUME_STREAK = Number(process.env.RESUME_STREAK || 1); // quantos giros seguidos p/ retomar
const RESUME_COOLDOWN_SPINS = 2; 
// =========================
// ESTADO DA SESSÃO
// =========================

const SessionState = {
  IDLE: "IDLE",
  WAITING_BETSOPEN: "WAITING_BETSOPEN",
  BET_PLACED: "BET_PLACED",
};

const session = {
  state: SessionState.IDLE,
  bets: [],
  attempt: 0,
  maxAttempts: 1 + MAX_GALES,
  baseChip: BASE_CHIP,
  currentChip: BASE_CHIP,
  lastResult: null,
  gameInfo: null,
  preparing: false,
  resumeCooldown: 0,
  // NOVO: alinhamento de região
  paused: false,
  driftStreak: 0,
  alignStreak: 0,
  lastRealWindow: [],
  lastDist: null,
};

let ws = null;
let authToken = null;
let gameWsUrl = null;
let reconnecting = false;

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
      const [name, value] = nameValue.split("=");
      this.cookies[name.trim()] = value ? value.trim() : "";
    });
  }

  getCookie(name) {
    return this.cookies[name];
  }
}

// =========================
// AUXILIARES DE LOGIN / WS
// =========================

async function loginAndGetToken() {
  const url = `${AUTH_BASE_URL}/api/auth/login`;
  const payload = { email: AUTH_EMAIL, password: AUTH_PASSWORD };

  const response = await axios.post(url, payload, {
    timeout: 15000,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
  });

  const cookieManager = new CookieManager();
  cookieManager.extractCookies(response.headers["set-cookie"]);
  const token = cookieManager.getCookie("bookmaker_token");
  if (!token) throw new Error("Token não encontrado na resposta do login");
  return token;
}

async function getWebSocketUrlWithPuppeteer(gameLink) {
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

    page.on("console", (msg) => {
      const text = msg.text();
      if (text.includes("WS_INTERCEPTED:")) {
        const url = text.split("WS_INTERCEPTED:")[1].trim();
        webSocketUrls.push(url);
      }
    });

    page.on("websocket", (wso) => {
      webSocketUrls.push(wso.url());
    });

    await page.goto(gameLink, {
      waitUntil: "networkidle2",
      timeout: 60000,
    });
    await new Promise((resolve) => setTimeout(resolve, 3000));

    const capturedUrls = await page.evaluate(() => window.__wsUrls || []);
    const allUrls = [...new Set([...capturedUrls, ...webSocketUrls])];

    console.log(allUrls)

    if (allUrls.length > 0) {
      const pragmaticUrl = allUrls.find(
        (url) =>
          url.includes("game")
      );
      return pragmaticUrl || allUrls[1];
    }

    throw new Error("WebSocket URL não encontrada");
  } finally {
    await browser.close();
  }
}

async function getGameWebSocketUrl(gameId, token) {
  const url = `${AUTH_BASE_URL}/api/start-game/${gameId}`;

  const { data } = await axios.get(url, {
    headers: { Cookie: `bookmaker_token=${token}` },
    timeout: 15000,
  });

  if (!data.success || !data.link) {
    throw new Error("Falha ao iniciar o jogo");
  }

  const wsUrl = await getWebSocketUrlWithPuppeteer(data.link);

  console.log(wsUrl)

  if (!wsUrl) throw new Error("URL de WebSocket não encontrada no start-game");
  return wsUrl;
}

// =========================
// BUSCAR SUGESTÃO NA SUA API
// =========================

async function fetchSuggestionNumbers(rouletteId, quantidade) {
  const url = `${ANALYSIS_BASE_URL}/api/sugestao/${encodeURIComponent(
    rouletteId
  )}?quantidade=${quantidade}&incluir_protecoes=true&max_protecoes=5&incluir_zero=true&limite_historico=100&w_estelar=0.2&w_chain=0.2&w_temporal=0.2&w_quente=0.2&w_comportamental=0.2&minute_offset=0&interval_minutes=2&days_back=30`;

  const { data } = await axios.get(url, { timeout: 15000 });

  if (
    !data?.sugestoes?.principais ||
    !Array.isArray(data.sugestoes.principais)
  ) {
    return [];
  }

  return data.sugestoes.principais
    .map((s) => s.numero)
    .filter((n) => n >= 0 && n <= 36);
}

// =========================
// PARSE DO RESULTADO PELO WEBSOCKET
// =========================

function parseWinningNumber(message) {
  const text = message.toString();
  const m = text.match(/gameresult[^>]*score="(\d+)"/);
  return m ? parseInt(m[1], 10) : null;
}

function isBetsOpenMessage(message) {
  const text = message.toString().toLowerCase();
  return text.includes("betsopen");
}

function parseBetsOpenMessage(xmlMessage) {
  const gameMatch = xmlMessage.match(/game="([^"]+)"/);
  const tableMatch = xmlMessage.match(/table="([^"]+)"/);
  return gameMatch && tableMatch
    ? { game: gameMatch[1], table: tableMatch[1] }
    : null;
}

// =========================
// NOVO: RODA + FUNÇÕES CIRCULARES
// =========================

// Roda europeia (ordem física)
const WHEEL = [
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30,
  8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29,
  7, 28, 12, 35, 3, 26
];

const POS = {};
for (let i = 0; i < WHEEL.length; i++) POS[WHEEL[i]] = i;

function circularCenter(nums) {
  const positions = nums
    .map((n) => POS[n])
    .filter((p) => p !== undefined);

  if (!positions.length) return null;

  let sumSin = 0;
  let sumCos = 0;
  const L = WHEEL.length;

  for (const p of positions) {
    const ang = (2 * Math.PI * p) / L;
    sumSin += Math.sin(ang);
    sumCos += Math.cos(ang);
  }

  const meanAng = Math.atan2(sumSin / positions.length, sumCos / positions.length);
  let meanPos = Math.round((meanAng * L) / (2 * Math.PI));
  if (meanPos < 0) meanPos += L;

  return meanPos;
}

function circularDistance(posA, posB) {
  const L = WHEEL.length;
  const d = Math.abs(posA - posB);
  return Math.min(d, L - d);
}

function updateAlignment(numeroReal) {
    // atualiza janela real
    session.lastRealWindow.push(numeroReal);
    if (session.lastRealWindow.length > ALIGN_WINDOW_K) {
      session.lastRealWindow.shift();
    }
  
    if (!session.bets || !session.bets.length || session.lastRealWindow.length < 3) {
      return;
    }
  
    const prevCenter = circularCenter(session.bets);
    const realCenter = circularCenter(session.lastRealWindow);
  
    if (prevCenter === null || realCenter === null) return;
  
    const dist = circularDistance(prevCenter, realCenter);
    session.lastDist = dist;
  
    // =============================
    // MODO ATIVO (não pausado)
    // =============================
    if (!session.paused) {
      // se acabou de retomar, respeita cooldown e NÃO deixa pausar
      if (session.resumeCooldown > 0) {
        session.resumeCooldown -= 1;
        // opcional: zera streaks pra não acumular lixo
        session.driftStreak = 0;
        session.alignStreak = 0;
        return;
      }
  
      // lógica normal de PAUSE
      if (dist > PAUSE_DIST) {
        session.driftStreak += 1;
        session.alignStreak = 0;
        if (session.driftStreak >= PAUSE_STREAK) {
          session.paused = true;
          console.log(
            `Pausa no ciclo (dist=${dist}) | tentativa=${session.attempt}/${session.maxAttempts}`
          );
        }
      } else {
        session.driftStreak = 0;
      }
    } else {
      // =============================
      // MODO PAUSADO
      // =============================
  
      // 1) Se o número real faz parte da jogada → retoma IMEDIATO
      const hitOnPaused = session.bets && session.bets.includes(numeroReal);
      if (hitOnPaused) {
        session.paused = false;
        session.alignStreak = 0;
        session.driftStreak = 0;
        session.resumeCooldown = RESUME_COOLDOWN_SPINS; // protege logo após retomar
        console.log(
          `Retomando ciclo por acerto na região (n=${numeroReal}) | tentativa=${session.attempt}/${session.maxAttempts}`
        );
        return;
      }
  
      // 2) Regra normal de alinhamento por distância
      if (dist <= RESUME_DIST) {
        session.alignStreak += 1;
        session.driftStreak = 0;
        if (session.alignStreak >= RESUME_STREAK) {
          session.paused = false;
          session.alignStreak = 0;
          session.resumeCooldown = RESUME_COOLDOWN_SPINS; // idem aqui
          console.log(
            `Retomando ciclo (dist=${dist}) | tentativa=${session.attempt}/${session.maxAttempts}`
          );
        }
      } else {
        session.alignStreak = 0;
      }
    }
  }

// =========================
// LÓGICA DE APOSTA (PLACE BET)
// =========================

// Sequência fixa de fichas por tentativa (1ª, 2ª, 3ª, ...)
const BET_SEQUENCE = [1.0, 1.5, 1.5, 2.0, 2.5,  3.0, 4.5, 7.0, 10.5];

function calculateNextChipValue(attempt, baseChip) {
  const idx = attempt;
  if (idx >= 0 && idx < BET_SEQUENCE.length) return BET_SEQUENCE[idx];
  return BET_SEQUENCE[BET_SEQUENCE.length - 1];
}

function generateChecksumTimestamp() {
  return Date.now().toString();
}

function sendBet(wsConn, gameInfo, bets, valorAposta) {
  const checksum = generateChecksumTimestamp();
  const betsXML = bets
    .map((num) => {
      const betCode = Number(num) == 0 ? 2 : Number(num) + 3;
      return `<bet amt="${valorAposta}" bc="${betCode}" ck="${checksum}" />`;
    })
    .join("");

  const message =
    `<command channel="table-${gameInfo.table}" >` +
    `<lpbet gm="roulette_desktop" gId="${gameInfo.game}" uId="ppc1735139140386" ck="${checksum}">` +
    betsXML +
    `</lpbet></command>`;

  // log principal acontece em handleBetsOpen (pra ficar limpo)
  wsConn.send(message);
}

// =========================
// CONTROLE DE SESSÃO (CICLO APOSTA + GALES)
// =========================

async function prepareNewSessionIfNeeded() {
  if (session.preparing) return false;
  if (session.state !== SessionState.IDLE) return false;
  if (!ROULETTE_ID) return false;

  session.preparing = true;
  try {
    const bets = await fetchSuggestionNumbers(ROULETTE_ID, SUGGESTION_QTD);
    if (!bets.length) return false;

    session.bets = bets;
    session.attempt = 0; // só zera quando inicia ciclo normal
    session.currentChip = BASE_CHIP;
    session.lastResult = null;

    session.state = SessionState.WAITING_BETSOPEN;
    return true;
  } finally {
    session.preparing = false;
  }
}

async function handleBetsOpen(gameInfo) {
  session.gameInfo = gameInfo;

  if (session.state === SessionState.BET_PLACED) return;

  if (session.state === SessionState.IDLE) {
    const ok = await prepareNewSessionIfNeeded();
    if (!ok) return;
  }

  if (session.state !== SessionState.WAITING_BETSOPEN) return;
  if (!session.bets.length) {
    session.state = SessionState.IDLE;
    return;
  }
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  // NOVO: se pausado, não aposta e não consome tentativa
  if (session.paused) {
    return;
  }

  session.currentChip = calculateNextChipValue(
    session.attempt,
    session.baseChip
  );
  session.attempt += 1;

  console.log(
    `Tentativa ${session.attempt}: ${session.bets.join(", ")} | ficha=${session.currentChip.toFixed(2)}`
  );

  sendBet(ws, session.gameInfo, session.bets, session.currentChip);
  session.state = SessionState.BET_PLACED;
}

async function handleRoundResult(numero) {

    // LOG SEMPRE DO RESULTADO (mesmo pausado)
  console.log(
    `[resultado] Número sorteado: ${numero}${session.paused ? " (PAUSA)" : ""}`
  );
  session.lastResult = numero;

  // NOVO: atualiza alinhamento antes de avaliar win/loss
  updateAlignment(numero);

  if (session.state !== SessionState.BET_PLACED) return;

  const ganhou = session.bets.includes(numero);

  if (ganhou) {
    console.log(
      `✅ WIN! Aposta ganha na tentativa ${session.attempt} | número=${numero}`
    );
    session.state = SessionState.IDLE;
    session.bets = [];
    session.driftStreak = 0;
    session.alignStreak = 0;
    session.resumeCooldown = 0;
    session.paused = false;
    return;
  }

  if (session.attempt >= session.maxAttempts) {
    console.log(`Fim dos GALES | derrota | último=${numero}`);
    session.state = SessionState.IDLE;
    session.bets = [];
    session.driftStreak = 0;
    session.alignStreak = 0;
    session.resumeCooldown = 0;
    session.paused = false;
    return;
  }

  /* try {
    const novos = await fetchSuggestionNumbers(ROULETTE_ID, SUGGESTION_QTD);
    if (novos.length) {
      session.bets = novos;
    }
  } catch (_) {} */

  session.state = SessionState.WAITING_BETSOPEN;
}

// =========================
// RECONEXÃO COM REL0GIN
// =========================

async function reconnectWithRelogin() {
  if (reconnecting) return;
  reconnecting = true;

  try {
    console.warn("[ws] Reconectando: refazendo login...");
    authToken = await loginAndGetToken();
    gameWsUrl = await getGameWebSocketUrl(GAME_ID, authToken);
    console.warn("[ws] Login/WS URL OK. Reconectando socket...");
    connectWebSocket();
  } catch (err) {
    console.error("[ws] Falha ao relogar/reconectar:", err.message);
    setTimeout(() => {
      reconnecting = false;
      reconnectWithRelogin();
    }, RECONNECT_DELAY_MS);
    return;
  }

  reconnecting = false;
}

// =========================
// LOOP DO WEBSOCKET
// =========================

function connectWebSocket() {
  if (!gameWsUrl) {
    console.error("[ws] gameWsUrl não definido. Não é possível conectar.");
    return;
  }

  console.log("[ws] Conectando ao WebSocket da mesa...");
  ws = new WebSocket(gameWsUrl);

  ws.on("open", () => {
    console.log("[ws] Conectado.");
  });

  ws.on("message", (data) => {
    const text = data.toString();

    if (isBetsOpenMessage(text)) {
      const gameInfo = parseBetsOpenMessage(text);
      if (gameInfo) {
        handleBetsOpen(gameInfo).catch((err) => {
          console.error("[bet] Erro em handleBetsOpen:", err.message);
        });
      }
    }

    const numero = parseWinningNumber(text);
    if (numero !== null && !Number.isNaN(numero)) {
      handleRoundResult(numero).catch((err) => {
        console.error("[resultado] Erro em handleRoundResult:", err.message);
      });
    }
  });

  ws.on("close", (code, reason) => {
    console.warn(
      `[ws] Conexão fechada (code=${code}, reason=${reason}).`
    );
    ws = null;

    // NÃO resetar attempt/state/bets aqui
    console.warn(
      `[ws] Mantendo sessão: state=${session.state} attempt=${session.attempt}/${session.maxAttempts}`
    );

    setTimeout(reconnectWithRelogin, RECONNECT_DELAY_MS);
  });

  ws.on("error", (err) => {
    console.error("[ws] Erro no WebSocket:", err.message);
    try {
      ws?.close();
    } catch (_) {}
  });
}

// =========================
// ENTRADA PRINCIPAL
// =========================

async function main() {
  try {
    if (!GAME_ID)
      throw new Error("GAME_ID não definido. Configure no .env");
    if (!ROULETTE_ID)
      throw new Error("ROULETTE_ID não definido. Configure no .env");

    authToken = await loginAndGetToken();
    gameWsUrl = await getGameWebSocketUrl(GAME_ID, authToken);

    connectWebSocket();
  } catch (err) {
    console.error("[main] Erro ao iniciar bot_auto:", err.message);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error("[main] Erro fatal:", err);
  process.exit(1);
});