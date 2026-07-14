import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { findAppUser } from '@/lib/mongo';
import { startGame } from '@/lib/bookmaker';
import { findCasinoGame } from '@/lib/games';

// Devolve o link jogável de um jogo de cassino (ex.: Mines) na conta do próprio
// usuário. O cliente abre esse link em NOVA ABA (jogo nativo, sem overlay nosso).
export async function POST(
  _req: Request,
  { params }: { params: Promise<{ gameId: string }> },
) {
  const { gameId } = await params;

  // Só jogos da lista curada podem ser lançados.
  if (!findCasinoGame(gameId)) {
    return NextResponse.json({ error: 'Jogo não disponível.' }, { status: 404 });
  }

  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  }

  const user = await findAppUser(session.email, session.house);
  if (!user?.lotogreenToken) {
    return NextResponse.json(
      { error: 'Sessão da casa não encontrada. Faça login novamente.' },
      { status: 401 },
    );
  }

  const result = await startGame(gameId, user.lotogreenToken, session.house);
  if (!result.ok || !result.link) {
    return NextResponse.json(
      { error: result.error ?? 'Falha ao abrir o jogo.' },
      { status: result.status },
    );
  }

  return NextResponse.json({ link: result.link });
}
