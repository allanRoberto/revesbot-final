import Link from 'next/link';
import { redirect } from 'next/navigation';
import { getSession } from '@/lib/session';
import AutomationDashboard from '@/components/AutomationDashboard';

export default async function AutomaticoPage() {
  const session = await getSession();
  if (!session) redirect('/login');

  return (
    <div className="automation-shell">
      <header className="topbar">
        <div className="logo-sm">REVESBOT</div>
        <div className="topbar-right">
          <Link className="logout-sm" href="/dashboard">
            Apostas manuais
          </Link>
          <span className="user-email">{session.email}</span>
          <a className="logout-sm" href="/api/auth/logout">
            Sair
          </a>
        </div>
      </header>
      <AutomationDashboard />
    </div>
  );
}
