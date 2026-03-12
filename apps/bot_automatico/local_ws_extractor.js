// local_ws_extractor.js
const express = require('express');
const bodyParser = require('body-parser');
const cors = require('cors');
const { chromium } = require('playwright');

require("dotenv").config();
const axios = require("axios");
const WebSocket = require("ws");
const puppeteer = require('puppeteer');

const app = express();
app.use(bodyParser.json());

// libera CORS para seu front (ajuste o origin conforme seu domínio)
app.use(cors({
  origin: true, // em produção, coloque o domínio exato do seu front
}));

/**
 * Abre o link do jogo com Puppeteer e captura:
 *  - URLs de WebSocket
 *  - Requisições de rede (para tentar identificar a URL do vídeo)
 *
 * Retorna um objeto com:
 *  {
 *    wsUrl,          // URL principal de WebSocket (compatível com o front)
 *    wsUrls,         // lista completa de websockets encontrados
 *    videoUrl,       // melhor chute de URL de vídeo/stream
 *    mediaUrls,      // todas as URLs de mídia/stream que pareceram vídeo
 *    allRequestUrls, // todas as URLs de requisição capturadas
 *  }
 */
async function getUrlsWithPuppeteer(gameLink) {
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  try {
    const page = await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36');

    // Coleta de WebSockets
    const webSocketUrls = new Set();

    // Coleta de requisições de rede
    const requestRecords = [];

    // Proxy em window.WebSocket para capturar URLs criadas via JS
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

    // Captura logs de console com "WS_INTERCEPTED"
    page.on('console', msg => {
      const text = msg.text();
      if (text.includes('WS_INTERCEPTED:')) {
        const url = text.split('WS_INTERCEPTED:')[1].trim();
        webSocketUrls.add(url);
      }
    });

    // Evento nativo de WebSocket do Puppeteer
    page.on('websocket', ws => {
      webSocketUrls.add(ws.url());
    });

    // Captura todas as requisições de rede feitas pela página
    page.on('request', req => {
      try {
        requestRecords.push({
          url: req.url(),
          resourceType: req.resourceType()
        });
      } catch (_) {
        // evita quebrar caso alguma informação não esteja disponível
      }
    });

    // Navega até o link do jogo
    await page.goto(gameLink, { waitUntil: 'networkidle2', timeout: 60000 });

    // Espera alguns segundos para garantir que scripts e streams foram inicializados
    await new Promise(resolve => setTimeout(resolve, 5000));

    // Recupera URLs interceptadas via window.__wsUrls
    const capturedUrls = await page.evaluate(() => window.__wsUrls || []);
    capturedUrls.forEach(u => webSocketUrls.add(u));

    // Lista final de websockets sem duplicatas
    const wsUrls = Array.from(webSocketUrls);

    // Heurística para escolher um WebSocket "principal"
    let pragmaticWs = wsUrls.find(url =>
      url.includes('pragmatic') ||
      url.includes('livecasino') ||
      url.includes('game')
    );
    const mainWsUrl = pragmaticWs || (wsUrls.length > 0 ? wsUrls[0] : null);

    // --- Identificação de possíveis URLs de vídeo/stream ---

    // Normaliza as URLs de requisições (sem duplicatas)
    const allRequestUrlsSet = new Set(requestRecords.map(r => r.url));
    const allRequestUrls = Array.from(allRequestUrlsSet);

    // Filtra por tipos de recurso e extensões/trechos comuns em streaming de vídeo
    const mediaCandidates = requestRecords.filter(r => {
      const url = r.url.toLowerCase();
      const type = (r.resourceType || '').toLowerCase();

      const isMediaType = ['media', 'xhr', 'fetch'].includes(type);
      const looksLikeVideo =
        url.includes('.m3u8') ||
        url.includes('.mpd') ||
        url.includes('hls') ||
        url.includes('manifest') ||
        url.includes('stream') ||
        url.includes('video');

      return isMediaType && looksLikeVideo;
    });

    const mediaUrls = Array.from(new Set(mediaCandidates.map(r => r.url)));

    // Melhor chute de URL de vídeo
    let mainVideoUrl = null;
    if (mediaUrls.length > 0) {
      // prioriza .m3u8
      mainVideoUrl = mediaUrls.find(u => u.toLowerCase().includes('.m3u8')) ||
                     mediaUrls.find(u => u.toLowerCase().includes('.mpd')) ||
                     mediaUrls[0];
    }

    // Retorna tudo o que coletamos
    return {
      wsUrl: mainWsUrl || null,  // compatível com o front atual
      wsUrls,                    // todos os websockets encontrados
      videoUrl: mainVideoUrl,    // melhor chute da URL de vídeo
      mediaUrls,                 // todas as URLs de mídia/stream que parecem vídeo
      allRequestUrls             // todas as URLs requisitadas pela página
    };
  } finally {
    await browser.close();
  }
}

app.post('/extract-ws', async (req, res) => {
  const { iframeUrl } = req.body;

  try {
    if (!iframeUrl) {
      return res.status(400).json({ error: 'iframeUrl é obrigatório' });
    }

    console.log('[EXTRACT] Recebendo iframeUrl:', iframeUrl);

    const urlsInfo = await getUrlsWithPuppeteer(iframeUrl);

    // Se absolutamente nada de WS foi encontrado, ainda assim devolvemos
    // as listas para você inspecionar no front (não jogamos erro aqui).
    if (!urlsInfo || (!urlsInfo.wsUrl && (!urlsInfo.wsUrls || urlsInfo.wsUrls.length === 0))) {
      console.warn('[EXTRACT] Nenhuma URL de WebSocket encontrada, retornando apenas listas de requisições.');
    }

    // A resposta inclui:
    //  - wsUrl (se encontrado)
    //  - wsUrls
    //  - videoUrl
    //  - mediaUrls
    //  - allRequestUrls
    return res.json(urlsInfo);

  } catch (err) {
    console.error('[EXTRACT] Erro:', err);
    return res.status(500).json({ error: 'Falha ao extrair URLs', details: err.message });
  }
});

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => {
  console.log(`Extractor Playwright rodando em http://localhost:${PORT}`);
});