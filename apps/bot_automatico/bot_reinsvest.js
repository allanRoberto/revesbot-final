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
const ROULETTE_ID = process.env.ROULETTE_ID || "pragmatic-brazilian-roulette"

const SUGGESTION_QTD = Number(process.env.SUGGESTION_QTD || 27);  // quantos números pegar da sugestão
const BASE_CHIP = Number(process.env.BASE_CHIP || 0.5);           // ficha base por número
const MAX_GALES = Number(process.env.MAX_GALES || 2);             // quantidade de gales (0,1,2,...)
const USE_MARTINGALE = (process.env.USE_MARTINGALE || "true") === "true";

// Modo de aposta: "GALE" (padrão atual) ou "REINVEST" (reinvestimento de lucro, sem gales)
const BET_MODE = (process.env.BET_MODE || "REINVEST").toUpperCase();

// Quantas jogadas o modo REINVEST pode fazer antes de resetar para a ficha base
const REINVEST_MAX_ROUNDS = Number(process.env.REINVEST_MAX_ROUNDS || 3);

// Incremento mínimo de ficha no modo REINVEST (ex.: 0.5)
const CHIP_STEP = Number(process.env.CHIP_STEP || 0.5);

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

  // Modo de operação da estratégia de aposta
  mode: BET_MODE,

  // Estado específico do modo de reinvestimento de lucro
  lucroAcumulado: 0,
  reinvestRoundCount: 0,
  maxReinvestRounds: REINVEST_MAX_ROUNDS,
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
        withCredentials: true,
    });
    
    const setCookie = response.headers['set-cookie'];
    
    if (!setCookie) {
        throw new Error("Nenhum cookie retornado no login");
    }
    
    const cookieManager = new CookieManager();
    cookieManager.extractCookies(setCookie);
    const token = cookieManager.getCookie("bookmaker_token");
    
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
        
        console.log("[puppeteer] Abrindo página do jogo:", gameLink);
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
    } catch (err) {
        console.error("[puppeteer] Erro ao tentar obter o WebSocket:", err.message);
        throw err;
    } finally {
        await browser.close();
    }
}

