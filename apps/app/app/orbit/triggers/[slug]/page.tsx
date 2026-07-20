import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from 'next/navigation';
import SubscriptionGate from '@/components/SubscriptionGate';
import { getSession } from '@/lib/session';
import TriggerDashboard from '../TriggerDashboard';
import styles from '../triggers.module.css';

export const metadata: Metadata = {
  title: 'Detalhe do gatilho | RevesBot',
  description: 'Assertividade, entradas e histórico da estratégia orbital.',
};

export default async function TriggerDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const session = await getSession();
  if (!session) redirect('/login');
  const { slug } = await params;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="logo-sm">REVESBOT</div>
        <div className="topbar-right">
          <span className={styles.liveMarker}>Monitor ativo</span>
          <span className="user-email">{session.email}</span>
          <Link className="logout-sm" href="/orbit/triggers">Gatilhos</Link>
          <Link className="logout-sm" href="/orbit">Sugestões</Link>
        </div>
      </header>

      <main className={styles.page}>
        <Link className={styles.backLink} href="/orbit/triggers">← Todas as estratégias</Link>
        <div className={styles.detailHero}>
          <span>Estratégia individual</span>
          <h1>Monitor do gatilho</h1>
          <p>Assertividade separada por roleta, horário e tentativa.</p>
        </div>
        <TriggerDashboard slug={slug} />
      </main>

      <SubscriptionGate />
    </div>
  );
}
