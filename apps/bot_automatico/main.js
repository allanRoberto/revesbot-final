// main.js
// Sistema de apostas automáticas com gerenciamento de múltiplas mesas
// Cada mesa mantém conexão WebSocket ativa com reconexão automática
//
// Requisitos:
//   npm install dotenv axios ws puppeteer express

require("dotenv").config();
const express = require("express");
const axios = require("axios");
const WebSocket = require("ws");
const puppeteer = require("puppeteer");
const fs = require("fs");

// =========================
// CONFIGURAÇÕES
// =========================

const DEPLOY_STAGE = String(process.env.DEPLOY_STAGE || "").trim().toLowerCase();
const DEFAULT_AUTH_BASE_URL =
  DEPLOY_STAGE === "develop" || DEPLOY_STAGE === "dev" || DEPLOY_STAGE === "development"
    ? "https://auth-dev.revesbot.com.br"
    : "https://auth.revesbot.com.br";
const AUTH_BASE_URL = process.env.AUTH_BASE_URL || DEFAULT_AUTH_BASE_URL;
const AUTH_EMAIL = "romulogoncalves95@gmail.com";
const AUTH_PASSWORD = "497856Drs@";
const AUTH_EMAIL_FALLBACK = process.env.AUTH_EMAIL || AUTH_EMAIL_FALLBACK;
const AUTH_PASSWORD_FALLBACK = process.env.AUTH_PASSWORD || AUTH_PASSWORD_FALLBACK;
const API_PORT = process.env.API_PORT || 3000;
const TOKEN_RENEWAL_INTERVAL = 20 * 60 * 1000; // 20 minutos
const PING_INTERVAL = 5000; // Ping a cada 5 segundos
const RECONNECT_DELAY = 500; // Delay entre tentativas de reconexão (ms)
const MAX_RECONNECT_BEFORE_TOKEN_REFRESH = 3; // Força renovação de token após N falhas
const DEBUG_MODE = process.env.DEBUG_MODE === 'true';

function readNumberEnv(name, fallback, minValue = 0) {
  const raw = process.env[name];
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < minValue) {
    return fallback;
  }
  return parsed;
}

const START_GAME_TIMEOUT = readNumberEnv("START_GAME_TIMEOUT", 60000, 15000);
const AUTH_LOGIN_TIMEOUT = readNumberEnv("AUTH_LOGIN_TIMEOUT", 60000, 15000);
const AUTH_LOGIN_RETRIES = readNumberEnv("AUTH_LOGIN_RETRIES", 2, 1);
const AUTH_LOGIN_RETRY_DELAY_MS = readNumberEnv("AUTH_LOGIN_RETRY_DELAY_MS", 3000, 0);
const TABLE_CONNECT_CONCURRENCY = readNumberEnv("TABLE_CONNECT_CONCURRENCY", 2, 1);
const TABLE_CONNECT_STAGGER_MS = readNumberEnv("TABLE_CONNECT_STAGGER_MS", 1500, 0);

if (!process.env.AUTH_EMAIL) {
  console.warn("[config] AUTH_EMAIL ausente; usando fallback hardcoded (deprecated).");
}
if (!process.env.AUTH_PASSWORD) {
  console.warn("[config] AUTH_PASSWORD ausente; usando fallback hardcoded (deprecated).");
}

// Sequência fixa de fichas por tentativa
const BET_SEQUENCE = [1.0, 1.0, 1.5, 2.5];



function detectMessageFormat(text) {
  if (!text) return "unknown";
  const t = text.trim();
  if (t.startsWith("{") || t.startsWith("[")) return "json";
  if (t.startsWith("<")) return "xml";
  return "unknown";
}

function isBetsOpen(text) {
  const format = detectMessageFormat(text);

  // XML
  if (format === "xml") {
    return text.includes("<betsopen");
  }

  // JSON (formato real Pragmatic)
  if (format === "json") {
    try {
      const payload = JSON.parse(text);
      return !!payload?.betsopen;
    } catch {
      return false;
    }
  }

  return false;
}


function isTableIdle(text) {
  const format = detectMessageFormat(text);

  // XML
  if (format === "xml") {
    return text.includes('idle="true"') && text.includes('type="timeout"');
  }

  // JSON
  if (format === "json") {
    try {
      const payload = JSON.parse(text);

      return (
        payload?.type === "timeout" ||
        payload?.event === "idle" ||
        payload?.idle === true
      );
    } catch {
      return false;
    }
  }

  return false;
}

function getWinningNumber(text) {
  const format = detectMessageFormat(text);

  // XML
  if (format === "xml") {
    const match = text.match(/gameresult[^>]*score="(\d+)"/);
    return match ? Number(match[1]) : null;
  }

  // JSON (formato real Pragmatic)
  if (format === "json") {
    try {
      const payload = JSON.parse(text);
      if (!payload?.gameresult?.score) return null;
      return Number(payload.gameresult.score);
    } catch {
      return null;
    }
  }

  return null;
}

