import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { getRecentNumbers } from '@/lib/mongo';
import { findRoulette } from '@/lib/games';
import { topSuggestion } from '@/lib/suggestion';

// Sugestão ATUAL (8 números) + os 3 últimos números da mesa (base/momento).
// Algoritmo roda no servidor; só os números finais vão pro cliente.
export async function GET(
  _req: Request,
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

  const numbers = await getRecentNumbers(game.rouletteId, 200);
  const suggestion = topSuggestion(numbers, 8);

  return NextResponse.json({
    numbers: suggestion.map((s) => s.num),
    // 3 últimos números da mesa (mais recente primeiro) — base da análise.
    last: numbers.slice(0, 3),
    sampleSize: numbers.length,
  });
}