async function getGameWebSocketUrl(gameId, token) {
    console.log("[auth] Buscando URL do WebSocket do game...");
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
  )}?quantidade=${quantidade}&incluir_protecoes=false&max_protecoes=5&incluir_zero=false&limite_historico=200&w_master=0&w_estelar=0.2&w_chain=0.6&w_temporal=0.2&target_time=18%3A15&interval_minutes=2&days_back=30`
  //console.log(`[sugestao] Buscando sugestão em: ${url}`);

  const { data } = await axios.get(url, { timeout: 15000 });

  if (!data?.sugestoes?.principais || !Array.isArray(data.sugestoes.principais)) {
    console.warn("[sugestao] Resposta inesperada, sem 'sugestoes.principais'.");
    return [];
  }

  const numeros = data.sugestoes.principais.map((s) => s.numero).filter((n) => n >= 0 && n <= 36);

  //console.log("[sugestao] Números sugeridos:", numeros);
  return numeros;
}

// =========================
// FUNÇÃO PARA CÁLCULO DA PRÓXIMA FICHA (MARTINGALE / GALE)
// =========================

// Exemplo de uma sequência de apostas em centavos para o GALE, por tentativa.
// attempt = 0 (primeira), 1 (primeiro GALE), 2 (segundo GALE), etc.
const BET_SEQUENCE = [50, 100, 200, 400, 800, 1600, 3200]; // exemplo

function calculateNextChipValue(attempt, baseChip) {
  // attempt começa em 1 na lógica atual
  const idx = attempt;

  // Se tiver valor configurado para essa tentativa, usa ele
  if (idx >= 0 && idx < BET_SEQUENCE.length) {
    return BET_SEQUENCE[idx];
  }

  // Se passar do tamanho do array, mantém o último valor
  return BET_SEQUENCE[BET_SEQUENCE.length - 1];
}

// =========================
// PARSE DA MENSAGEM BETSOPEN / RESULT
// =========================

function isBetsOpenMessage(message) {
    const text = message.toString().toLowerCase();
    // Ajuste aqui conforme o evento de "bets open" da mesa (pode ser <betsopen, "BetsOpen", etc.)
    return text.includes("betsopen");
  }

  function parseBetsOpenMessage(xmlMessage) {
    const gameMatch = xmlMessage.match(/game="([^"]+)"/);
    const tableMatch = xmlMessage.match(/table="([^"]+)"/);
    return (gameMatch && tableMatch) ? { game: gameMatch[1], table: tableMatch[1] } : null;
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



// =========================
// ENVIAR APOSTA
// =========================

function generateChecksumTimestamp() {
    return Date.now().toString();
}

function sendBet(ws, gameInfo, bets, valorAposta) {
    if (!gameInfo || !gameInfo.table || !gameInfo.game) {
        console.error("[bet] gameInfo inválido. Não é possível montar a aposta.");
        return;
    }

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
// CONTROLE DE SESSÃO (GALE / REINVEST)
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
  session.lastResult = null;

  // No modo GALE, sempre reinicia a ficha a partir da base.
  // No modo REINVEST, mantemos o valor atual de ficha (controlado pela estratégia de reinvestimento).
  if (session.mode === "GALE") {
    session.currentChip = BASE_CHIP;
    session.maxAttempts = 1 + MAX_GALES;
  }

  session.state = SessionState.WAITING_BETSOPEN;
  /* console.log(
    `[sessao] Nova sessão iniciada. Números=${bets.join(
      ","
    )} | maxTentativas=${session.maxAttempts}`
  ); */

}

// =========================
// ESTRATÉGIA DE REINVESTIMENTO DE LUCRO
// =========================

function resetReinvestCycle() {
  console.log(
    `[reinvest] Resetando ciclo. Voltando ficha para base=${session.baseChip.toFixed(
      2
    )} e zerando lucro acumulado.`
  );
  session.currentChip = session.baseChip;
  session.lucroAcumulado = 0;
  session.reinvestRoundCount = 0;
}

function adjustReinvestStake(qtdNumeros) {
  if (!qtdNumeros || qtdNumeros <= 0) return;

  let chip = session.currentChip || session.baseChip;
  let lucro = session.lucroAcumulado;

  if (chip < session.baseChip) {
    chip = session.baseChip;
  }

  let changed = false;

  while (true) {
    const nextChip = chip + CHIP_STEP;
    const custoProxNivel = nextChip * qtdNumeros;

    // Só sobe de nível se o lucro acumulado for suficiente para bancar
    // uma aposta inteira no próximo patamar de ficha.
    if (lucro >= custoProxNivel) {
      chip = nextChip;
      lucro -= custoProxNivel;
      changed = true;
    } else {
      break;
    }
  }

  session.currentChip = chip;
  session.lucroAcumulado = lucro;

  if (changed) {
    console.log(
      `[reinvest] Nova ficha por número=${chip.toFixed(
        2
      )} | lucro restante para reinvestimento=${lucro.toFixed(2)}`
    );
  }
}

function handleBetsOpenReinvest() {
  // Se já atingiu o número máximo de jogadas do ciclo de reinvestimento,
  // reseta para a ficha base e zera o acumulado.
  if (session.reinvestRoundCount >= session.maxReinvestRounds) {
    resetReinvestCycle();
  }

  const qtdNumeros = session.bets.length || SUGGESTION_QTD;

  if (!session.currentChip || session.currentChip < session.baseChip) {
    session.currentChip = session.baseChip;
  }

  session.reinvestRoundCount += 1;

  console.log(
    `[reinvest] Aposta ${session.reinvestRoundCount}/${session.maxReinvestRounds} | numeros=${qtdNumeros} | ficha=${session.currentChip.toFixed(
      2
    )} | lucroAcumulado=${session.lucroAcumulado.toFixed(2)}`
  );

  sendBet(ws, session.gameInfo, session.bets, session.currentChip);
  session.state = SessionState.BET_PLACED;
}

function handleRoundResultReinvest(ganhou, numero) {
  const qtdNumeros = session.bets.length || SUGGESTION_QTD;
  const chip = session.currentChip || session.baseChip;
  const custoAposta = chip * qtdNumeros;

  if (ganhou) {
    const retornoBruto = 36 * chip;
    const lucroRodada = retornoBruto - custoAposta;
    session.lucroAcumulado += lucroRodada;

    console.log(
      `[reinvest] ✅ WIN | numero=${numero} | ganhoBruto=${retornoBruto.toFixed(
        2
      )} | custo=${custoAposta.toFixed(2)} | lucroRodada=${lucroRodada.toFixed(
        2
      )} | lucroAcumulado=${session.lucroAcumulado.toFixed(2)}`
    );
  } else {
    session.lucroAcumulado -= custoAposta;
    if (session.lucroAcumulado < 0) session.lucroAcumulado = 0;

    console.log(
      `[reinvest] ❌ LOSS | numero=${numero} | custo=${custoAposta.toFixed(
        2
      )} | lucroAcumulado=${session.lucroAcumulado.toFixed(2)}`
    );
  }

  // Ajusta a ficha possível com base no lucro acumulado após essa rodada.
  adjustReinvestStake(qtdNumeros);

  // Sempre encerra a sessão após uma única aposta (sem GALE).
  session.state = SessionState.IDLE;
  session.bets = [];
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

  // Modo de reinvestimento de lucro: uma única aposta por rodada, sem GALE.
  if (session.mode === "REINVEST") {
    handleBetsOpenReinvest();
    return;
  }

  // Modo GALE: calcula valor da ficha para esta tentativa
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

  // Se estivermos no modo de reinvestimento, delega para a lógica específica.
  if (session.mode === "REINVEST") {
    handleRoundResultReinvest(ganhou, numero);
    return;
  }

  // Modo GALE (padrão atual)
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
    `[sessao] ❌ LOSS na tentativa ${session.attempt}/${session.maxAttempts} | número=${numero}`
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

    // Debug opcional:
    //console.log("[ws] MSG:", text);

    // 1) Checa bets open
    if (isBetsOpenMessage(text)) {
      console.log("[ws] Apostas abertas...");

      const gameInfo = parseBetsOpenMessage(text);
      if (!gameInfo) {
        console.warn("[ws] Não conseguiu extrair gameInfo da mensagem de betsopen.");
        return;
      }

      handleBetsOpen(gameInfo);
      return;
    }

    // 2) Checa resultado (winning number)
    const numero = parseWinningNumber(text);
    if (numero !== null) {
      handleRoundResult(numero);
      return;
    }
  });

  ws.on("close", () => {
    console.log("[ws] Conexão fechada. Tentando reconectar em breve...");
    setTimeout(connectWebSocket, RECONNECT_DELAY_MS);
  });

  ws.on("error", (err) => {
    console.error("[ws] Erro no WebSocket:", err.message);
    try {
      ws.close();
    } catch (_) {}
    setTimeout(connectWebSocket, RECONNECT_DELAY_MS);
  });
}

// =========================
// MAIN
// =========================

async function main() {
  try {
    console.log("[main] Iniciando bot_auto...");

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