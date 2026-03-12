// bot_api.js
// API REST para receber sinais e executar apostas automáticas
// Login mantido ativo com renovação automática de token
//
// Requisitos:
//   npm install dotenv axios ws puppeteer express

require("dotenv").config();
const express = require("express");
const axios = require("axios");
const WebSocket = require("ws");
const puppeteer = require("puppeteer");

// =========================
// CONFIGURAÇÕES
// =========================

const AUTH_BASE_URL = process.env.AUTH_BASE_URL || "https://auth.revesbot.com.br";
const AUTH_EMAIL = process.env.AUTH_EMAIL || "allan.rsti@gmail.com";
const AUTH_PASSWORD = process.env.AUTH_PASSWORD || "419300@Al";

const API_PORT = process.env.API_PORT || 3000;
const TOKEN_RENEWAL_INTERVAL = 25 * 60 * 1000; // 25 minutos

// Sequência fixa de fichas por tentativa
const BET_SEQUENCE = [1.0, 1.5, 1.5, 1.5, 1.0, 1.0, 1.0];

// =========================
// ESTADO GLOBAL
// =========================

let authToken = null;
let tokenRenewalTimer = null;

// =========================
// COOKIE MANAGER
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
// FUNÇÕES DE LOGIN
// =========================

async function loginAndGetToken() {
  const url = `${AUTH_BASE_URL}/api/auth/login`;
  const payload = { email: AUTH_EMAIL, password: AUTH_PASSWORD };

  console.log("[auth] Fazendo login...");
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
  
  if (!token) {
    throw new Error("Token não encontrado na resposta do login");
  }
  
  console.log("[auth] ✅ Login realizado com sucesso");
  return token;
}

async function renewToken() {
  try {
    console.log("[auth] Renovando token...");
    authToken = await loginAndGetToken();
    console.log("[auth] ✅ Token renovado");
  } catch (err) {
    console.error("[auth] ❌ Erro ao renovar token:", err.message);
  }
}

function startTokenRenewal() {
  if (tokenRenewalTimer) {
    clearInterval(tokenRenewalTimer);
  }
  
  tokenRenewalTimer = setInterval(renewToken, TOKEN_RENEWAL_INTERVAL);
  console.log(`[auth] Renovação automática de token configurada (a cada ${TOKEN_RENEWAL_INTERVAL / 60000} minutos)`);
}

// =========================
// OBTER WEBSOCKET URL
// =========================

