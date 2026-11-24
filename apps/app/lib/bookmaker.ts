// Camada de comunicação com as casas de apostas: login, saldo e link do jogo.
// Casas 'royal' (SorteAgora) falam direto com a API da casa (lib/royal.ts); as
// demais passam pelo Express (auth_api), que conhece a plataforma da LotoGreen.
// Tudo aqui roda server-side; o token da casa nunca é exposto ao browser.

import { findHouse } from './houses';
import { findRoulette, gameSlug } from './games';
import { royalLogin, royalStartGame, royalUser } from './royal';

const EXPRESS_URL = process.env.EXPRESS_URL || 'http://localhost:3090';

export interface BookmakerLoginResult {
  ok: boolean;
  token?: string;
  /** Mensagem de erro vinda da casa de apostas (ou genérica). */
  error?: string;
  status: number;
}

/**
 * Valida email/senha na casa escolhida. No caminho do Express, lemos o token
 * do CORPO da resposta (não do cookie httpOnly do Express, que não chega até
 * aqui numa chamada server-to-server).
 */
export async function loginBookmaker(
  email: string,
  password: string,
  house: string,
): Promise<BookmakerLoginResult> {
  const info = findHouse(house);
  if (info?.integration === 'royal') return royalLogin(info, email, password);

  let res: Response;
  try {
    res = await fetch(`${EXPRESS_URL}/auth/login`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-house': house },
      body: JSON.stringify({ email, password }),
      cache: 'no-store',
    });
  } catch {
    return {
      ok: false,
      status: 502,
      error: 'Não foi possível contatar o servidor de autenticação.',
    };
  }

  let data: { token?: string; isConnected?: boolean; error?: unknown } = {};
  try {
    data = await res.json();
  } catch {
    /* resposta sem corpo JSON */
  }

  if (!res.ok || !data.token) {
    const error =
      typeof data.error === 'string'
        ? data.error
        : 'E-mail ou senha inválidos.';
    return { ok: false, status: res.status || 401, error };
  }

  return { ok: true, status: 200, token: data.token };
}

export interface BookmakerUser {
  name?: string;
  email?: string;
  /** Saldo em centavos (dinheiro real; bônus fica de fora). */
  balance?: number;
}

/** Busca os dados do usuário (inclui saldo) na casa da sessão. */
export async function getBookmakerUser(
  bookmakerToken: string,
  house: string,
): Promise<BookmakerUser | null> {
  const info = findHouse(house);
  if (info?.integration === 'royal') return royalUser(info, bookmakerToken);

  try {
    const res = await fetch(`${EXPRESS_URL}/auth/user`, {
      method: 'GET',
      headers: { cookie: `bookmaker_token=${bookmakerToken}`, 'x-house': house },
      cache: 'no-store',
    });
    if (!res.ok) return null;
    const data = await res.json();
    return { name: data?.name, email: data?.email, balance: data?.balance };
  } catch {
    return null;
  }
}

export interface StartGameResult {
  ok: boolean;
  link?: string;
  error?: string;
  status: number;
}

/**
 * Inicia um jogo na casa e devolve o link jogável.
 * No caminho do Express, ele lê o token do cookie `bookmaker_token`; como a
 * chamada é server-to-server, injetamos o token (vindo do Mongo) nesse cookie.
 */
export async function startGame(
  gameId: string,
  bookmakerToken: string,
  house: string,
): Promise<StartGameResult> {
  const info = findHouse(house);
  if (info?.integration === 'royal') {
    const game = findRoulette(gameId);
    const slug = game ? gameSlug(game, info.id) : undefined;
    if (!slug) {
      return { ok: false, status: 404, error: `Este jogo não está disponível na ${info.name}.` };
    }
    return royalStartGame(info, bookmakerToken, slug);
  }

  let res: Response;
  try {
    res = await fetch(`${EXPRESS_URL}/start-game/${gameId}`, {
      method: 'GET',
      headers: { cookie: `bookmaker_token=${bookmakerToken}`, 'x-house': house },
      cache: 'no-store',
    });
  } catch {
    return {
      ok: false,
      status: 502,
      error: 'Não foi possível contatar o servidor de jogos.',
    };
  }

  let data: { success?: boolean; link?: string; message?: string } = {};
  try {
    data = await res.json();
  } catch {
    /* sem corpo JSON */
  }

  if (!res.ok || !data.link) {
    return {
      ok: false,
      status: res.status || 500,
      error: data.message || 'Não foi possível abrir o jogo.',
    };
  }

  return { ok: true, status: 200, link: data.link };
}
