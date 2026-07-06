import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { getUsers } from '@/lib/mongo';
import { startGame } from '@/lib/bookmaker';
import { findRoulette } from '@/lib/games';

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ gameId: string }> },
) {
  const { gameId } = await params;

  // Só permitimos as roletas curadas.
  if (!findRoulette(gameId)) {
    return NextResponse.json({ error: 'Jogo não disponível.' }, { status: 404 });
  }

  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  }

  const users = await getUsers();
  const user = await users.findOne({ email: session.email });
  if (!user?.lotogreenToken) {
    return NextResponse.json(
      { error: 'Sessão da LotoGreen não encontrada. Faça login novamente.' },
      { status: 401 },
    );
  }

  const result = await startGame(gameId, user.lotogreenToken, session.house);
  if (!result.ok || !result.link) {
    return NextResponse.json(
      { error: result.error ?? 'Falha ao iniciar o jogo.' },
      { status: result.status },
    );
  }

  return NextResponse.json({ link: result.link });
}