function getResultGameId(text) {
  const format = detectMessageFormat(text);

  // XML
  if (format === "xml") {
    const match = text.match(/gameresult[^>]*id="([^"]+)"/);
    return match ? match[1] : null;
  }

  // JSON (formato real Pragmatic)
  if (format === "json") {
    try {
      const payload = JSON.parse(text);
      return payload?.gameresult?.id ?? null;
    } catch {
      return null;
    }
  }

  return null;
}

function parseBetError(text) {
  const format = detectMessageFormat(text);

  // =========================
  // XML
  // =========================
  if (format === "xml" && text.includes("betValidationError")) {
    const match = text.match(/code="([^"]+)"[^>]*desc="([^"]+)"/);
    if (!match) return null;

    return {
      code: match[1],
      message: match[2]
    };
  }

  // =========================
  // JSON (formato real Pragmatic)
  // =========================
  if (format === "json") {
    try {
      const payload = JSON.parse(text);

      if (!payload?.betValidationError) return null;

      return {
        code: payload.betValidationError.code,
        message: payload.betValidationError.desc,
        betCode: payload.betValidationError.betCode,
        amount: payload.betValidationError.amount,
        table: payload.betValidationError.table
      };
    } catch {
      return null;
    }
  }

  return null;
}
function buildPingMessage() {
  return `<ping time="${Date.now()}"></ping>`;
}
// =========================
// ESTADO GLOBAL
// =========================

let authToken = null;
let tokenRenewalTimer = null;
let tokenLastRenewal = null;
let tablePool = null;  // Referência global para atualizar tokens

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
// FUNÇÕES AUXILIARES
// =========================

function addReconnect(wsUrl) {
  const url = new URL(wsUrl);
  url.searchParams.set('reconnect', 'true');
  return url.toString();
}

function isLikelyGameWebSocketUrl(url) {
  const raw = String(url || "").trim().toLowerCase();
  if (!raw) {
    return false;
  }
  return (
    raw.startsWith("ws://") ||
    raw.startsWith("wss://")
  ) && (
    raw.includes("pragmatic") ||
    raw.includes("livecasino") ||
    raw.includes("game")
  );
}

function isIgnoredGameWebSocketUrl(url) {
  const raw = String(url || "").trim().toLowerCase();
  if (!raw) {
    return false;
  }
  return (
    raw.includes("/chat") ||
    raw.includes("chat.") ||
    raw.includes("pragmaticplaylive.net/chat") ||
    raw.includes("generic")
  );
}

function chooseBestGameWebSocketUrl(urls) {
  const normalizedUrls = Array.from(
    new Set(
      (Array.isArray(urls) ? urls : [])
        .map((url) => String(url || "").trim())
        .filter(Boolean)
    )
  );

  const candidates = normalizedUrls
    .filter((url) => isLikelyGameWebSocketUrl(url))
    .filter((url) => !isIgnoredGameWebSocketUrl(url));

  if (candidates.length === 0) {
    return null;
  }

  const scoreUrl = (url) => {
    const raw = String(url || "").toLowerCase();
    let score = 0;
    if (raw.includes("/game")) score += 100;
    if (raw.includes("table")) score += 30;
    if (raw.includes("tableid")) score += 20;
    if (raw.includes("game")) score += 10;
    if (raw.includes("pragmatic")) score += 5;
    if (raw.includes("livecasino")) score += 5;
    return score;
  };

  candidates.sort((a, b) => scoreUrl(b) - scoreUrl(a) || a.localeCompare(b));
  return candidates[0];
}

// =========================
// FUNÇÕES DE LOGIN
// =========================

