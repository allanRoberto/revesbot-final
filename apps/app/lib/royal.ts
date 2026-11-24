import 'server-only';

import type { House } from './houses';
import type { BookmakerLoginResult, BookmakerUser, StartGameResult } from './bookmaker';

// Cliente da plataforma Royal Bets Solutions (SorteAgora). A API fica num host
// próprio (`house.apiBase`) e aceita chamadas servidor-a-servidor, sem navegador:
//   POST /auth/login     { login, password }        -> { access_token, two_factor_required }
//   GET  /users/me       Bearer                     -> { wallet: [{ currency, balance }], ... }
//   POST /game/get-game  Bearer { provider, game }  -> { url, details }
// O saldo vem em CENTAVOS na carteira 'BRL' (o site da casa divide por 100 para
// exibir). Erros vêm como { id, message }, ex.: INVALID_LOGIN.
// Nada aqui registra senha, token ou link de jogo em log.

const USER_AGENT =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36';
const TIMEOUT_MS = 15_000;

// Os mesmos códigos que o site da casa trata na tela de login.
const ERROR_MESSAGES: Record<string, string> = {
  INVALID_LOGIN: 'E-mail ou senha inválidos.',
  LOGIN_IP_BLOCKED: 'A casa bloqueou temporariamente o login deste endereço de IP.',
  LOGIN_IP_BLOCKED_HOUR:
    'Muitas tentativas de login. A casa bloqueou este endereço de IP por até 1 hora.',
  VPN_PROXY_NOT_ALLOWED:
    'A casa recusou o login porque não aceita conexões por VPN ou proxy.',
  TWO_FACTOR_AUTH_REQUIRED:
    'Esta conta usa verificação em duas etapas. Desative-a no painel da casa para o app conseguir entrar.',
  INVALID_TWO_FACTOR_TOKEN: 'Código de verificação em duas etapas inválido.',
  TWO_FACTOR_BLOCKED: 'A verificação em duas etapas desta conta está bloqueada na casa.',
  USER_BANNED: 'A casa suspendeu esta conta.',
};

interface RoyalResponse {
  ok: boolean;
  status: number;
  data: Record<string, unknown> | null;
}

async function call(
  house: House,
  path: string,
  options: { method: 'GET' | 'POST'; token?: string; body?: unknown },
): Promise<RoyalResponse> {
  if (!house.apiBase) throw new Error(`Casa ${house.id} sem apiBase configurada.`);

  const headers: Record<string, string> = {
    accept: 'application/json',
    origin: `https://${house.domain}`,
    referer: `https://${house.domain}/`,
    'user-agent': USER_AGENT,
  };
  if (options.body !== undefined) headers['content-type'] = 'application/json';
  if (options.token) headers.authorization = `Bearer ${options.token}`;

  const res = await fetch(`${house.apiBase}${path}`, {
    method: options.method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    cache: 'no-store',
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });

  let data: Record<string, unknown> | null = null;
  try {
    const parsed: unknown = await res.json();
    if (parsed && typeof parsed === 'object') data = parsed as Record<string, unknown>;
  } catch {
    /* resposta sem corpo JSON */
  }
  return { ok: res.ok, status: res.status, data };
}

function errorMessage(data: RoyalResponse['data'], fallback: string): string {
  const id = typeof data?.id === 'string' ? data.id : '';
  return ERROR_MESSAGES[id] ?? fallback;
}

// Erro da casa repassado ao navegador: 5xx vira 503 (falha do outro lado).
// Não usar 502: o Cloudflare troca a resposta 502 pela página de erro dele.
function upstreamStatus(status: number): number {
  return status >= 500 ? 503 : status || 503;
}

export async function royalLogin(
  house: House,
  email: string,
  password: string,
): Promise<BookmakerLoginResult> {
  let res: RoyalResponse;
  try {
    res = await call(house, '/auth/login', {
      method: 'POST',
      body: { login: email, password },
    });
  } catch {
    return { ok: false, status: 503, error: `Não foi possível contatar a ${house.name}.` };
  }

  if (!res.ok) {
    return {
      ok: false,
      status: upstreamStatus(res.status),
      error: errorMessage(res.data, 'E-mail ou senha inválidos.'),
    };
  }
  // O site da casa também para aqui: sem o código, o acesso não é liberado.
  if (res.data?.two_factor_required === true) {
    return { ok: false, status: 401, error: ERROR_MESSAGES.TWO_FACTOR_AUTH_REQUIRED };
  }
  const token = typeof res.data?.access_token === 'string' ? res.data.access_token : '';
  if (!token) {
    return {
      ok: false,
      status: 503,
      error: `A ${house.name} não devolveu o acesso. Tente novamente.`,
    };
  }
  return { ok: true, status: 200, token };
}

export async function royalUser(house: House, token: string): Promise<BookmakerUser | null> {
  try {
    const res = await call(house, '/users/me', { method: 'GET', token });
    if (!res.ok || !res.data || res.data.banned_at) return null;

    const wallets = (Array.isArray(res.data.wallet) ? res.data.wallet : []) as Array<{
      currency?: unknown;
      balance?: unknown;
    } | null>;
    const brl = wallets.find((wallet) => wallet?.currency === 'BRL');
    const cents = Number(brl?.balance);

    return {
      name: typeof res.data.name === 'string' ? res.data.name : undefined,
      email: typeof res.data.email === 'string' ? res.data.email : undefined,
      balance: brl && Number.isFinite(cents) ? Math.round(cents) : undefined,
    };
  } catch {
    return null;
  }
}

/** `slug` no formato '<provedor>/<jogo>', ex.: 'pragmatic-live/brazilian-roulette'. */
export async function royalStartGame(
  house: House,
  token: string,
  slug: string,
): Promise<StartGameResult> {
  const [provider, game] = slug.split('/');
  if (!provider || !game) {
    return { ok: false, status: 500, error: 'Jogo configurado de forma errada no app.' };
  }

  let res: RoyalResponse;
  try {
    res = await call(house, '/game/get-game', {
      method: 'POST',
      token,
      body: { provider, game },
    });
  } catch {
    return { ok: false, status: 503, error: `Não foi possível contatar a ${house.name}.` };
  }

  const url = typeof res.data?.url === 'string' ? res.data.url : '';
  if (res.ok && url) return { ok: true, status: 200, link: url };

  // Sem link = a casa não reconheceu o acesso (token vencido) ou travou o jogo
  // nesta conta. Sem token, a API responde 201 com url null.
  if (res.ok || res.status === 401 || res.status === 403) {
    return {
      ok: false,
      status: 401,
      error: `A ${house.name} não liberou o jogo. Faça login novamente; se continuar, confira sua conta no site da casa.`,
    };
  }
  return {
    ok: false,
    status: upstreamStatus(res.status),
    error: errorMessage(res.data, 'Não foi possível abrir o jogo.'),
  };
}
