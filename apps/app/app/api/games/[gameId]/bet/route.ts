import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { getRecentNumbers } from '@/lib/mongo';
import { findRoulette } from '@/lib/games';
import { ensembleSuggestion } from '@/lib/suggestion';
import { isActive } from '@/lib/subscription';
import { placeBet } from '@/lib/betws';

// Marca (aposta) os números sugeridos na mesa.
// A sugestão é RECALCULADA no servidor — não confiamos em números do cliente.
// body: { sessionId: string, chipValue?: number }
export async function POST(
  req: Request,
  { params }: { params: Promise<{ gameId: string }> },
) {
  const { gameId } = await params;

  const game = findRoulette(gameId);
  if (!game) {
    return NextResponse.json({ error: 'Jogo não disponível.' }, { status: 404 });
  }

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

  let body: { sessionId?: string; chipValue?: number };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Requisição inválida.' }, { status: 400 });
  }
  if (!body.sessionId) {
    return NextResponse.json({ error: 'sessionId é obrigatório.' }, { status: 400 });
  }

  const recent = await getRecentNumbers(game.rouletteId, 360);
  const suggestion = ensembleSuggestion(recent, undefined, 9).map((s) => s.num);
  if (suggestion.length === 0) {
    return NextResponse.json(
      { error: 'Sem dados suficientes para sugerir números.' },
      { status: 409 },
    );
  }

  try {
    const result = await placeBet(body.sessionId, suggestion, body.chipValue);
    return NextResponse.json(result);
  } catch (err) {
    // bet_ws devolve mensagens de negócio (apostas fechadas, sessão inexistente…).
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'Falha ao marcar os números.' },
      { status: 409 },
    );
  }
}
