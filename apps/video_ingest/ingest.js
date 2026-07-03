// PROTÓTIPO de ingest (v2 — captura MSE): abre a mesa no Chromium (headed sob xvfb)
// e intercepta o SourceBuffer.appendBuffer do player de vídeo (fMP4 H264+AAC).
// Os bytes já vêm codificados, então o ffmpeg só REMUXA para HLS (-c copy) — sem
// re-encodar (CPU ~zero). O init segment é capturado desde o 1º append via
// evaluateOnNewDocument (roda em todos os frames, inclusive o OOPIF do vídeo).
//
// Uso:  GAME_LINK="https://..." CHROME_BIN=/usr/bin/chromium npm run ingest
// Saída: hls/stream.m3u8   (ffplay hls/stream.m3u8, ou servir via nginx/hls.js)

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const puppeteer = require('puppeteer-core');
const { WebSocketServer } = require('ws');

const GAME_LINK = process.env.GAME_LINK;
const CHROME = process.env.CHROME_BIN || '/usr/bin/chromium';
const HLS_DIR = process.env.HLS_DIR || path.join(__dirname, 'hls');
const WS_PORT = Number(process.env.WS_PORT || 0);

if (!GAME_LINK) { console.error('Defina GAME_LINK.'); process.exit(1); }
fs.mkdirSync(HLS_DIR, { recursive: true });

// ---- Relay ao vivo (fMP4 via WebSocket) ----
// O ffmpeg emite no stdout um fMP4 contínuo (fragmentos de ~1s, cada um
// começando em keyframe). Guardamos o init (ftyp+moov) e retransmitimos cada
// moof+mdat para todos os navegadores conectados, que alimentam o MSE direto.
// Latência ~1-2s; o HLS continua sendo gerado como fallback (iOS / WS falhou).
let initSeg = null;
let initMime = null;
const clients = new Set();
if (WS_PORT) {
  const wss = new WebSocketServer({ port: WS_PORT });
  wss.on('connection', (c) => {
    clients.add(c);
    c.on('close', () => clients.delete(c));
    c.on('error', () => clients.delete(c));
    if (initSeg) {
      c.send(JSON.stringify({ type: 'init', mime: initMime }));
      c.send(initSeg);
    }
  });
  console.log('[relay] WS ouvindo na porta', WS_PORT);
}

function mimeFromInit(buf) {
  const hex = (n) => n.toString(16).padStart(2, '0');
  const i = buf.indexOf('avcC');
  const video = i >= 0 ? `avc1.${hex(buf[i + 5])}${hex(buf[i + 6])}${hex(buf[i + 7])}` : 'avc1.4d401f';
  const audio = buf.indexOf('mp4a') >= 0 ? ', mp4a.40.2' : '';
  return `video/mp4; codecs="${video}${audio}"`;
}

function broadcast(frag) {
  for (const c of clients) {
    if (c.readyState !== 1) continue;
    // Cliente que não drena o socket acumularia RAM aqui — derruba e ele reconecta.
    if (c.bufferedAmount > 3_000_000) { c.terminate(); clients.delete(c); continue; }
    c.send(frag);
  }
}

// Corta o stdout do ffmpeg em boxes MP4: init = tudo até o moov (inclusive);
// depois disso cada fragmento fecha quando chega o mdat.
let mp4Acc = Buffer.alloc(0);
let mp4Pending = [];
function onMp4Data(chunk) {
  mp4Acc = mp4Acc.length ? Buffer.concat([mp4Acc, chunk]) : chunk;
  while (mp4Acc.length >= 8) {
    const size = mp4Acc.readUInt32BE(0);
    if (size < 8) { console.log('[relay] box mp4 inválido — descartando buffer'); mp4Acc = Buffer.alloc(0); mp4Pending = []; return; }
    if (mp4Acc.length < size) break;
    const type = mp4Acc.toString('ascii', 4, 8);
    mp4Pending.push(mp4Acc.subarray(0, size));
    mp4Acc = mp4Acc.subarray(size);
    if (type === 'moov') {
      initSeg = Buffer.concat(mp4Pending);
      mp4Pending = [];
      initMime = mimeFromInit(initSeg);
      console.log('[relay] init pronto:', initSeg.length, 'bytes,', initMime);
      for (const c of clients) {
        if (c.readyState !== 1) continue;
        c.send(JSON.stringify({ type: 'init', mime: initMime }));
        c.send(initSeg);
      }
    } else if (type === 'mdat') {
      broadcast(Buffer.concat(mp4Pending));
      mp4Pending = [];
    }
  }
}

