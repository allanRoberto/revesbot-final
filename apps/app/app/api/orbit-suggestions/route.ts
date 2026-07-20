import { NextResponse } from 'next/server';
import { ROULETTES } from '@/lib/games';
import { getSession } from '@/lib/session';
import { isActive } from '@/lib/subscription';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

function orbitApiBase(): string {
  const configured = process.env.ORBIT_API_URL?.replace(/\/$/, '');
  if (configured) return configured;
  const port = process.env.DEPLOY_STAGE === 'main' ? '8080' : '8081';
  return `http://127.0.0.1:${port}`;
}

export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  }
  if (!(await isActive(session.email))) {
    return NextResponse.json(
      { error: 'Assinatura necessária.', paywall: true },
      { status: 402 },
    );
  }

  const rouletteIds = ROULETTES.map((game) => game.rouletteId);
  const url = new URL('/api/orbit/suggestions', orbitApiBase());
  url.searchParams.set('roulette_ids', rouletteIds.join(','));
  url.searchParams.set('pivot_count', '3');
  url.searchParams.set('memory_occurrences', '6');
  url.searchParams.set('history_limit', '600');
  url.searchParams.set('horizon', '3');
  const performanceUrl = new URL('/api/orbit/performance', orbitApiBase());
  performanceUrl.searchParams.set('roulette_ids', rouletteIds.join(','));
  performanceUrl.searchParams.set('max_attempts', '10');
  const historyUrl = new URL('/api/orbit/history', orbitApiBase());
  historyUrl.searchParams.set('roulette_ids', rouletteIds.join(','));
  historyUrl.searchParams.set('limit', '20');

  try {
    const [response, performanceResponse, historyResponse] = await Promise.all([
      fetch(url, {
        cache: 'no-store',
        signal: AbortSignal.timeout(20_000),
      }),
      fetch(performanceUrl, {
        cache: 'no-store',
        signal: AbortSignal.timeout(20_000),
      }),
      fetch(historyUrl, {
        cache: 'no-store',
        signal: AbortSignal.timeout(20_000),
      }),
    ]);
    const payload = await response.json();
    if (!response.ok) {
      return NextResponse.json(
        { error: payload?.detail ?? 'Motor orbital indisponível.' },
        { status: response.status },
      );
    }
    const performancePayload = performanceResponse.ok
      ? await performanceResponse.json()
      : { roulettes: [] };
    const performanceByRoulette = new Map(
      Array.isArray(performancePayload.roulettes)
        ? performancePayload.roulettes.map(
            (row: { roulette_id?: string }) => [row.roulette_id ?? '', row],
          )
        : [],
    );
    const historyPayload = historyResponse.ok
      ? await historyResponse.json()
      : { roulettes: [] };
    const historyByRoulette = new Map(
      Array.isArray(historyPayload.roulettes)
        ? historyPayload.roulettes.map(
            (row: { roulette_id?: string; items?: unknown[] }) => [
              row.roulette_id ?? '',
              row.items ?? [],
            ],
          )
        : [],
    );
    const names = new Map(ROULETTES.map((game) => [game.rouletteId, game.name]));
    const roulettes = Array.isArray(payload.roulettes)
      ? payload.roulettes.map((row: { roulette_id?: string }) => ({
          ...row,
          name: names.get(row.roulette_id ?? '') ?? row.roulette_id ?? 'Roleta',
          performance: performanceByRoulette.get(row.roulette_id ?? '') ?? null,
          history: historyByRoulette.get(row.roulette_id ?? '') ?? [],
        }))
      : [];
    return NextResponse.json({
      ...payload,
      roulettes,
      generated_at: new Date().toISOString(),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Falha de conexão.';
    return NextResponse.json(
      { error: `Não foi possível consultar o motor orbital: ${message}` },
      { status: 502 },
    );
  }
}
