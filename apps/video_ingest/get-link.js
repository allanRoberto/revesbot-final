// Gera um GAME_LINK fresco logando no Express (auth da casa) e chamando start-game.
// Uso: EXPRESS_URL=... EMAIL=... PASSWORD=... GAME_ID=373 node get-link.js
// Imprime só a URL no stdout (para usar em `GAME_LINK=$(npm run --silent get-link)`).

const EXPRESS_URL = process.env.EXPRESS_URL || 'https://auth.revesbot.com.br';
const EMAIL = process.env.EMAIL;
const PASSWORD = process.env.PASSWORD;
const GAME_ID = process.env.GAME_ID || '373';

async function main() {
  if (!EMAIL || !PASSWORD) throw new Error('Defina EMAIL e PASSWORD no ambiente.');

  const login = await fetch(`${EXPRESS_URL}/auth/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  const ld = await login.json();
  const token = ld.token || ld.access_token;
  if (!token) throw new Error('Login sem token: ' + JSON.stringify(ld).slice(0, 200));

  const sg = await fetch(`${EXPRESS_URL}/start-game/${GAME_ID}`, {
    headers: { cookie: `bookmaker_token=${token}` },
  });
  const sd = await sg.json();
  if (!sd.link) throw new Error('start-game sem link: ' + JSON.stringify(sd).slice(0, 200));

  process.stdout.write(sd.link);
}

main().catch((e) => {
  console.error('[get-link]', e.message);
  process.exit(1);
});
