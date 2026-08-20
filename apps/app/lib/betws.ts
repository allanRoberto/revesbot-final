import 'server-only';

// Cliente do serviço bet_ws (captura o WS da mesa e envia apostas).
// Roda só no servidor: o token compartilhado nunca vai ao browser.

const BET_WS_URL = process.env.BET_WS_URL || 'http://127.0.0.1:4060';
const BET_WS_TOKEN = process.env.BET_WS_TOKEN || '';

function headers(ownerKey?: string): Record<string, string> {
  const h: Record<string, string> = { 'content-type': 'application/json' };
  if (BET_WS_TOKEN) h['X-Bet-Token'] = BET_WS_TOKEN;
  if (ownerKey) h['X-Bet-Owner'] = ownerKey;
  return h;
}

export interface TableState {
  sessionId: string;
  connected: boolean;
  betsOpen: boolean;
  gameInfo: { game: string; table: string } | null;
  lastResult: number | null;
  rouletteId: string | null;
  automation?: {
    runId: string;
    status: 'running' | 'stopping' | 'stopped' | 'error';
    netProfitCents: number;
    targetProfitCents: number;
    maxLossCents: number;
    roundsSettled: number;
    pendingRoundId: string | null;
  } | null;
}

/** Cria uma sessão de mesa a partir do link jogável (iframe) já resolvido. */
export async function createBetSession(
  gameLink: string,
  rouletteId: string,
  clientKey?: string,
): Promise<TableState> {
  const res = await fetch(`${BET_WS_URL}/session`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ gameLink, rouletteId, clientKey }),
    cache: 'no-store',
  });
  if (!res.ok) {
    const msg = await safeError(res);
    throw new Error(msg);
  }
  return res.json();
}

/** Estado atual da mesa (apostas abertas, último número, etc.). */
export async function getBetSessionState(
  sessionId: string,
  ownerKey: string,
): Promise<TableState | null> {
  const res = await fetch(`${BET_WS_URL}/session/${sessionId}/state`, {
    headers: headers(ownerKey),
    cache: 'no-store',
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await safeError(res));
  return res.json();
}

export interface BetResult {
  ok: boolean;
  bets: Record<string, number>;
  gameInfo: { game: string; table: string } | null;
  state: TableState;
}

/**
 * Envia a aposta real na sessão informada.
 * bets: { numero: valor } — o slip COMPLETO (o lpbet substitui o anterior),
 * com o valor acumulado de cada número.
 */
export async function placeBet(
  sessionId: string,
  bets: Record<number, number>,
  ownerKey: string,
): Promise<BetResult> {
  const res = await fetch(`${BET_WS_URL}/session/${sessionId}/bet`, {
    method: 'POST',
    headers: headers(ownerKey),
    body: JSON.stringify({ bets }),
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(await safeError(res));
  return res.json();
}

/** Abre o stream SSE de eventos da mesa (para o app repassar ao browser). */
export async function openSessionEvents(
  sessionId: string,
  ownerKey: string,
): Promise<Response> {
  return fetch(`${BET_WS_URL}/session/${sessionId}/events`, {
    headers: headers(ownerKey),
    cache: 'no-store',
  });
}

export interface AutomationStartConfig {
  runId: string;
  gameId: string;
  targetProfitCents: number;
  maxLossCents: number;
  chipValueCents: number;
}

export async function startBetAutomation(
  sessionId: string,
  ownerKey: string,
  config: AutomationStartConfig,
): Promise<TableState> {
  const res = await fetch(`${BET_WS_URL}/session/${sessionId}/automation/start`, {
    method: 'POST',
    headers: headers(ownerKey),
    body: JSON.stringify(config),
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(await safeError(res));
  const body = await res.json();
  return body.state;
}

export async function stopBetAutomation(
  sessionId: string,
  ownerKey: string,
): Promise<TableState> {
  const res = await fetch(`${BET_WS_URL}/session/${sessionId}/automation/stop`, {
    method: 'POST',
    headers: headers(ownerKey),
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(await safeError(res));
  const body = await res.json();
  return body.state;
}

async function safeError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    return data.error || data.message || `bet_ws respondeu ${res.status}`;
  } catch {
    return `bet_ws respondeu ${res.status}`;
  }
}
