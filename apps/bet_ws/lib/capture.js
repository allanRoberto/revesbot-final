// Abre o link da mesa num browser headless e captura a URL do WebSocket do jogo.
// Portado de apps/bot_automatico/bot_aposta.js (getWebSocketUrlWithPuppeteer):
// usa duas técnicas em paralelo (Proxy em window.WebSocket + evento nativo),
// espera os scripts subirem e filtra o WS da Pragmatic por heurística.

const fs = require('fs');
const os = require('os');
const path = require('path');
const puppeteer = require('puppeteer');

// Resolve o executável do Chrome. O disco pode não ter a versão que o Puppeteer
// baixaria por padrão, então reaproveitamos o que já está no cache
// (~/.cache/puppeteer/chrome-headless-shell/*). Override via PUPPETEER_EXECUTABLE_PATH.
function resolveExecutablePath() {
  if (process.env.PUPPETEER_EXECUTABLE_PATH) {
    return process.env.PUPPETEER_EXECUTABLE_PATH;
  }
  try {
    const p = puppeteer.executablePath();
    if (p && fs.existsSync(p)) return p;
  } catch (_) {
    /* segue para o cache */
  }
  const base = path.join(os.homedir(), '.cache', 'puppeteer', 'chrome-headless-shell');
  if (fs.existsSync(base)) {
    for (const ver of fs.readdirSync(base)) {
      const hit = path.join(base, ver, 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell');
      if (fs.existsSync(hit)) return hit;
      const linux = path.join(base, ver, 'chrome-headless-shell-linux64', 'chrome-headless-shell');
      if (fs.existsSync(linux)) return linux;
    }
  }
  return undefined; // deixa o Puppeteer tentar o default
}

// Seleciona o WS do JOGO entre os candidatos capturados.
// O socket do jogo Pragmatic é `wss://gsXX.pragmaticplaylive.net/game?...`.
// Precisamos EXCLUIR os sockets de vídeo/estatística/CDN (client., videostats.,
// CloudFront/Amazon) que só completam o handshake e não mandam o feed da mesa.
function pickGameWs(urls) {
  const isVideoOrStats = (u) =>
    /videostats|client\.|\/video|cloudfront|amazonaws|akamai|hls|\.m3u8|stats/i.test(u);

  // 1º: pragmaticplaylive com caminho /game (o socket real da mesa).
  const gamePath = urls.find(
    (u) => /pragmaticplaylive/i.test(u) && /\/game\b|game\?/i.test(u) && !isVideoOrStats(u),
  );
  if (gamePath) return gamePath;

  // 2º: qualquer pragmaticplaylive que não seja vídeo/stats.
  const prag = urls.find((u) => /pragmaticplaylive/i.test(u) && !isVideoOrStats(u));
  if (prag) return prag;

  // 3º: qualquer um que não seja claramente vídeo/stats/CDN.
  const notMedia = urls.find((u) => !isVideoOrStats(u));
  if (notMedia) return notMedia;

  // Último recurso: o primeiro.
  return urls[0];
}

async function captureGameWsUrl(gameLink, { waitMs = 15000 } = {}) {
  const browser = await puppeteer.launch({
    headless: true,
    executablePath: resolveExecutablePath(),
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    const cdp = await page.target().createCDPSession();
    await cdp.send('Network.enable');
    await page.setUserAgent(
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    );

    const wsUrls = [];
    let resolveGameWs;
    const gameWsFound = new Promise((resolve) => { resolveGameWs = resolve; });
    const recordWs = (url) => {
      if (!url) return;
      wsUrls.push(url);
      if (/pragmaticplaylive/i.test(url) && /\/game\b|game\?/i.test(url)) {
        resolveGameWs(url);
      }
    };

    // (1) Proxy em window.WebSocket, injetado antes de qualquer script rodar.
    await page.evaluateOnNewDocument(() => {
      const OriginalWebSocket = window.WebSocket;
      window.WebSocket = new Proxy(OriginalWebSocket, {
        construct(target, args) {
          window.__wsUrls = window.__wsUrls || [];
          window.__wsUrls.push(args[0]);
          return new target(...args);
        },
      });
    });

    // (2) Evento nativo do Puppeteer.
    page.on('websocket', (ws) => recordWs(ws.url()));

    // (3) CDP captura sockets de todos os frames, inclusive o iframe interno
    // da Pragmatic. É a fonte mais confiável no Chromium do servidor.
    cdp.on('Network.webSocketCreated', ({ url }) => recordWs(url));

    // Uma mesa ao vivo nunca fica realmente ociosa: vídeo, telemetria e
    // WebSockets mantêm requisições abertas. Esperar por `networkidle2` fazia
    // toda criação de sessão terminar em timeout. Basta carregar o documento e
    // aguardar diretamente o socket do jogo aparecer.
    let navigationError = null;
    const navigation = page
      .goto(gameLink, { waitUntil: 'domcontentloaded', timeout: 30000 })
      .catch((err) => { navigationError = err; });

    // O socket costuma surgir antes mesmo de o DOM terminar. Não fazemos
    // page.evaluate em loop: páginas do provedor podem manter a thread principal
    // ocupada e deixar essa chamada presa indefinidamente.
    await Promise.race([navigation, gameWsFound]);
    if (!wsUrls.some((u) => /pragmaticplaylive/i.test(u) && /\/game\b|game\?/i.test(u))) {
      await Promise.race([
        gameWsFound,
        new Promise((resolve) => setTimeout(resolve, waitMs)),
      ]);
    }

    // O proxy injetado é apenas fallback. Sua leitura tem limite próprio para
    // nunca segurar a resposta da API nem acumular Chromiums no servidor.
    let injected = [];
    if (wsUrls.length === 0) {
      injected = await Promise.race([
        page.evaluate(() => window.__wsUrls || []).catch(() => []),
        new Promise((resolve) => setTimeout(() => resolve([]), 1000)),
      ]);
    }
    const all = [...new Set([...injected, ...wsUrls])];

    if (all.length === 0) {
      if (navigationError) throw navigationError;
      throw new Error('Nenhuma URL de WebSocket encontrada na página do jogo.');
    }

    console.log(`[capture] candidatos WS (${all.length}):`);
    all.forEach((u) => console.log(`[capture]   - ${u}`));

    const gameWs = pickGameWs(all);
    console.log(`[capture] escolhido: ${gameWs}`);

    return { gameWsUrl: gameWs, allWsUrls: all };
  } finally {
    // `browser.close()` também pode ficar aguardando uma página congestionada.
    // Depois de 3s encerramos somente o Chromium criado por esta captura.
    await Promise.race([
      browser.close().catch(() => {}),
      new Promise((resolve) => setTimeout(resolve, 3000)),
    ]);
    if (browser.connected) browser.process()?.kill('SIGKILL');
  }
}

module.exports = { captureGameWsUrl };