async function loginAndGetToken() {
  const url = `${AUTH_BASE_URL}/api/auth/login`;
  const payload = { email: AUTH_EMAIL, password: AUTH_PASSWORD };

  console.log("🔐 Fazendo login...");
  let lastError = null;

  for (let attempt = 1; attempt <= AUTH_LOGIN_RETRIES; attempt++) {
    try {
      const response = await axios.post(url, payload, {
        timeout: AUTH_LOGIN_TIMEOUT,
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
      
      console.log("✅ Login realizado com sucesso\n");
      tokenLastRenewal = Date.now();
      return token;
    } catch (error) {
      lastError = error;
      if (attempt >= AUTH_LOGIN_RETRIES) {
        break;
      }

      console.warn(
        `⚠️ Login falhou (${error.message}). Nova tentativa em ${AUTH_LOGIN_RETRY_DELAY_MS}ms...`
      );

      if (AUTH_LOGIN_RETRY_DELAY_MS > 0) {
        await new Promise((resolve) => setTimeout(resolve, AUTH_LOGIN_RETRY_DELAY_MS));
      }
    }
  }

  throw lastError;
}

async function renewToken() {
  try {
    console.log("🔄 Renovando token...");
    authToken = await loginAndGetToken();

    // IMPORTANTE: Atualiza o token em TODOS os TableManagers
    if (tablePool) {
      tablePool.updateAuthToken(authToken);
      console.log(`✅ Token atualizado em ${tablePool.managers.size} mesas`);
    }
  } catch (err) {
    console.error("❌ Erro ao renovar token:", err.message);

    // Se falhar, tenta novamente em 30 segundos
    console.log("⏳ Tentando renovar novamente em 30 segundos...");
    setTimeout(renewToken, 30000);
  }
}

function startTokenRenewal() {
  if (tokenRenewalTimer) {
    clearInterval(tokenRenewalTimer);
  }
  
  tokenRenewalTimer = setInterval(renewToken, TOKEN_RENEWAL_INTERVAL);
  if (DEBUG_MODE) {
    console.log(`Token será renovado a cada ${TOKEN_RENEWAL_INTERVAL / 60000} minutos`);
  }
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
    ],
  });

  try {
    const page = await browser.newPage();
    const client = await page.target().createCDPSession();
    await client.send("Network.enable");

    // User-agent completo de Chrome real
    await page.setUserAgent(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      );
    
    const webSocketUrls = new Set();

    await page.evaluateOnNewDocument(() => {
      const originalWebSocket = window.WebSocket;
      window.WebSocket = new Proxy(originalWebSocket, {
        construct(target, args) {
          const url = args[0];
          console.log("WS_INTERCEPTED:", url);
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
        if (url) {
          webSocketUrls.add(url);
        }
      }
    });

    page.on("websocket", (wso) => {
      const url = wso.url();
      if (url) {
        webSocketUrls.add(url);
      }
    });

    client.on("Network.webSocketCreated", ({ url }) => {
      if (url) {
        webSocketUrls.add(url);
      }
    });

    await page.goto(gameLink, {
        waitUntil: "networkidle2",
        timeout: 60000,
      });
  
    const maxWait = 15000;
    const startTime = Date.now();
    let selectedUrl = null;
    while ((Date.now() - startTime) < maxWait) {
        const capturedUrls = await page.evaluate(() => window.__wsUrls || []);
        capturedUrls.forEach((url) => {
          if (url) {
            webSocketUrls.add(url);
          }
        });
        selectedUrl = chooseBestGameWebSocketUrl(Array.from(webSocketUrls));
        if (selectedUrl) {
          break;
        }
        await new Promise(r => setTimeout(r, 250));
    }

    const allUrls = Array.from(webSocketUrls);

    if (selectedUrl) {
      if (DEBUG_MODE) {
        console.log("[ws] URLs capturadas:", allUrls);
        console.log("[ws] URL escolhida:", selectedUrl);
      }
      return selectedUrl;
    }

    if (DEBUG_MODE) {
      console.error("[ws] Nenhuma URL de WebSocket capturada", {
        gameLink,
        finalPageUrl: page.url(),
        capturedCount: allUrls.length,
        urls: allUrls,
        ignoredOnly: allUrls.length > 0 && allUrls.every((url) => isIgnoredGameWebSocketUrl(url)),
      });
    }

    throw new Error(
      allUrls.length > 0 && allUrls.every((url) => isIgnoredGameWebSocketUrl(url))
        ? "Apenas WebSocket ignorado (chat/generic) foi capturado"
        : "WebSocket URL não encontrada"
    );
  } finally {
    await browser.close();
  }
}

async function getGameWebSocketUrl(gameId, token) {
  const url = `${AUTH_BASE_URL}/api/start-game/${gameId}`;




  const { data } = await axios.get(url, {
    headers: { Cookie: `bookmaker_token=${token}` },
    timeout: START_GAME_TIMEOUT,
  });

  const gameLink =
    data?.gameUrl ||
    data?.iframeUrl ||
    data?.url ||
    data?.link ||
    data?.urlGame ||
    null;

  if (DEBUG_MODE) {
    console.log("[auth] /start-game resposta:", {
      success: !!data?.success,
      gameId,
      keys: Object.keys(data || {}),
      gameLink,
    });
  }

  if (!data?.success || !gameLink) {
    throw new Error("Falha ao iniciar o jogo");
  }
  const wsUrl = await getWebSocketUrlWithPuppeteer(gameLink);


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
    `<lpbet gm="roulette_desktop" gId="${gameInfo.game}" uId="ppc1735138579882" ck="${checksum}">` +
    betsXML +
    `</lpbet></command>`;

  wsConn.send(message);
}

function parseWinningNumber(message) {
  const text = message.toString();
  const m = text.match(/gameresult[^>]*score="(\d+)"/);
  return m ? parseInt(m[1], 10) : null;
}

function extractTableIdFromWsUrl(wsUrl) {
  try {
    const url = new URL(wsUrl);
    return url.searchParams.get("tableId");
  } catch {
    return null;
  }
}

// =========================
// TABLE MANAGER
// =========================

class TableManager {
  constructor(gameId, name, rouletteId, url, authToken) {
    this.gameId = gameId;
    this.name = name;
    this.rouletteId = rouletteId;
    this.url = url;
    this.authToken = authToken;
    
    // Estado da conexão
    this.ws = null;
    this.wsUrl = null;
    this.gameInfo = null;
    this.connected = false;
    
    // Reconexão
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 3;
    this.reconnecting = false;
    
    // Aposta atual (apenas 1 por vez)
    this.currentBet = null;
    
    // Métricas
    this.stats = {
      totalBets: 0,
      wins: 0,
      losses: 0,
      errors: 0,
      lastBet: null,
      lastReconnect: null,
      uptime: Date.now()
    };
  }

 
  async initialize() {
    try {
      if (DEBUG_MODE) {
        console.log(`[${this.gameId}] Inicializando ${this.name}...`);
      }
      
      this.wsUrl = await getGameWebSocketUrl(this.gameId, this.authToken);
      await this.connect();
      
    } catch (err) {
      console.error(`❌ ${this.name}: ${err.message}`);
      throw err;
    }
  }


  async connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl);
      
      const initTimeout = setTimeout(() => {
        reject(new Error('Timeout: gameInfo não foi capturado em 15s'));
      }, 15000);
      
      this.ws.on('open', () => {

        if (!this.gameInfo) {
          this.gameInfo = { game: null, table: null };
        }
      
        if (!this.gameInfo.table) {
          const tableFromUrl = extractTableIdFromWsUrl(this.ws.url);
          if (tableFromUrl) {
            this.gameInfo.table = tableFromUrl;
      
            if (DEBUG_MODE) {
              console.log(
                `[${this.gameId}] 🎰 table capturada via URL: ${tableFromUrl}`
              );
            }
          }
        }
        if (DEBUG_MODE) {
          console.log(`[${this.gameId}] WebSocket conectado`);
        }
        this.connected = true;
        this.reconnectAttempts = 0;

        // Inicia ping para manter conexão ativa
        this.pingInterval = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
              this.ws.send(`<ping time='${Date.now()}'></ping>`);
              if (DEBUG_MODE) {
                console.log(`[${this.gameId}] 📡 Ping enviado`);
              }
            }
          }, PING_INTERVAL);
      });

      this.ws.on('message', (data) => {
        const text = data.toString();

        
        if (DEBUG_MODE) {
          console.log(`[${this.gameId}] 📨 ${text.substring(0, 100)}${text.length > 100 ? '...' : ''}`);
        }
        
        // Captura gameInfo SEMPRE
        this.captureGameInfo(text);
        
        // Verifica se já está completo
        const isReconnection = !!this.gameInfo?.table;
        
        const isReady = isReconnection 
          ? (this.gameInfo?.game !== null)
          : (this.gameInfo?.game && this.gameInfo?.table);
        
        if (isReady && initTimeout) {
          clearTimeout(initTimeout);
          if (DEBUG_MODE) {
            console.log(`[${this.gameId}] gameInfo pronto! game=${this.gameInfo.game}, table=${this.gameInfo.table}`);
          }
          resolve();
        }
        
        // Processa normalmente
        this.handleMessage(data);
      });

      this.ws.on('close', () => {
        clearTimeout(initTimeout);
        if (this.pingInterval) {
          clearInterval(this.pingInterval);
          this.pingInterval = null;
        }
        if (DEBUG_MODE) {
          console.log(`[${this.gameId}] WebSocket fechado`);
        }
        this.connected = false;
        this.handleDisconnect();
      });

      this.ws.on('error', (err) => {
        console.log(err)
        clearTimeout(initTimeout);
        console.error(`[${this.gameId}] ❌ Erro no WebSocket:`, err.message);
      });
    });
  }

  captureGameInfo(text) {
    if (!text) return;
  
    // Garante estrutura base
    if (!this.gameInfo) {
      this.gameInfo = { game: null, table: null };
    }
  
    const trimmed = text.trim();
    const isJSON = trimmed.startsWith("{") || trimmed.startsWith("[");
    
    // =========================
    // JSON MODE
    // =========================
    if (isJSON) {
      let payload;
      try {
        payload = JSON.parse(trimmed);
      } catch (e) {
        return;
      }
  
      // gameId
      if (payload?.game?.id) {
        const newGameId = String(payload.game.id);
        if (this.gameInfo.game !== newGameId) {
          const oldGame = this.gameInfo.game;
          this.gameInfo.game = newGameId;
  
          if (DEBUG_MODE) {
            console.log(
              `[${this.gameId}] 🎮 game atualizado (JSON): ${oldGame || "null"} → ${newGameId}`
            );
          }
        }
      }
  
      // tableId
      if (!this.gameInfo.table && payload?.lastgame?.tableId) {
        this.gameInfo.table = payload?.lastgame?.tableId;
  
        if (DEBUG_MODE) {
          console.log(
            `[${this.gameId}] 🎰 table capturada (JSON): ${this.gameInfo.table}`
          );
        }
      }
  
      return;
    }
  
    // =========================
    // XML MODE (original)
    // =========================
  
    // 1. Captura gameId (sempre)
    const gameMatch = text.match(/<game id="([^"]+)"/);
    if (gameMatch) {
      const newGameId = gameMatch[1];
  
      if (this.gameInfo.game !== newGameId) {
        const oldGame = this.gameInfo.game;
        this.gameInfo.game = newGameId;
  
        if (DEBUG_MODE) {
          console.log(
            `[${this.gameId}] 🎮 game atualizado: ${oldGame || "null"} → ${newGameId}`
          );
        }
      }
    }
  
    // 2. Captura tableId (só se ainda não tiver)
    if (!this.gameInfo.table) {
      const tableMatch = text.match(/tableId="([^"]+)"/);
      const subscribeMatch = text.match(/<subscribe[^>]*table="([^"]+)"/);
  
      const tableId = tableMatch?.[1] || subscribeMatch?.[1];
  
      if (tableId) {
        this.gameInfo.table = tableId;
  
        if (DEBUG_MODE) {
          console.log(
            `[${this.gameId}] 🎰 table capturada: ${tableId}`
          );
        }
      }
    }
  }

  handleMessage(data) {
    const text = data.toString();
    
    // Detecta IDLE
    if (isTableIdle(text)) {
      console.log(`⚠️  ${this.name} ficou idle - Reconectando...`);
      this.connected = false;
      this.handleDisconnect();
      return;
    }

    
    // Detecta betsopen (mesa abriu apostas)
    if (isBetsOpen(text)) {
      // Se tem aposta pendente (primeira OU gale), envia agora
      if (this.currentBet && !this.currentBet.waiting && this.currentBet.pendingGale) {
        const isFirstBet = this.currentBet.currentAttempt === 0;
        console.log(`🟢 ${this.name}: Mesa abriu - Enviando ${isFirstBet ? 'aposta' : 'gale'}...`);
        this.currentBet.pendingGale = false;
        this.sendBet();
      }
    }

    // Processa resultado
    if (this.currentBet) {
      this.processResult(text);
    }
  }

  async handleDisconnect() {
    if (this.reconnecting) return;
    this.reconnecting = true;

    // Contador de falhas consecutivas
    if (!this.consecutiveFailures) {
      this.consecutiveFailures = 0;
    }
    this.consecutiveFailures++;

    console.log(`🔄 [${this.name}] Reconectando (falha ${this.consecutiveFailures})...`);

    // Se passou de N falhas consecutivas, provavelmente o token expirou
    if (this.consecutiveFailures >= MAX_RECONNECT_BEFORE_TOKEN_REFRESH) {
      console.log(`⚠️ [${this.name}] ${this.consecutiveFailures} falhas. Renovando token...`);

      try {
        await renewToken();
        console.log(`✅ Token renovado!`);
        this.consecutiveFailures = 0; // Reset após renovar
      } catch (err) {
        console.error(`❌ Erro ao renovar token:`, err.message);
      }
    }

    // Fecha conexão antiga
    if (this.ws) {
      try {
        this.ws.removeAllListeners();
        this.ws.close();
      } catch (e) {}
    }

    // Tenta reconexão rápida primeiro (sem puppeteer)
    if (this.reconnectAttempts < this.maxReconnectAttempts && this.wsUrl) {
      this.reconnectAttempts++;
      this.stats.lastReconnect = Date.now();

      try {
        // Mantém o table, só reseta o game
        if (this.gameInfo) {
          this.gameInfo.game = null;
        }

        this.wsUrl = addReconnect(this.wsUrl);
        await new Promise(resolve => setTimeout(resolve, RECONNECT_DELAY));
        await this.connect();

        console.log(`✅ [${this.name}] Reconectada!`);
        this.consecutiveFailures = 0;
        this.reconnecting = false;
        return;

      } catch (err) {
        console.error(`❌ [${this.name}] Falha rápida:`, err.message);
        this.reconnecting = false;

        // Tenta novamente imediatamente
        setImmediate(() => this.handleDisconnect());
        return;
      }
    }

    // Reinício completo (com puppeteer)
    console.log(`🔄 [${this.name}] Reinício completo...`);
    this.reconnectAttempts = 0;
    this.gameInfo = null;

    try {
      await this.initialize();
      console.log(`✅ [${this.name}] Reiniciada!`);
      this.consecutiveFailures = 0;
    } catch (err) {
      console.error(`❌ [${this.name}] Falha no reinício:`, err.message);
      this.stats.errors++;

      // Agenda nova tentativa em 3 segundos
      setTimeout(() => {
        this.reconnecting = false;
        this.handleDisconnect();
      }, 3000);
      return;
    }

    this.reconnecting = false;
  }

  async placeBet(signal) {
    if (this.currentBet) {
      throw new Error('Já existe uma aposta em andamento nesta mesa');
    }

    if (!this.connected) {
      throw new Error('Mesa não está conectada');
    }
    
    if (!this.gameInfo?.game || !this.gameInfo?.table) {
      throw new Error('Mesa não está pronta: gameInfo incompleto');
    }

    // Tudo pronto, pode apostar!
    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        if (this.currentBet && this.currentBet.resolve === resolve) {
          this.currentBet = null;
          reject(new Error('Timeout: aposta não foi processada em 120s'));
        }
      }, 120000);

      this.currentBet = {
        signal,
        currentAttempt: 0,
        maxAttempts: signal.gales,
        resolve: (result) => {
          clearTimeout(timeoutId);
          resolve(result);
        },
        reject: (err) => {
          clearTimeout(timeoutId);
          reject(err);
        },
        startTime: Date.now(),
        waiting: false,
      };

      this.stats.totalBets++;
      this.stats.lastBet = Date.now();
      
      // NÃO envia aqui - aguarda betsopen em handleMessage
      // Primeira aposta: envia após 1 segundo (não aguarda betsopen)
        setTimeout(() => {
            this.sendBet();
        }, 3000);
    });
  }

  sendBet() {
    if (!this.currentBet) return;

    this.currentBet.currentAttempt++;
    const attempt = this.currentBet.currentAttempt;
    const max = this.currentBet.maxAttempts;
    
    //const chipValue = calculateChipValue(attempt - 1);
    const chipValue = this.currentBet.signal.valor || calculateChipValue(attempt - 1);

    
    console.log(`💰 ${this.name}: Aposta ${attempt}/${max} - Ficha: ${chipValue} - ${this.currentBet.signal.bets}`);
    
    sendBet(this.ws, this.gameInfo, this.currentBet.signal.bets, chipValue);
    this.currentBet.waiting = true;
  }

  processResult(text) {
    if (!this.currentBet || !this.currentBet.waiting) return;

    // Verifica erro de validação
    const betError = parseBetError(text);
    if (betError) {
      console.log(`❌ ${this.name}: ${betError.message}`);
      this.stats.errors++;

      this.currentBet.resolve({
        success: false,
        result: "error",
        attempts: this.currentBet.currentAttempt,
        errorCode: betError.code,
        errorMessage: betError.message
      });

      this.currentBet = null;
      return;
    }

    // Captura resultado
    const numero = getWinningNumber(text);
    if (numero === null) return;

    const resultGameId = getResultGameId(text);
    if (!resultGameId) return;
    
    // garante comparação correta (ids grandes)
    if (BigInt(resultGameId) < BigInt(this.gameInfo.game)) return;

    this.currentBet.waiting = false;
    const ganhou = this.currentBet.signal.bets.includes(numero);

    if (ganhou) {
      console.log(`✅ ${this.name}: WIN no número ${numero}!`);
      this.stats.wins++;
      
      this.currentBet.resolve({
        success: true,
        result: "win",
        attempts: this.currentBet.currentAttempt,
        winningNumber: numero,
        message: `Vitória no número ${numero} (tentativa ${this.currentBet.currentAttempt}/${this.currentBet.maxAttempts})`
      });
      this.currentBet = null;
      return;
    }

    console.log(`❌ ${this.name}: LOSS - Número ${numero}`);

    if (this.currentBet.currentAttempt >= this.currentBet.maxAttempts) {
      this.stats.losses++;
      
      this.currentBet.resolve({
        success: true,
        result: "loss",
        attempts: this.currentBet.currentAttempt,
        winningNumber: numero,
        message: `Derrota após ${this.currentBet.currentAttempt} tentativas`
      });
      this.currentBet = null;
      return;
    }

    console.log(`🔄 ${this.name}: Preparando gale (aguardando betsopen)...`);
    
    // Marca como pendente - enviará quando receber <betsopen>
    this.currentBet.pendingGale = true;
  }

  getHealth() {
    return {
      gameId: this.gameId,
      name: this.name,
      rouletteId: this.rouletteId,
      connected: this.connected,
      hasGameInfo: !!this.gameInfo,
      gameInfo: this.gameInfo,
      reconnectAttempts: this.reconnectAttempts,
      currentBet: this.currentBet ? {
        attempt: this.currentBet.currentAttempt,
        maxAttempts: this.currentBet.maxAttempts,
        elapsed: Date.now() - this.currentBet.startTime
      } : null,
      stats: {
        ...this.stats,
        winRate: this.stats.totalBets > 0 
          ? ((this.stats.wins / this.stats.totalBets) * 100).toFixed(2) + '%'
          : 'N/A'
      },
      uptime: Date.now() - this.stats.uptime
    };
  }
}

