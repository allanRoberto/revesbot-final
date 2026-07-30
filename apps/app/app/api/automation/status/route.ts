import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import {
  finalizeAutomationRun,
  getAutomationView,
} from '@/lib/automation';
import { findAppUser } from '@/lib/mongo';
import { getBookmakerUser } from '@/lib/bookmaker';
import {
  automationIsActivated,
  reconcilePendingPixGoPayments,
} from '@/lib/invoices';
import { houseName } from '@/lib/houses';

export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  }

  await reconcilePendingPixGoPayments(session.email);
  let view = await getAutomationView(session.email);
  if (
    view.run?.expiresAt &&
    ['starting', 'waiting_signal', 'running'].includes(view.run.status) &&
    new Date(view.run.expiresAt) <= new Date()
  ) {
    await finalizeAutomationRun(view.run.runId, 'time_limit');
    view = await getAutomationView(session.email);
  }

  const user = await findAppUser(session.email, session.house);
  const bookmaker = user?.lotogreenToken
    ? await getBookmakerUser(user.lotogreenToken, session.house)
    : null;

  return NextResponse.json({
    ...view,
    activated: await automationIsActivated(session.email),
    connection: {
      house: session.house,
      houseName: houseName(session.house),
      connected: Boolean(user?.lotogreenToken),
      balanceCents:
        typeof bookmaker?.balance === 'number' ? bookmaker.balance : null,
    },
    signalSourceConnected:
      process.env.AUTOMATION_SIGNAL_SOURCE_ENABLED === 'true',
  });
}
