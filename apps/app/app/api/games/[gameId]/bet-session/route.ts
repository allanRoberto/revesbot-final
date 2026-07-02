import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { findAppUser } from '@/lib/mongo';
import { startGame } from '@/lib/bookmaker';
import { findRoulette, gameSlug, RouletteGame } from '@/lib/games';
import { houseMode } from '@/lib/houses';
import { decrypt } from '@/lib/crypto';
import { getHouseGameLink } from '@/lib/houseAgent';
import { isActive } from '@/lib/subscription';
import { createBetSession, getBetSessionState } from '@/lib/betws';

// Resolve o link jogável (playGame.do) conforme o modo da casa.
async function resolveGameLink(
  gameId: string,
  game: RouletteGame,
  user: { email: string; lotogreenToken: string; encryptedPassword?: { iv: string; authTag: string; ciphertext: string } },
  house: string,
): Promise<{ ok: true; link: string } | { ok: false; error: string; status: number }> {
  if (houseMode(house) === 'browser') {
    const slug = gameSlug(game, house);
    if (!slug) return { ok: false, error: 'Esta mesa não está disponível nesta casa.', status: 404 };
    if (!user.encryptedPassword) {
      return { ok: false, error: 'Reconecte-se à casa (senha não disponível).', status: 409 };
    }
    try {
      const password = decrypt(user.encryptedPassword);
      const { gameURL } = await getHouseGameLink(house, user.email, password, slug);
      return { ok: true, link: gameURL };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : 'Falha ao abrir a mesa.', status: 502 };
    }
  }
  // Casa http (LotoGreen): proxy servidor-a-servidor.
  const started = await startGame(gameId, user.lotogreenToken, house);
  if (!started.ok || !started.link) {
    return { ok: false, error: started.error ?? 'Não foi possível abrir a mesa.', status: started.status || 500 };
  }
  return { ok: true, link: started.link };
}

// Garante que o usuário está logado, é assinante e tem token da casa.
// Devolve { email, game, user } ou uma Response de erro.
async function guard(gameId: string) {
  const game = findRoulette(gameId);
  if (!game) {
    return { error: NextResponse.json({ error: 'Jogo não disponível.' }, { status: 404 }) };
  }
  const session = await getSession();
  if (!session) {
    return { error: NextResponse.json({ error: 'Não autenticado.' }, { status: 401 }) };
  }
  if (!(await isActive(session.email))) {
    return { error: NextResponse.json({ error: 'Assinatura necessária.', paywall: true }, { status: 402 }) };
  }
  const user = await findAppUser(session.email, session.house);
  if (!user?.lotogreenToken) {
    return { error: NextResponse.json({ error: 'Reconecte-se à casa de apostas.' }, { status: 409 }) };
  }
  return { game, user, house: session.house };
}

// POST → cria a sessão de mesa (captura o WS e conecta).
export async function POST(
  _req: Request,
  { params }: { params: Promise<{ gameId: string }> },
) {
  const { gameId } = await params;
  const g = await guard(gameId);
  if (g.error) return g.error;

  const resolved = await resolveGameLink(gameId, g.game!, g.user!, g.house!);
  if (!resolved.ok) {
    return NextResponse.json({ error: resolved.error }, { status: resolved.status });
  }

  try {
    const state = await createBetSession(resolved.link, g.game!.rouletteId);
    return NextResponse.json(state);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'Falha ao conectar na mesa.' },
      { status: 502 },
    );
  }
}

// GET ?sessionId= → estado atual da mesa.
export async function GET(
  req: Request,
  { params }: { params: Promise<{ gameId: string }> },
) {
  const { gameId } = await params;
  const g = await guard(gameId);
  if (g.error) return g.error;

  const sessionId = new URL(req.url).searchParams.get('sessionId');
  if (!sessionId) {
    return NextResponse.json({ error: 'sessionId é obrigatório.' }, { status: 400 });
  }

  try {
    const state = await getBetSessionState(sessionId);
    if (!state) return NextResponse.json({ error: 'session_not_found' }, { status: 404 });
    return NextResponse.json(state);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'Falha ao consultar a mesa.' },
      { status: 502 },
    );
  }
}