// =========================
// TABLE POOL
// =========================

class TableManagerPool {
  constructor(authToken) {
    this.authToken = authToken;
    this.managers = new Map();
  }

  /**
   * Atualiza o token em TODOS os TableManagers conectados.
   * Chamado quando o token é renovado.
   */
  updateAuthToken(newToken) {
    this.authToken = newToken;
    for (const manager of this.managers.values()) {
      manager.authToken = newToken;
      if (DEBUG_MODE) {
        console.log(`[${manager.gameId}] Token atualizado`);
      }
    }
  }

  async createManager(tableConfig) {
    const manager = new TableManager(
      String(tableConfig.gameId),
      tableConfig.name,
      tableConfig.rouletteId,
      tableConfig.url,
      this.authToken
    );

    await manager.initialize();
    this.managers.set(String(tableConfig.gameId), manager);
    return manager;
  }

  getByGameId(gameId) {
    return this.managers.get(String(gameId));
  }

  getByRouletteId(rouletteId) {
    for (const manager of this.managers.values()) {
      if (manager.rouletteId === rouletteId) {
        return manager;
      }
    }
    return null;
  }

  async placeBet(signal) {
    const gameIdMatch = signal.roulette_url.match(/\/play\/(\d+)/);
    if (!gameIdMatch) {
      throw new Error("Não foi possível extrair game_id da URL");
    }

    const gameId = String(gameIdMatch[1]);
    const manager = this.getByGameId(gameId);

    if (!manager) {
      throw new Error(`Mesa ${gameId} não está conectada`);
    }

    return await manager.placeBet(signal);
  }
}

