import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { getRecentNumbers } from '@/lib/mongo';
import { findRoulette } from '@/lib/games';
import { ensembleSuggestion } from '@/lib/suggestion';
import { isActive } from '@/lib/subscription';

// Sugestão por ENSEMBLE (9 números): combina a sugestão de 8 das janelas
// 50/100/200/300/360, pontuando cada número e seus vizinhos de roda, e pega o
// top 9. + os 3 últimos números da mesa (base). Algoritmo roda só no servidor.
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

  // Sugestão é exclusiva de assinantes com plano ativo.
  if (!(await isActive(session.email))) {
    return NextResponse.json(
      { error: 'Assinatura necessária.', paywall: true },
      { status: 402 },
    );
  }

  const numbers = await getRecentNumbers(game.rouletteId, 360);
  const suggestion = ensembleSuggestion(numbers, undefined, 9);

  return NextResponse.json({
    numbers: suggestion.map((s) => s.num),
    // 3 últimos números da mesa (mais recente primeiro) — base da análise.
    last: numbers.slice(0, 3),
    sampleSize: numbers.length,
  });
}
