import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { findRoulette } from '@/lib/games';
import { isActive } from '@/lib/subscription';
import { placeBet } from '@/lib/betws';

// Aposta os números escolhidos no tabuleiro (números cheios; vizinhos já vêm
// expandidos na lista). body: { sessionId, numbers: number[], chipValue?: number }
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

  let body: { sessionId?: string; numbers?: number[]; chipValue?: number };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Requisição inválida.' }, { status: 400 });
  }
  if (!body.sessionId) {
    return NextResponse.json({ error: 'sessionId é obrigatório.' }, { status: 400 });
  }

  // Valida e normaliza os números (0–36), sem duplicatas, limite de segurança.
  const numbers = [...new Set((body.numbers || []).map(Number))].filter(
    (n) => Number.isInteger(n) && n >= 0 && n <= 36,
  );
  if (numbers.length === 0) {
    return NextResponse.json({ error: 'Nenhum número válido.' }, { status: 400 });
  }
  if (numbers.length > 37) {
    return NextResponse.json({ error: 'Muitos números.' }, { status: 400 });
  }

  try {
    const result = await placeBet(body.sessionId, numbers, body.chipValue);
    return NextResponse.json(result);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'Falha ao apostar.' },
      { status: 409 },
    );
  }
}