// =========================
// API REST
// =========================

const app = express();

// Configuração de CORS para permitir requisições do frontend
app.use((req, res, next) => {
  res.header("Access-Control-Allow-Origin", "*");
  res.header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
  res.header("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization");

  // Responde imediatamente às requisições OPTIONS (preflight)
  if (req.method === "OPTIONS") {
    return res.sendStatus(200);
  }
  next();
});

app.use(express.json());

app.post("/api/bet", async (req, res) => {
  try {
    if (!authToken) {
      return res.status(503).json({
        success: false,
        error: "Sistema não inicializado"
      });
    }

    const signal = req.body;

    if (!signal.bets || !signal.roulette_url || signal.gales === undefined) {
      return res.status(400).json({
        success: false,
        error: "Dados incompletos. Necessário: bets, roulette_url, gales"
      });
    }

    // Extrai gameId para verificar status da mesa
    const gameIdMatch = signal.roulette_url.match(/\/play\/(\d+)/);
    if (!gameIdMatch) {
      return res.status(400).json({
        success: false,
        error: "URL inválida. Não foi possível extrair game_id"
      });
    }

    const gameId = String(gameIdMatch[1]);
    const manager = tablePool.getByGameId(gameId);

    // Retorna status específico se mesa não está disponível
    if (!manager) {
      return res.status(503).json({
        success: false,
        error: `Mesa ${gameId} não está conectada`,
        status: "table_offline",
        gameId: gameId,
        connectedTables: Array.from(tablePool.managers.keys())
      });
    }

    if (!manager.connected) {
      return res.status(503).json({
        success: false,
        error: `Mesa ${manager.name} está reconectando`,
        status: "table_reconnecting",
        gameId: gameId
      });
    }

    if (DEBUG_MODE) {
      console.log(`\n[api] Nova aposta: ${signal.bets.join(', ')} | Gales: ${signal.gales}`);
    }

    const result = await tablePool.placeBet(signal);

    res.json({
      success: true,
      ...result
    });

  } catch (err) {
    console.error("❌ Erro ao processar aposta:", err.message);
    res.status(500).json({
      success: false,
      error: err.message
    });
  }
});

