// bot_auto.js
// Bot automático: consulta API de sugestão, aposta, lê resultado pelo WS da mesa,
// controla GALE e repete o ciclo.

// Requisitos:
//   npm install dotenv axios ws

require("dotenv").config();
const axios = require("axios");
const WebSocket = require("ws");
const puppeteer = require('puppeteer');


// =========================
// CONFIGURAÇÕES (ENV / FIXO)
// =========================

const AUTH_BASE_URL = process.env.AUTH_BASE_URL || "https://auth.revesbot.com.br";      // micro serviço auth
const ANALYSIS_BASE_URL = process.env.ANALYSIS_BASE_URL || "http://127.0.0.1:8001"; // API neural/sugestao
const AUTH_EMAIL = process.env.AUTH_EMAIL || "allan.rsti@gmail.com";
const AUTH_PASSWORD = process.env.AUTH_PASSWORD || "419300@Al";

const GAME_ID = process.env.GAME_ID || "450";         // gameId da mesa na casa de apostas
const ROULETTE_ID = process.env.ROULETTE_ID || "pragmatic-brazilian-roulette"; // id da roleta usado na sua API (ex: pragmatic-brazilian-roulette)

const SUGGESTION_QTD = Number(process.env.SUGGESTION_QTD || 6);  // quantos números pegar da sugestão
const BASE_CHIP = Number(process.env.BASE_CHIP || 0.5);           // ficha base por número
const MAX_GALES = Number(process.env.MAX_GALES || 3);             // quantidade de gales (0,1,2,...)
const USE_MARTINGALE = (process.env.USE_MARTINGALE || "true") === "true";

const RECONNECT_DELAY_MS = 1000;

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
};

let ws = null;
let authToken = null;
let gameWsUrl = null;



// ============================
// COOKIE MANAGER
// ============================
class CookieManager {
    constructor() {
        this.cookies = {};
    }
    
    extractCookies(setCookieHeaders) {
        if (!setCookieHeaders) return;
        const cookieArray = Array.isArray(setCookieHeaders) ? setCookieHeaders : [setCookieHeaders];
        cookieArray.forEach(cookie => {
            const [nameValue] = cookie.split(';');
            const [name, value] = nameValue.split('=');
            this.cookies[name.trim()] = value ? value.trim() : '';
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
    console.log("[auth] Fazendo login no AUTH_BASE_URL...");
    const url = `${AUTH_BASE_URL}/api/auth/login`;
    const payload = {
        email: AUTH_EMAIL,
        password: AUTH_PASSWORD,
    };

    const response = await axios.post(url, payload, {
        timeout: 15000,
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
    });

    const cookieManager = new CookieManager();
    cookieManager.extractCookies(response.headers['set-cookie']);
    const token = cookieManager.getCookie('bookmaker_token');
    // Ajuste aqui conforme o retorno real do seu serviço de auth
    if (!token) {
        throw new Error("Token não encontrado na resposta do login");
    }

    console.log("[auth] Login OK, token obtido.");
    
    return token;
}

async function getWebSocketUrlWithPuppeteer(gameLink) {
    const browser = await puppeteer.launch({ 
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    try {
        const page = await browser.newPage();
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36');
        
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
                }
            });
        });
        
        page.on('console', msg => {
            const text = msg.text();
            if (text.includes('WS_INTERCEPTED:')) {
                const url = text.split('WS_INTERCEPTED:')[1].trim();
                webSocketUrls.push(url);
            }
        });
        
        page.on('websocket', ws => {
            webSocketUrls.push(ws.url());
        });
        
        await page.goto(gameLink, { waitUntil: 'networkidle2', timeout: 60000 });
        await new Promise(resolve => setTimeout(resolve, 3000));
        
        const capturedUrls = await page.evaluate(() => window.__wsUrls || []);
        const allUrls = [...new Set([...capturedUrls, ...webSocketUrls])];
        
        if (allUrls.length > 0) {
            const pragmaticUrl = allUrls.find(url => 
                url.includes('pragmatic') || url.includes('livecasino') || url.includes('game')
            );
            return pragmaticUrl || allUrls[0];
        }
        
        throw new Error('WebSocket URL não encontrada');
    } finally {
        await browser.close();
    }
}

