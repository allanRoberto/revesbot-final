import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from 'next/navigation';
import SubscriptionGate from '@/components/SubscriptionGate';
import { getSession } from '@/lib/session';
import TriggerDashboard from './TriggerDashboard';
import styles from './triggers.module.css';

export const metadata: Metadata = {
  title: 'Estratégias de gatilho | RevesBot',
  description: 'Monitor prospectivo das estratégias de entrada do motor orbital.',
};

export default async function TriggerCatalogPage() {
  const session = await getSession();
  if (!session) redirect('/login');

  return (
    <div className="shell">
      <header className="topbar">
        <div className="logo-sm">REVESBOT</div>
        <div className="topbar-right">
          <span className={styles.liveMarker}>Monitor ativo</span>
          <span className="user-email">{session.email}</span>
          <Link className="logout-sm" href="/orbit">Sugestões</Link>
          <Link className="logout-sm" href="/dashboard">Voltar</Link>
        </div>
      </header>

      <main className={styles.page}>
        <div className={styles.hero}>
          <div>
            <span>Motor de entradas · 7 estratégias</span>
            <h1>Gatilhos orbitais</h1>
            <p>
              Cada regra é monitorada no servidor, congela a entrada no instante do
              gatilho e mede uma janela completa de cinco tentativas.
            </p>
          </div>
          <div className={styles.heroBadge}>
            <strong>5 tentativas</strong>
            <span>em todos os modelos</span>
          </div>
        </div>
        <TriggerDashboard />
      </main>

      <SubscriptionGate />
    </div>
  );
}