async function getWebSocketUrlWithPuppeteer(gameLink) {
  const browser = await puppeteer.launch({
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-accelerated-2d-canvas",
      "--no-first-run",
      "--no-zygote",
      "--disable-gpu",
      "--disable-extensions",
      "--disable-background-networking",
      "--disable-default-apps",
      "--disable-sync",
      "--disable-translate",
      "--hide-scrollbars",
      "--metrics-recording-only",
      "--mute-audio",
      "--no-default-browser-check",
      "--disable-features=site-per-process",
    ],
  });

  try {
    const page = await browser.newPage();
    
    // Bloquear recursos desnecessários para acelerar
    await page.setRequestInterception(true);
    page.on("request", (request) => {
      const resourceType = request.resourceType();
      // Bloqueia imagens, fontes, CSS, media - só permite scripts e documentos
      if (["image", "stylesheet", "font", "media"].includes(resourceType)) {
        request.abort();
      } else {
        request.continue();
      }
    });

    await page.setUserAgent(
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    );

    const webSocketUrls = [];
    let resolved = false;

    // Interceptar WebSocket ANTES da página carregar
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

    // Capturar WebSocket assim que aparecer
    page.on("websocket", (wso) => {
      const url = wso.url();
      console.log(`[puppeteer] WebSocket detectado: ${url}`);
      webSocketUrls.push(url);
      
      // Se encontrou WebSocket pragmatic, pode parar imediatamente
      if (!resolved && (url.includes("pragmatic") || url.includes("livecasino") || url.includes("game"))) {
        resolved = true;
      }
    });

    // Não esperar networkidle2, só esperar o DOM carregar
    const gotoPromise = page.goto(gameLink, {
      waitUntil: "networkidle2", // Mudado de networkidle2 para domcontentloaded
      timeout: 15000, // Reduzido de 60s para 15s
    });

    // Espera até encontrar WebSocket OU timeout
    const websocketPromise = new Promise((resolve) => {
      const checkInterval = setInterval(() => {
        if (webSocketUrls.length > 0 || resolved) {
          clearInterval(checkInterval);
          resolve(true);
        }
      }, 100);
      
      // Timeout de 10s para encontrar WebSocket
      setTimeout(() => {
        clearInterval(checkInterval);
        resolve(false);
      }, 10000);
    });

    // Aguarda ou navegação completar ou WebSocket aparecer
    await Promise.race([gotoPromise, websocketPromise]);

    // Pequena espera adicional para garantir que capturou o WS (reduzido de 3s para 500ms)
    await new Promise((resolve) => setTimeout(resolve, 500));

    const capturedUrls = await page.evaluate(() => window.__wsUrls || []);
    const allUrls = [...new Set([...capturedUrls, ...webSocketUrls])];

    console.log(`[puppeteer] URLs capturadas: ${allUrls.length}`);

    if (allUrls.length > 0) {
      const pragmaticUrl = allUrls.find(
        (url) =>
          url.includes("pragmatic") ||
          url.includes("livecasino") ||
          url.includes("game")
      );
      return pragmaticUrl || allUrls[0];
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
  if (!wsUrl) {
    throw new Error("URL de WebSocket não encontrada no start-game");
  }
  
  return wsUrl;
}

// =========================
// FUNÇÕES DE APOSTA
// =========================

function calculateChipValue(attempt) {
  const idx = attempt;
  if (idx >= 0 && idx < BET_SEQUENCE.length) {
    return BET_SEQUENCE[idx];
  }
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

  console.log(`🎲 Apostando em ${bets.join(", ")} | Valor: ${valorAposta} centavos`);
  wsConn.send(message);
}

function parseWinningNumber(message) {
  const text = message.toString();
  const m = text.match(/gameresult[^>]*score="(\d+)"/);
  return m ? parseInt(m[1], 10) : null;
}

function parseBetsOpenMessage(xmlMessage) {
  const gameMatch = xmlMessage.match(/game="([^"]+)"/);
  const tableMatch = xmlMessage.match(/table="([^"]+)"/);
  return gameMatch && tableMatch
    ? { game: gameMatch[1], table: tableMatch[1] }
    : null;
}

function isBetsOpenMessage(message) {
  const text = message.toString().toLowerCase();
  return text.includes("betsopen");
}

// =========================
// PROCESSAMENTO DE APOSTA
// =========================