async function getGameWebSocketUrl(gameId, token) {
    //console.log("[auth] Buscando URL do WebSocket do game...");
    const url = `${AUTH_BASE_URL}/api/start-game/${gameId}`;

    const { data } = await axios.get(url, {
        headers: { 'Cookie': `bookmaker_token=${token}` },
        timeout: 15000,
    });

    if (!data.success || !data.link) {
        throw new Error('Falha ao iniciar o jogo');
    }


    const wsUrl = await getWebSocketUrlWithPuppeteer(data.link);

    if (!wsUrl) {
        throw new Error("URL de WebSocket não encontrada na resposta de start-game");
    }

    //console.log("[auth] WebSocket URL obtida:", wsUrl);
    return wsUrl;
}

// =========================
// BUSCAR SUGESTÃO NA SUA API
// =========================

async function fetchSuggestionNumbers(rouletteId, quantidade) {
  const url = `${ANALYSIS_BASE_URL}/api/sugestao/${encodeURIComponent(
    rouletteId
  )}?quantidade=${quantidade}&incluir_protecoes=true&max_protecoes=5&incluir_zero=true&limite_historico=100&w_estelar=0.2&w_chain=0.2&w_temporal=0.2&w_quente=0.2&w_comport=0.2&minute_offset=0&interval_minutes=2&days_back=30`

  const { data } = await axios.get(url, { timeout: 15000 });

  if (!data?.sugestoes?.principais || !Array.isArray(data.sugestoes.principais)) {
    console.warn("[sugestao] Resposta inesperada, sem 'sugestoes.principais'.");
    return [];
  }

  const numeros = data.sugestoes.principais.map((s) => s.numero).filter((n) => n >= 0 && n <= 36);
  return numeros;
}

// =========================
// PARSE DO RESULTADO PELO WEBSOCKET
// =========================

function parseWinningNumber(message) {
  
  const text = message.toString();
  // Exemplo 3: XML: <winning number="X">
  m = text.match(/gameresult[^>]*score="(\d+)"/);

  if (m) return parseInt(m[1], 10);

  return null;
}

function isBetsOpenMessage(message) {
  const text = message.toString().toLowerCase();
  return text.includes("betsopen");
}

function parseBetsOpenMessage(xmlMessage) {
    const gameMatch = xmlMessage.match(/game="([^"]+)"/);
    const tableMatch = xmlMessage.match(/table="([^"]+)"/);
    return (gameMatch && tableMatch) ? { game: gameMatch[1], table: tableMatch[1] } : null;
}

// =========================
// LÓGICA DE APOSTA (PLACE BET)
// =========================
// Sequência fixa de fichas por tentativa (1ª, 2ª, 3ª, ...)
const BET_SEQUENCE = [1.0, 1.0, 1.0, 1.0, 1.0, 1.5, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]; 
//const BET_SEQUENCE = [1.0, 1.0, 1.5, 2.0, 3.5, 5.0]; 
//                   tent1 tent2 tent3 tent4 ...

function calculateNextChipValue(attempt, baseChip) {
  // attempt começa em 1 na lógica atual
  const idx = attempt;

  console.log(idx, "idx")
  // Se tiver valor configurado para essa tentativa, usa ele
  if (idx >= 0 && idx < BET_SEQUENCE.length) {
    return BET_SEQUENCE[idx];
  }

  // Se passar do tamanho do array, mantém o último valor
  return BET_SEQUENCE[BET_SEQUENCE.length - 1];
}


function generateChecksumTimestamp() {
    return Date.now().toString();
}

function sendBet(ws, gameInfo, bets, valorAposta) {
    const checksum = generateChecksumTimestamp();
    const betsXML = bets.map(num => {
        let betCode = Number(num) == 0 ? 2 : Number(num) + 3;
        return `<bet amt="${valorAposta}" bc="${betCode}" ck="${checksum}" />`;
    }).join("");
    
    const message =
        `<command channel="table-${gameInfo.table}" >` +
        `<lpbet gm="roulette_desktop" gId="${gameInfo.game}" uId="ppc1735139140386" ck="${checksum}">` +
        betsXML +
        `</lpbet></command>`;
    
    console.log(`🎲 Apostando em ${bets.join(', ')} | Valor: ${valorAposta} centavos`);
    ws.send(message);
}

// =========================
// CONTROLE DE SESSÃO (CICLO APOSTA + GALES)
// =========================

