import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { getRecentNumbers } from '@/lib/mongo';
import { findRoulette } from '@/lib/games';
import { motorSuggestion, MOTOR_HISTORY_LIMIT } from '@/lib/motorCorrelacoes';
import { isActive } from '@/lib/subscription';

// Sugestão pelo MOTOR DE CORRELAÇÕES (9 números "concretos") — porte fiel do
// HTML "motor_correlacoes_monitor_api". Roda lado a lado com a sugestão por
// ensemble (/suggestion) para comparação de assertividade com os mesmos
// critérios (9 números, pagar em até 4 tentativas). Usa 300 números de
// histórico, o mesmo limite do monitor do HTML. Roda só no servidor.
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

  // Sugestão é exclusiva de assinantes com plano ativo (mesma regra do ensemble).
  if (!(await isActive(session.email))) {
    return NextResponse.json(
      { error: 'Assinatura necessária.', paywall: true },
      { status: 402 },
    );
  }

  const numbers = await getRecentNumbers(game.rouletteId, MOTOR_HISTORY_LIMIT);
  const result = motorSuggestion(numbers);

  return NextResponse.json({
    numbers: result?.concrete ?? [],
    logical: result?.logical ?? [],
    base: result?.base ?? null,
    behind: result?.behind ?? null,
    // 3 últimos números da mesa (mais recente primeiro) — base da análise.
    last: numbers.slice(0, 3),
    sampleSize: numbers.length,
    // Histórico usado no cálculo (mais recente primeiro). Prova de paridade:
    // cole exatamente esta lista no HTML e a sugestão tem que ser idêntica.
    history: numbers,
  });
}
