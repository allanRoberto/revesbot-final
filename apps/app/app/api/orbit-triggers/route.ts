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

export async function GET(request: Request) {
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

  const strategySlug = new URL(request.url).searchParams.get('slug')?.trim();
  const rouletteIds = ROULETTES.map((game) => game.rouletteId);
  const path = strategySlug
    ? `/api/orbit-triggers/${encodeURIComponent(strategySlug)}`
    : '/api/orbit-triggers/catalog';
  const url = new URL(path, orbitApiBase());
  url.searchParams.set('roulette_ids', rouletteIds.join(','));
  if (strategySlug) url.searchParams.set('history_limit', '20');

  try {
    const response = await fetch(url, {
      cache: 'no-store',
      signal: AbortSignal.timeout(20_000),
    });
    const payload = await response.json();
    if (!response.ok) {
      return NextResponse.json(
        { error: payload?.detail ?? 'Monitor de gatilhos indisponível.' },
        { status: response.status },
      );
    }
    if (!strategySlug) return NextResponse.json(payload);

    const names = new Map(ROULETTES.map((game) => [game.rouletteId, game.name]));
    return NextResponse.json({
      ...payload,
      roulettes: Array.isArray(payload.roulettes)
        ? payload.roulettes.map((row: { roulette_id?: string }) => ({
            ...row,
            name: names.get(row.roulette_id ?? '') ?? row.roulette_id ?? 'Roleta',
          }))
        : [],
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Falha de conexão.';
    return NextResponse.json(
      { error: `Não foi possível consultar os gatilhos: ${message}` },
      { status: 502 },
    );
  }
}
