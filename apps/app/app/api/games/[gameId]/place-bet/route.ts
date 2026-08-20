import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { findRoulette } from '@/lib/games';
import { isActive } from '@/lib/subscription';
import { placeBet } from '@/lib/betws';
import { automationOwnerKey } from '@/lib/automation';

// Aposta o slip completo no tabuleiro (números cheios; vizinhos já vêm
// expandidos). body: { sessionId, bets: { numero: valor } } — cada número com
// o valor acumulado; o lpbet substitui o slip anterior na mesa.
export async function POST(
  req: Request,
  { params }: { params: Promise<{ gameId: string }> },
) {
  const { gameId } = await params;
  if (!findRoulette(gameId)) {
    return NextResponse.json({ error: 'Jogo não disponível.' }, { status: 404 });
  }
  const session = await getSession();
  if (!session) return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  if (!(await isActive(session.email))) {
    return NextResponse.json({ error: 'Assinatura necessária.', paywall: true }, { status: 402 });
  }

  let body: { sessionId?: string; bets?: Record<string, number> };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Requisição inválida.' }, { status: 400 });
  }
  if (!body.sessionId) {
    return NextResponse.json({ error: 'sessionId é obrigatório.' }, { status: 400 });
  }

  // Valida e normaliza o slip: números 0–36, valores > 0 (limite de segurança
  // por número para evitar erro de digitação/estado corrompido).
  const bets: Record<number, number> = {};
  for (const [k, v] of Object.entries(body.bets || {})) {
    const n = Number(k);
    const value = Number(v);
    if (!Number.isInteger(n) || n < 0 || n > 36) continue;
    if (!Number.isFinite(value) || value <= 0 || value > 1000) {
      return NextResponse.json({ error: `Valor inválido para o número ${n}.` }, { status: 400 });
    }
    bets[n] = Math.round(value * 100) / 100;
  }
  if (Object.keys(bets).length === 0) {
    return NextResponse.json({ error: 'Nenhuma aposta válida.' }, { status: 400 });
  }

  try {
    const ownerKey = automationOwnerKey(session.email, session.house, gameId);
    const result = await placeBet(body.sessionId, bets, ownerKey);
    return NextResponse.json(result);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'Falha ao apostar.' },
      { status: 409 },
    );
  }
}
