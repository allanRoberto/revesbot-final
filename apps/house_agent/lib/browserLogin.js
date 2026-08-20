// Fluxo headless para casas da plataforma Nuxt/BFF (Esportiva, Bateu, …):
// abre o site (passa Cloudflare), faz login no modal (campos #login/#password,
// Turnstile invisível), e — navegando para a página do jogo — captura o
// start-game-v2 (gameURL) e o user-profile (saldo). Validado no spike.

const puppeteer = require('puppeteer-core');

const CHROME = process.env.CHROME_BIN || '/usr/bin/chromium';
const UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launch() {
  return puppeteer.launch({
    headless: false, // precisa render real (Cloudflare/Turnstile + vídeo)
    executablePath: CHROME,
    args: [
      '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
      '--use-gl=swiftshader', '--enable-unsafe-swiftshader',
      '--window-size=1360,900',
      // parece menos "automação" p/ Cloudflare/Turnstile
      '--disable-blink-features=AutomationControlled',
    ],
  });
}

async function doLogin(page, domain, email, password) {
  await page.goto(`https://${domain}`, { waitUntil: 'networkidle2', timeout: 60000 });
  await sleep(4000);

  // detecta bloqueio de Cloudflare (não deveria ocorrer no IP do servidor)
  const blocked = await page.evaluate(() => {
    const t = (document.title + ' ' + (document.body ? document.body.innerText.slice(0, 120) : '')).toLowerCase();
    return /just a moment|verifying you are human|attention required|enable javascript and cookies/.test(t);
  });
  if (blocked) throw new Error('Cloudflare bloqueou o acesso (challenge).');

  // abre o modal de login
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('button,a')].find((b) => /^entrar$/i.test((b.textContent || '').trim()));
    if (el) el.click();
  });
  await sleep(3000);

  // preenche credenciais (React/Vue: precisa disparar input/change)
  await page.evaluate((em, pw) => {
    const set = (el, v) => {
      if (!el) return;
      const d = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      d.call(el, v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    set(document.querySelector('#login'), em);
    set(document.querySelector('#password'), pw);
  }, email, password);
  await sleep(2000);

  // submete
  await page.evaluate(() => {
    const p = document.querySelector('#password');
    const f = p && p.closest('form');
    if (f && f.requestSubmit) { f.requestSubmit(); return; }
    [...document.querySelectorAll('button')]
      .filter((b) => /^entrar$/i.test((b.textContent || '').trim()) && !b.disabled)
      .slice(-1)
      .forEach((b) => b.click());
  });

  // espera a sessão (cookie jwt_token) por até ~18s
  for (let i = 0; i < 9; i++) {
    await sleep(2000);
    const cookies = await page.cookies();
    if (cookies.some((c) => c.name === 'jwt_token')) return true;
  }
  throw new Error('Falha no login (sessão não estabelecida — credenciais ou Turnstile).');
}

/**
 * Loga na casa e devolve { gameURL, balance } para o slug informado.
 * slug ex.: "pragmaticplay/roleta-brasileira".
 */
async function getGameLink({ domain, email, password, slug }) {
  const browser = await launch();
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1360, height: 900 });
    await page.setUserAgent(UA);

    await doLogin(page, domain, email, password);
    // deixa o BFF assentar (enriquecer o token jwt_token) após o login
    await sleep(5000);

    // Pega o token enriquecido do cookie e chama o start-game-v2 via fetch
    // IN-PAGE (com Bearer + tenant). Assim o link NÃO é consumido por este
    // navegador — fica fresco para o bet_ws abrir e capturar o WS.
    const cookies = await page.cookies();
    const jwt = (cookies.find((c) => c.name === 'jwt_token') || {}).value || '';
    if (!jwt) throw new Error('token jwt_token não encontrado após login.');

    const out = await page.evaluate(async (slugArg, token) => {
      const h = {
        accept: 'application/json',
        authorization: 'Bearer ' + token,
        tenant: location.hostname,
        'origin-domain': location.hostname,
        lang: 'pt-br',
        language: 'pt-br',
        country: 'BR',
        currency: 'BRL',
      };
      const rnd = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()));
      const qs = new URLSearchParams({ slug: slugArg, platform: 'WEB', use_demo: '0', source: 'watchIsAuthenticated', tab_id: rnd(), mounted_id: rnd() });
      const sg = await fetch('/api/start-game-v2?' + qs.toString(), { headers: h, credentials: 'include' }).then((r) => r.json()).catch(() => null);
      let balance = null;
      try { balance = (await fetch('/api/auth/user-profile', { headers: h, credentials: 'include' }).then((r) => r.json())).balance ?? null; } catch (e) { /* saldo é opcional */ }
      return { sg, balance };
    }, slug, jwt);

    const sg = out.sg || {};
    const gameURL = sg.gameURL || sg.url || sg.link || (sg.data && (sg.data.gameURL || sg.data.url));
    if (!gameURL) throw new Error('gameURL ausente: ' + JSON.stringify(sg).slice(0, 200));

    return { gameURL, balance: out.balance };
  } finally {
    await browser.close();
  }
}

module.exports = { getGameLink };