async function processBet(signal) {
  const { bets, gales, roulette_url } = signal;
  
  if (!bets || !Array.isArray(bets) || bets.length === 0) {
    throw new Error("Números de aposta inválidos");
  }

  const maxAttempts = (gales || 0) + 1; // 1 aposta inicial + N gales
  
  // Extrair game_id da URL (ex: https://lotogreen.bet.br/play/556 -> 556)
  const gameIdMatch = roulette_url.match(/\/play\/(\d+)/);
  if (!gameIdMatch) {
    throw new Error("Não foi possível extrair game_id da URL");
  }
  const gameId = gameIdMatch[1];
  
  console.log(`\n[bet] 🎯 Novo sinal recebido`);
  console.log(`[bet] 🎲 Números: ${bets.join(", ")}`);
  console.log(`[bet] 🎰 Mesa: ${roulette_url}`);
  console.log(`[bet] 🔄 Tentativas máximas: ${maxAttempts} (1 inicial + ${gales} gales)`);

  // Conectar no WebSocket da mesa (UMA VEZ SÓ)
  console.log(`[bet] Conectando na mesa (game_id: ${gameId})...`);
  const wsUrl = await getGameWebSocketUrl(gameId, authToken);
  
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let gameInfo = null;
    let capturedGameId = null;
    let capturedTableId = null;
    let currentAttempt = 0;
    let waitingResult = false;

    const cleanup = () => {
      try {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.close();
        }
      } catch (err) {
        console.error("[bet] Erro ao fechar WebSocket:", err.message);
      }
    };

    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error("Timeout: não foi possível conectar ou fazer aposta"));
    }, 90000); // 90 segundos para todo o processo (inicial + gales)

    // Função auxiliar para tentar montar gameInfo
    const tryBuildGameInfo = () => {
      if (!gameInfo && capturedGameId && capturedTableId) {
        gameInfo = { game: capturedGameId, table: capturedTableId };
        console.log(`[bet] ✅ gameInfo montado: ${JSON.stringify(gameInfo)}`);
        return true;
      }
      return false;
    };

    // Função para fazer aposta
    const placeBet = () => {
      if (!gameInfo) {
        console.error("[bet] ❌ Tentou apostar sem gameInfo!");
        return;
      }

      currentAttempt++;
      const chipValue = calculateChipValue(currentAttempt - 1);
      console.log(`[bet] 📍 Tentativa ${currentAttempt}/${maxAttempts} | Ficha: ${chipValue}`);
      sendBet(ws, gameInfo, bets, chipValue);
      waitingResult = true;
    };

    ws.on("open", () => {
      console.log("[bet] ✅ Conectado no WebSocket da mesa");
    });

    ws.on("message", (data) => {
      const text = data.toString();
      
      // DEBUG: Log de todas as mensagens recebidas (primeiros 150 chars)
      console.log(`[bet] 📨 WS: ${text.substring(0, 150)}...`);

      // Verificar erro de validação de aposta
      if (text.includes("betValidationError")) {
        const errorMatch = text.match(/code="([^"]+)"[^>]*desc="([^"]+)"/);
        if (errorMatch) {
          const errorCode = errorMatch[1];
          const errorDesc = errorMatch[2];
          console.log(`[bet] ❌ Erro de validação: [${errorCode}] ${errorDesc}`);
          
          clearTimeout(timeout);
          cleanup();
          resolve({
            success: false,
            result: "error",
            attempts: currentAttempt,
            errorCode: errorCode,
            errorMessage: errorDesc,
            message: `Aposta rejeitada: ${errorDesc}`
          });
          return;
        }
      }

      // Capturar gameId: <game id="11999874614" ...>
      if (!capturedGameId) {
        const gameMatch = text.match(/<game id="([^"]+)"/);
        if (gameMatch) {
          capturedGameId = gameMatch[1];
          console.log(`[bet] 🎮 Game ID capturado: ${capturedGameId}`);
          tryBuildGameInfo();
        }
      }

      // Capturar tableId: <lastgame ... tableId="rwbrzportrwa16rg" ...>
      if (!capturedTableId) {
        const tableMatch = text.match(/tableId="([^"]+)"/);
        if (tableMatch) {
          capturedTableId = tableMatch[1];
          console.log(`[bet] 🏛️ Table ID capturado: ${capturedTableId}`);
          tryBuildGameInfo();
        }
      }

      // Capturar tableId alternativo: <subscribe ... table="rwbrzportrwa16rg" ...>
      if (!capturedTableId) {
        const subscribeTableMatch = text.match(/<subscribe[^>]*table="([^"]+)"/);
        if (subscribeTableMatch) {
          capturedTableId = subscribeTableMatch[1];
          console.log(`[bet] 🏛️ Table ID capturado via subscribe: ${capturedTableId}`);
          tryBuildGameInfo();
        }
      }

      // Fazer PRIMEIRA aposta assim que tiver gameInfo completo
      if (gameInfo && currentAttempt === 0) {
        console.log(`[bet] 🎮 Mesa identificada: ${gameInfo.game} / ${gameInfo.table}`);
        placeBet();
      }

      // Processar resultado - apenas se já fez alguma aposta
      if (currentAttempt > 0 && waitingResult) {
        const numero = parseWinningNumber(text);
        if (numero !== null && !isNaN(numero)) {
          const resultGameMatch = text.match(/gameresult[^>]*id="([^"]+)"/);
          if (resultGameMatch) {
            const resultGameId = resultGameMatch[1];
            console.log(`[bet] 🎯 Resultado detectado: ${numero} (gameId: ${resultGameId})`);
            
            // Só processa se for o mesmo gameId ou um gameId posterior
            if (resultGameId >= gameInfo.game) {
              waitingResult = false;
              console.log(`[bet] 🎰 Processando resultado: ${numero}`);

              const ganhou = bets.includes(numero);

              if (ganhou) {
                console.log(`[bet] ✅ VITÓRIA! Número ${numero} na tentativa ${currentAttempt}/${maxAttempts}`);
                clearTimeout(timeout);
                cleanup();
                resolve({
                  success: true,
                  result: "win",
                  attempts: currentAttempt,
                  winningNumber: numero,
                  message: `Vitória no número ${numero} (tentativa ${currentAttempt}/${maxAttempts})`
                });
                return;
              }

              // Perdeu
              console.log(`[bet] ❌ PERDA na tentativa ${currentAttempt}/${maxAttempts}`);

              if (currentAttempt >= maxAttempts) {
                console.log(`[bet] 💀 Fim das tentativas. Derrota total.`);
                clearTimeout(timeout);
                cleanup();
                resolve({
                  success: true,
                  result: "loss",
                  attempts: currentAttempt,
                  winningNumber: numero,
                  message: `Derrota após ${currentAttempt} tentativas`
                });
                return;
              }

              // Tem mais gales - faz próxima aposta na MESMA conexão
              console.log(`[bet] 🔄 Preparando GALE ${currentAttempt}...`);
              placeBet();
            } else {
              console.log(`[bet] ⏭️ Ignorando resultado antigo (gameId: ${resultGameId} < ${gameInfo.game})`);
            }
          }
        }
      }
    });

    ws.on("error", (err) => {
      console.error("[bet] ❌ Erro no WebSocket:", err.message);
      clearTimeout(timeout);
      cleanup();
      reject(new Error(`Erro no WebSocket: ${err.message}`));
    });

    ws.on("close", () => {
      console.log("[bet] 🔌 WebSocket fechado");
    });
  });
}