let ffmpeg = null;
let bytes = 0;
// DIAGNÓSTICO: grava o stream cru capturado para inspecionar se a captura é válida.
const rawOut = process.env.RAW_OUT ? fs.createWriteStream(process.env.RAW_OUT) : null;
function feed(buf) {
  if (rawOut) rawOut.write(buf);
  if (!ffmpeg) startFfmpeg();
  bytes += buf.length;
  if (ffmpeg && ffmpeg.stdin.writable) ffmpeg.stdin.write(buf);
}
function startFfmpeg() {
  const out = path.join(HLS_DIR, 'stream.m3u8');
  // Re-encoda em resolução FIXA: o player faz ABR (270p/540p/1080p) e um -c copy
  // não aguenta a troca de resolução no meio. Escalar p/ altura fixa normaliza tudo.
  const height = process.env.OUT_HEIGHT || '480';
  ffmpeg = spawn('ffmpeg', [
    '-hide_banner', '-loglevel', 'warning',
    '-fflags', '+discardcorrupt', '-err_detect', 'ignore_err',
    '-i', 'pipe:0',
    '-vf', `scale=-2:${height},format=yuv420p`,
    '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency', '-profile:v', 'main',
    // Keyframe a cada 1s: segmentos HLS de 1s e fragmentos do relay que sempre
    // começam em keyframe (quem conecta no WS espera no máximo ~1s p/ decodar).
    '-force_key_frames', 'expr:gte(t,n_forced)',
    // global_header: extradata no encoder → o mp4 escreve o avcC de verdade
    // (sem isso o MSE rejeita). O dump_extra devolve SPS/PPS inline nos .ts.
    '-flags', '+global_header',
    '-c:a', 'aac', '-ar', '44100', '-b:a', '128k',
    '-map', '0:v', '-map', '0:a?',
    // tee: um encode só, duas saídas — HLS em disco (fallback) + fMP4 no stdout (relay WS).
    '-f', 'tee',
    `[f=hls:hls_time=1:hls_list_size=8:hls_flags=delete_segments+append_list+omit_endlist:bsfs/v=dump_extra=freq=keyframe]${out}|[f=mp4:movflags=+frag_keyframe+empty_moov+default_base_moof]pipe:1`,
  ], { stdio: ['pipe', 'pipe', 'inherit'] });
  ffmpeg.stdout.on('data', onMp4Data);
  ffmpeg.on('exit', (c) => console.log('[ffmpeg] saiu code=', c));
  console.log('[ffmpeg] re-encodando -> HLS', height + 'p em', out, WS_PORT ? `+ relay WS :${WS_PORT}` : '');
}

