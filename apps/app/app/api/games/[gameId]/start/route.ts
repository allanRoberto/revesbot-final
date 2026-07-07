import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { findAppUser } from '@/lib/mongo';
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

  // Doc CERTO por (email, casa) — o findOne({email}) pegava um doc antigo/de
  // outra casa e mandava um token stale, causando "precisa estar logado".
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
      { error: result.error ?? 'Falha ao iniciar o jogo.' },
      { status: result.status },
    );
  }

  return NextResponse.json({ link: result.link });
}