app.get("/health", (req, res) => {
  const tables = [];
  
  for (const manager of tablePool.managers.values()) {
    tables.push(manager.getHealth());
  }
  
  res.json({
    status: "ok",
    tokenActive: !!authToken,
    tokenLastRenewal: tokenLastRenewal ? new Date(tokenLastRenewal).toISOString() : null,
    tablesActive: tables.length,
    tables: tables,
    timestamp: new Date().toISOString()
  });
});

app.get("/health/:gameId", (req, res) => {
  const manager = tablePool.getByGameId(req.params.gameId);

  if (!manager) {
    return res.status(404).json({ error: "Mesa não encontrada" });
  }

  res.json(manager.getHealth());
});

// Endpoint para verificar quais mesas estão prontas para receber apostas
app.get("/tables", (req, res) => {
  const tables = [];

  for (const manager of tablePool.managers.values()) {
    tables.push({
      gameId: manager.gameId,
      name: manager.name,
      rouletteId: manager.rouletteId,
      status: manager.connected ? "ready" : "reconnecting",
      connected: manager.connected,
      hasGameInfo: !!(manager.gameInfo?.game && manager.gameInfo?.table)
    });
  }

  res.json({
    total: tables.length,
    ready: tables.filter(t => t.status === "ready").length,
    tables: tables
  });
});