(async () => {
  const browser = await puppeteer.launch({
    headless: false,
    executablePath: CHROME,
    args: [
      '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
      '--autoplay-policy=no-user-gesture-required',
      '--use-gl=swiftshader', '--enable-unsafe-swiftshader',
      '--window-size=1280,720',
      // Sem site-isolation: o frame do vídeo fica no mesmo processo, então o
      // throttle de rede (CDP) alcança ele e trava o ABR na menor qualidade.
      '--disable-site-isolation-trials',
      '--disable-features=IsolateOrigins,site-per-process,CalculateNativeWinOcclusion',
      // Impede o Chrome de pausar/throttlar a página em "background" (sob xvfb
      // ela é considerada hidden e o player pausa o vídeo depois de ~1min).
      '--disable-background-timer-throttling',
      '--disable-backgrounding-occluded-windows',
      '--disable-renderer-backgrounding',
    ],
  });
  // Encerramento limpo (systemd SIGTERM) e saída se o browser cair/congelar.
  function shutdown(code) {
    try { if (ffmpeg) ffmpeg.kill('SIGKILL'); } catch (_) {}
    try { browser.close(); } catch (_) {}
    process.exit(code || 0);
  }
  process.on('SIGTERM', () => shutdown(0));
  process.on('SIGINT', () => shutdown(0));
  browser.on('disconnected', () => { console.log('[browser] desconectou'); process.exit(1); });

  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });

  // Limita a banda para o player fixar a MENOR resolução (evita troca de
  // resolução do ABR, que corrompe o decode). Ajuste via NET_KBPS.
  const kbps = Number(process.env.NET_KBPS || 900);
  const bps = (kbps * 1024) / 8; // bytes/s
  await page.emulateNetworkConditions({
    offline: false,
    download: bps,
    upload: bps,
    latency: 20,
  });

  // Recebe cada segmento fMP4 (base64) e alimenta o ffmpeg, em ordem.
  await page.exposeFunction('pushSeg', (b64) => feed(Buffer.from(b64, 'base64')));

  // Mantém a página sempre "visível/focada" (sob xvfb ela é hidden e o player pausa).
  await page.evaluateOnNewDocument(() => {
    Object.defineProperty(document, 'hidden', { get: () => false, configurable: true });
    Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
    Object.defineProperty(document, 'webkitHidden', { get: () => false, configurable: true });
    try { document.hasFocus = () => true; } catch (_) {}
    window.addEventListener('visibilitychange', (e) => e.stopImmediatePropagation(), true);
  });

  // Hook do MSE, instalado ANTES de qualquer script do player (em todos os frames).
  await page.evaluateOnNewDocument(() => {
    if (!window.MediaSource) return;
    const _add = MediaSource.prototype.addSourceBuffer;
    let captured = false; // captura só o 1º SourceBuffer (é muxado: vídeo+áudio)
    MediaSource.prototype.addSourceBuffer = function (mime) {
      const sb = _add.call(this, mime);
      if (!captured && /mp4/i.test(mime)) {
        captured = true;
        const _ap = sb.appendBuffer.bind(sb);
        sb.appendBuffer = function (d) {
          try {
            const u = d instanceof ArrayBuffer
              ? new Uint8Array(d)
              : new Uint8Array(d.buffer, d.byteOffset, d.byteLength);
            let s = '';
            const CH = 0x8000;
            for (let i = 0; i < u.length; i += CH) s += String.fromCharCode.apply(null, u.subarray(i, i + CH));
            window.pushSeg(btoa(s));
          } catch (e) { /* ignora */ }
          return _ap(d);
        };
      }
      return sb;
    };
  });

  console.log('[browser] abrindo mesa...');
  await page.goto(GAME_LINK, { waitUntil: 'networkidle2', timeout: 60000 })
    .catch((e) => console.log('[browser] goto warn', e.message));

  console.log('[ingest] aguardando segmentos do player...');
  let last = 0;
  let stalls = 0;
  setInterval(() => {
    const kb = (bytes / 1024).toFixed(0);
    const stalled = bytes === last;
    console.log('[ingest] recebidos', kb, 'KB', stalled ? '(sem novos!)' : '');
    // Watchdog: se já recebeu algo e travou por ~30s, sai p/ o systemd reiniciar.
    if (bytes > 0 && stalled) {
      if (++stalls >= 6) { console.log('[ingest] congelou — reiniciando'); shutdown(1); }
    } else {
      stalls = 0;
    }
    last = bytes;
  }, 5000);

  // Poster borrado da mesa: 1 frame do HLS a cada 8s → poster.jpg. O player usa
  // como fallback quando o vídeo trava/cai (nada de tela preta) e a UI usa como
  // fundo enquanto conecta na mesa. Só gera quando já há stream.
  const posterPath = path.join(HLS_DIR, 'poster.jpg');
  const m3u8Path = path.join(HLS_DIR, 'stream.m3u8');
  setInterval(() => {
    if (bytes <= 0 || !fs.existsSync(m3u8Path)) return;
    const p = spawn('ffmpeg', [
      '-y', '-loglevel', 'error',
      '-i', m3u8Path,
      '-frames:v', '1',
      '-vf', 'scale=720:-1,gblur=sigma=20',
      '-q:v', '6',
      posterPath,
    ], { stdio: 'ignore' });
    const kt = setTimeout(() => { try { p.kill('SIGKILL'); } catch (_) {} }, 9000);
    p.on('exit', () => clearTimeout(kt));
    p.on('error', () => clearTimeout(kt));
  }, 8000);
})();
