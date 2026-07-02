import 'server-only';

// Cliente do house-agent (login headless para casas Nuxt/BFF: Esportiva, Bateu).
// Roda só no servidor; a senha do usuário nunca vai ao browser.

const HOUSE_AGENT_URL = process.env.HOUSE_AGENT_URL || 'http://127.0.0.1:4080';
const HOUSE_AGENT_TOKEN = process.env.HOUSE_AGENT_TOKEN || '';

export interface GameLinkResult {
  gameURL: string;
  balance: number | null;
}

/** Loga na casa (headless) e devolve o link jogável (playGame.do) + saldo. */
export async function getHouseGameLink(
  house: string,
  email: string,
  password: string,
  slug: string,
): Promise<GameLinkResult> {
  const headers: Record<string, string> = { 'content-type': 'application/json' };
  if (HOUSE_AGENT_TOKEN) headers['X-Agent-Token'] = HOUSE_AGENT_TOKEN;

  const res = await fetch(`${HOUSE_AGENT_URL}/game-link`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ house, email, password, slug }),
    cache: 'no-store',
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.gameURL) {
    throw new Error(data.error || `house-agent respondeu ${res.status}`);
  }
  return { gameURL: data.gameURL, balance: data.balance ?? null };
}
