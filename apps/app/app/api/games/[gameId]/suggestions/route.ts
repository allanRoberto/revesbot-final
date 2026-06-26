import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { getRecentNumbers } from '@/lib/mongo';
import { findRoulette } from '@/lib/games';
import { topSuggestion } from '@/lib/suggestion';

// Sugestões ao longo do tempo: a ATUAL + as ANTERIORES.
// Cada item = { prev3 (momento), suggestion (8 números), result, spinsToHit }.
// "spinsToHit" = em quantos giros após o momento um dos 8 saiu (para decidir
// travar numa sugestão e esperar bater). Tudo calculado no servidor.
export async function GET(
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

  const url = new URL(req.url);
  const count = Math.min(Math.max(Number(url.searchParams.get('count')) || 15, 1), 30);

  // numbers: mais recente primeiro. numbers[0] = último giro.
  const numbers = await getRecentNumbers(game.rouletteId, 200 + count);

  const items: {
    prev3: number[];
    suggestion: number[];
    result: number | null;
    spinsToHit: number | null;
    hitNumber: number | null;
    pending: boolean;
  }[] = [];

  for (let k = 0; k <= count; k++) {
    const base = numbers.slice(k); // números conhecidos no momento k (k mais recentes ocultos)
    const suggestion = topSuggestion(base, 8).map((s) => s.num);
    if (!suggestion.length) break;

    // Giros que ocorreram DEPOIS do momento k: numbers[k-1], numbers[k-2], ... numbers[0]
    let spinsToHit: number | null = null;
    let hitNumber: number | null = null;
    for (let d = 1; d <= k; d++) {
      if (suggestion.includes(numbers[k - d])) {
        spinsToHit = d;
        hitNumber = numbers[k - d];
        break;
      }
    }

    items.push({
      prev3: numbers.slice(k, k + 3), // 3 números do momento (mais recente primeiro)
      suggestion,
      result: k > 0 ? numbers[k - 1] : null, // o giro imediatamente seguinte
      spinsToHit,
      hitNumber,
      pending: k === 0, // a sugestão atual ainda não teve giro seguinte
    });
  }

  return NextResponse.json({ items });
}
