import { NextResponse } from 'next/server';
import { isValidInternalRequest } from '@/lib/internalAuth';
import { findRoulette } from '@/lib/games';
import { getRecentNumbers } from '@/lib/mongo';
import { ensembleSuggestionWithConfidence } from '@/lib/suggestionConfidence';

export async function GET(req: Request) {
  if (!isValidInternalRequest(req)) {
    return NextResponse.json({ error: 'Não autorizado.' }, { status: 401 });
  }
  const gameId = new URL(req.url).searchParams.get('gameId') || '';
  const game = findRoulette(gameId);
  if (!game) {
    return NextResponse.json({ error: 'Jogo não disponível.' }, { status: 404 });
  }
  const history = await getRecentNumbers(game.rouletteId, 360);
  const { picks, confidence } = ensembleSuggestionWithConfidence(
    history,
    game.rouletteId,
  );
  return NextResponse.json({
    numbers: picks.map((pick) => pick.num),
    confidence,
    sampleSize: history.length,
  });
}