// =========================
// API REST
// =========================

const app = express();
app.use(express.json());

app.post("/api/bet", async (req, res) => {
  try {
    if (!authToken) {
      return res.status(503).json({
        success: false,
        error: "Sistema não inicializado. Token não disponível."
      });
    }

    const signal = req.body;
    
    if (!signal.bets || !signal.roulette_url) {
      return res.status(400).json({
        success: false,
        error: "Dados do sinal incompletos. Necessário: bets, roulette_url, gales"
      });
    }

    const result = await processBet(signal);
    
    res.json({
      success: true,
      ...result
    });

  } catch (err) {
    console.error("[api] ❌ Erro ao processar aposta:", err.message);
    res.status(500).json({
      success: false,
      error: err.message
    });
  }
});

app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    tokenActive: !!authToken,
    timestamp: new Date().toISOString()
  });
});

// =========================
// INICIALIZAÇÃO
// =========================

async function initialize() {
  try {
    console.log("\n=================================");
    console.log("🚀 Iniciando API de Apostas");
    console.log("=================================\n");

    // Fazer login inicial
    authToken = await loginAndGetToken();
    
    // Configurar renovação automática
    startTokenRenewal();
    
    // Iniciar servidor API
    app.listen(API_PORT, () => {
      console.log(`\n✅ API rodando na porta ${API_PORT}`);
      console.log(`📍 Endpoint: POST http://localhost:${API_PORT}/api/bet`);
      console.log(`📍 Health: GET http://localhost:${API_PORT}/health\n`);
    });

  } catch (err) {
    console.error("❌ Erro ao inicializar:", err.message);
    process.exit(1);
  }
}

initialize();