async function prepareNewSessionIfNeeded() {
  if (session.state !== SessionState.IDLE) return;
  if (!ROULETTE_ID) {
    console.error("[sessao] ROULETTE_ID não definido. Configure no .env.");
    return;
  }

  const bets = await fetchSuggestionNumbers(ROULETTE_ID, SUGGESTION_QTD);
  if (!bets.length) {
    console.warn("[sessao] Nenhum número sugerido. Mantendo estado IDLE.");
    return;
  }

  session.bets = bets;
  session.attempt = 0;
  session.currentChip = BASE_CHIP;
  session.lastResult = null;

  session.state = SessionState.WAITING_BETSOPEN;
 
}

function handleBetsOpen(gameInfo) {
  // Só aposta se estivermos esperando oportunidade
  if (
    session.state !== SessionState.WAITING_BETSOPEN &&
    session.state !== SessionState.IDLE
  ) {

    console.log(session.state)
    return;
  }

  session.gameInfo = gameInfo


  // Se estava IDLE, tenta montar nova sessão
  if (session.state === SessionState.IDLE) {
    // Em vez de async direto, dispara sem bloquear:
    prepareNewSessionIfNeeded().catch((err) => {
      console.log(err)
      console.error("[sessao] Erro ao preparar nova sessão:", err.message);
    });
    return;
  }

  // Agora state == WAITING_BETSOPEN
  if (!session.bets.length) {
    console.warn("[bet] Sessão sem bets. Voltando para IDLE.");
    session.state = SessionState.IDLE;
    return;
  }

  if (!ws || ws.readyState !== WebSocket.OPEN) {
    console.warn("[bet] WebSocket não está aberto. Não é possível apostar.");
    return;
  }

  session.currentChip = calculateNextChipValue(session.attempt, session.baseChip);
  session.attempt += 1;

  console.log(
    `[sessao] Tentativa ${session.attempt}/${session.maxAttempts} | ficha=${session.currentChip.toFixed(
      2
    )}`
  );

  sendBet(ws, session.gameInfo, session.bets, session.currentChip);
  session.state = SessionState.BET_PLACED;
}

function handleRoundResult(numero) {
  session.lastResult = numero;
  console.log(`[resultado] Número sorteado: ${numero} ESTADO DA SESSION: ${session.state}`);

  if (session.state !== SessionState.BET_PLACED) {
    // Resultado chegou, mas não estávamos com aposta ativa (possível atraso de sync)
    return;
  }

  const ganhou = session.bets.includes(numero);



  if (ganhou) {
    console.log(
      `[sessao] ✅ WIN! Número ${numero} está na aposta. Tentativa ${session.attempt}/${session.maxAttempts}.`
    );
    // fim da sessão de gale: próxima oportunidade será nova previsão
    session.state = SessionState.IDLE;
    session.bets = [];
    return;
  }

  console.log(
    `[sessao] LOSS na tentativa ${session.attempt}/${session.maxAttempts} | número=${numero}`
  );

  if (session.attempt >= session.maxAttempts) {
    console.log("[sessao] ❌ Fim dos GALES. Sessão encerrada com derrota.");
    session.state = SessionState.IDLE;
    session.bets = [];
    return;
  }

  // Ainda tem GALE, aguarda próximo bets open com MESMOS números
  session.state = SessionState.WAITING_BETSOPEN;
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


    // 1) Checa bets open
    if (isBetsOpenMessage(text)) {
      console.log("[ws] Apostas abertas...");

      gameInfo = parseBetsOpenMessage(text);

      if (gameInfo) {
        //console.log(`\n🎰 ✅ CONDIÇÕES ATENDIDAS - ENVIANDO APOSTA`);
        handleBetsOpen(gameInfo);
      }
    }

    // 2) Checa número sorteado
    const numero = parseWinningNumber(text);
    if (numero !== null && !Number.isNaN(numero)) {
      handleRoundResult(numero);
    }
  });

  ws.on("close", (code, reason) => {
    console.warn(`[ws] Conexão fechada (code=${code}, reason=${reason}).`);
    ws = null;
    session.state = SessionState.IDLE;
    console.log(`[ws] Tentando reconectar em ${RECONNECT_DELAY_MS}ms...`);
    setTimeout(connectWebSocket, RECONNECT_DELAY_MS);
  });

  ws.on("error", (err) => {
    console.error("[ws] Erro no WebSocket:", err.message);
  });
}

// =========================
// ENTRADA PRINCIPAL
// =========================

async function main() {
  try {
    if (!GAME_ID) {
      throw new Error("GAME_ID não definido. Configure no .env");
    }
    if (!ROULETTE_ID) {
      throw new Error("ROULETTE_ID não definido. Configure no .env");
    }

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