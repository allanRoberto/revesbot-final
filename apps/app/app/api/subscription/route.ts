import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { getSubscriptionStatus } from '@/lib/subscription';
import { PLANS } from '@/lib/plans';

// Status da assinatura do usuário logado + planos disponíveis (pro paywall).
export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  }

  const status = await getSubscriptionStatus(session.email);
  return NextResponse.json({
    ...status,
    plans: PLANS.filter((p) => !p.hidden).map((p) => ({
      id: p.id,
      name: p.name,
      priceCents: p.priceCents,
      durationDays: p.durationDays,
      highlight: !!p.highlight,
    })),
  });
}
