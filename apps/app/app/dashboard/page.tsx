import { redirect } from 'next/navigation';
import { getSession } from '@/lib/session';
import { findAppUser } from '@/lib/mongo';
import { getBookmakerUser } from '@/lib/bookmaker';
import { ROULETTES } from '@/lib/games';
import { houseName } from '@/lib/houses';
import BalanceBadge from '@/components/BalanceBadge';
import SubscriptionGate from '@/components/SubscriptionGate';
import RouletteGrid from './RouletteGrid';

export default async function Dashboard() {
  const session = await getSession();
  if (!session) redirect('/login');

  const user = await findAppUser(session.email, session.house);
  const bookmaker = user?.lotogreenToken
    ? await getBookmakerUser(user.lotogreenToken, session.house)
    : null;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="logo-sm">REVESBOT</div>
        <div className="topbar-right">
          <BalanceBadge initial={bookmaker?.balance ?? null} />
          <span className="user-email">{session.email}</span>
          <a className="logout-sm" href="/api/auth/logout">
            Sair
          </a>
        </div>
      </header>

      <main className="content">
        <h1 className="page-title">Escolha uma roleta</h1>
        <p className="page-sub">Clique para entrar na mesa da {houseName(session.house)}.</p>
        <RouletteGrid games={ROULETTES} house={session.house} />
      </main>

      <SubscriptionGate />
    </div>
  );
}