// Endpoint para forçar renovação do token manualmente
app.post("/api/renew-token", async (req, res) => {
  try {
    console.log("🔐 Renovação manual de token solicitada...");
    await renewToken();
    res.json({
      success: true,
      message: "Token renovado com sucesso",
      lastRenewal: new Date(tokenLastRenewal).toISOString()
    });
  } catch (err) {
    console.error("❌ Erro ao renovar token:", err.message);
    res.status(500).json({
      success: false,
      error: err.message
    });
  }
});

// =========================
// INICIALIZAÇÃO
// =========================

/**
 * Conecta uma mesa em background (não bloqueia).
 * Retenta indefinidamente se falhar.
 */
async function connectTableInBackground(tableConfig) {
  const maxRetries = 3;
  let retries = 0;

  while (true) {
    try {
      await tablePool.createManager(tableConfig);
      console.log(`✅ ${tableConfig.name} conectada`);
      return;
    } catch (err) {
      retries++;
      console.error(`❌ ${tableConfig.name}: ${err.message} (tentativa ${retries})`);

      if (retries >= maxRetries) {
        console.log(`⏳ ${tableConfig.name}: Aguardando 30s antes de tentar novamente...`);
        await new Promise(r => setTimeout(r, 30000));
        retries = 0; // Reset para tentar mais 3 vezes
      } else {
        // Espera curta entre tentativas
        await new Promise(r => setTimeout(r, 2000));
      }
    }
  }
}

