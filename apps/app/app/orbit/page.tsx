import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from 'next/navigation';
import SubscriptionGate from '@/components/SubscriptionGate';
import { getSession } from '@/lib/session';
import OrbitDashboard from './OrbitDashboard';
import styles from './page.module.css';

export const metadata: Metadata = {
  title: 'Órbita de sugestões | RevesBot',
  description: 'Ranking orbital consolidado pelos três últimos resultados.',
};

export default async function OrbitPage() {
  const session = await getSession();
  if (!session) redirect('/login');

  return (
    <div className="shell">
      <header className="topbar">
        <div className="logo-sm">REVESBOT</div>
        <div className="topbar-right">
          <span className={styles.liveMarker}>Shadow mode</span>
          <span className="user-email">{session.email}</span>
          <Link className="logout-sm" href="/dashboard">
            Voltar
          </Link>
        </div>
      </header>

      <main className={styles.page}>
        <div className={styles.hero}>
          <div>
            <span className={styles.eyebrow}>Motor orbital · 3 pivôs</span>
            <h1>Sugestões por roleta</h1>
            <p>
              Consenso do último, penúltimo e antepenúltimo resultado, usando até
              6 ocorrências anteriores de cada pivô.
            </p>
          </div>
          <div className={styles.heroActions}>
            <div className={styles.methodBadge}>
              <strong>1,00 · 0,85 · 0,70</strong>
              <span>peso por recência</span>
            </div>
            <Link className={styles.triggerLink} href="/orbit/triggers">
              Estratégias de gatilho →
            </Link>
          </div>
        </div>

        <OrbitDashboard />
      </main>

      <SubscriptionGate />
    </div>
  );
}
