// ws_sniffer.js
// Abre a URL do jogo, detecta o WebSocket do GAME
// e imprime TODAS as mensagens enviadas e recebidas nele.
//
// Uso:
//   node ws_sniffer.js "URL_DO_IFRAME_DO_JOGO"
//
// Requer: npm install puppeteer

const puppeteer = require('puppeteer');

async function main() {
  const iframeUrl = process.argv[2];

  if (!iframeUrl) {
    console.error('Uso: node ws_sniffer.js "<URL_DO_IFRAME_DO_JOGO>"');
    process.exit(1);
  }

  console.log('[SNIFFER] Iniciando Puppeteer...');
  console.log('[SNIFFER] URL alvo:', iframeUrl);

  const browser = await puppeteer.launch({
    headless: false, // deixa visível pra você interagir
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
    ],
  });

  const page = await browser.newPage();
  await page.setUserAgent(
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
  );

  // Sessão CDP pra escutar eventos de rede (inclui WebSockets)
  const client = await page.target().createCDPSession();
  await client.send('Network.enable');

  // Mapeia requestId -> url do WebSocket
  const wsMap = new Map();

  // Quando um WebSocket é criado
  client.on('Network.webSocketCreated', (params) => {
    const { requestId, url } = params;
    wsMap.set(requestId, url);
    console.log('======================================================');
    console.log('[WS CREATED]', url);
    console.log('======================================================');
  });

  // Mensagens ENVIADAS (cliente -> servidor)
  client.on('Network.webSocketFrameSent', (params) => {
    const { requestId, response } = params;
    const url = wsMap.get(requestId) || 'UNKNOWN_WS';
    const payload = response.payloadData;

    // Foca no WS do GAME
    if (url.includes('/game')) {
      console.log('----------------- >>> FRAME ENVIADO (GAME) ----------');
      console.log('URL   :', url);
      console.log('OPCODE:', response.opcode);
      console.log('PAYLOAD:');
      console.log(payload);
      console.log('-----------------------------------------------------\n');
    }
  });

  // Mensagens RECEBIDAS (servidor -> cliente)
  client.on('Network.webSocketFrameReceived', (params) => {
    const { requestId, response } = params;
    const url = wsMap.get(requestId) || 'UNKNOWN_WS';
    const payload = response.payloadData;

    if (url.includes('/game')) {
      console.log('----------------- <<< FRAME RECEBIDO (GAME) ---------');
      console.log('URL   :', url);
      console.log('OPCODE:', response.opcode);
      console.log('PAYLOAD:');
      console.log(payload);
      console.log('-----------------------------------------------------\n');
    }
  });

  // Só pra você ver logs normais da página, se quiser
  page.on('console', (msg) => {
    console.log('[BROWSER]', msg.text());
  });

  // Navega para a URL da mesa / iframe
  await page.goto(iframeUrl, {
    waitUntil: 'networkidle2',
    timeout: 60000,
  });

  console.log('\n[SNIFFER] Página carregada.');
  console.log('[SNIFFER] Agora:');
  console.log('  1) Se precisar, faça login na página do jogo;');
  console.log('  2) Entre na mesa (se ainda não entrou automaticamente);');
  console.log('  3) Espere o jogo carregar;');
  console.log('  4) Quando aparecer apostas abertas, faça pelo menos UMA aposta manual;');
  console.log('  5) No terminal, observe:');
  console.log('       [WS CREATED] .../game?...');
  console.log('       >>> FRAME ENVIADO (GAME) ...');
  console.log('       <<< FRAME RECEBIDO (GAME) ...');
  console.log('  6) Quando terminar de analisar o handshake, use CTRL+C pra encerrar.\n');

  // Não fecha o browser automaticamente pra você acompanhar o fluxo.
}

main().catch((err) => {
  console.error('[SNIFFER] Erro geral:', err);
  process.exit(1);
});