import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { findAppUser } from '@/lib/mongo';
import { getBookmakerUser } from '@/lib/bookmaker';

// Saldo/usuário ao vivo (consumido pelo polling do BalanceBadge).
export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  }

  const user = await findAppUser(session.email, session.house);
  if (!user?.lotogreenToken) {
    return NextResponse.json({ balance: null }, { status: 200 });
  }

  const bookmaker = await getBookmakerUser(user.lotogreenToken, session.house);
  return NextResponse.json({
    balance: typeof bookmaker?.balance === 'number' ? bookmaker.balance : null,
    name: bookmaker?.name ?? null,
  });
}