function startTableConnectionsInBackground(tables) {
  const queue = [...tables];
  const workerCount = Math.min(TABLE_CONNECT_CONCURRENCY, queue.length);

  for (let workerIndex = 0; workerIndex < workerCount; workerIndex++) {
    (async () => {
      while (queue.length > 0) {
        const table = queue.shift();
        if (!table) {
          return;
        }

        if (TABLE_CONNECT_STAGGER_MS > 0) {
          await new Promise((resolve) => setTimeout(resolve, TABLE_CONNECT_STAGGER_MS));
        }

        await connectTableInBackground(table);
      }
    })().catch((err) => {
      console.error(`❌ Worker de conexão ${workerIndex + 1}: ${err.message}`);
    });
  }
}

async function initialize() {
  try {
    console.log("=================================");
    console.log("🚀 Sistema de Apostas Automáticas");
    console.log("=================================\n");

    // 1. Login
    authToken = await loginAndGetToken();
    startTokenRenewal();

    // 2. Carregar configuração de mesas
    const configPath = './tables-config.json';
    if (!fs.existsSync(configPath)) {
      throw new Error(`Arquivo ${configPath} não encontrado`);
    }

    const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    const enabledTables = config.tables.filter(t => t.enabled);

    // 3. Criar pool (vazio inicialmente)
    tablePool = new TableManagerPool(authToken);

    // 4. Iniciar API IMEDIATAMENTE (não espera mesas conectarem)
    app.listen(API_PORT, () => {
      console.log(`🌐 API rodando em http://localhost:${API_PORT}`);
      console.log(`📡 API pronta para receber apostas!`);
      console.log(`⚠️  Mesas conectando em background...\n`);
    });

    // 5. Conectar mesas em background com concorrência limitada
    console.log(
      `🎰 Iniciando conexão de ${enabledTables.length} mesas em background (${TABLE_CONNECT_CONCURRENCY} por vez)...\n`
    );

    startTableConnectionsInBackground(enabledTables);

  } catch (err) {
    console.error("❌ Erro ao inicializar:", err.message);
    process.exit(1);
  }
}

// Tratamento de sinais para shutdown gracioso
process.on('SIGINT', () => {
  console.log('\n\n🛑 Encerrando sistema...');
  if (tokenRenewalTimer) {
    clearInterval(tokenRenewalTimer);
  }
  process.exit(0);
});

process.on('SIGTERM', () => {
  console.log('\n\n🛑 Encerrando sistema...');
  if (tokenRenewalTimer) {
    clearInterval(tokenRenewalTimer);
  }
  process.exit(0);
});

initialize();
