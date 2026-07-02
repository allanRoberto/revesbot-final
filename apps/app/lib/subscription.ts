import { getSubscriptions, AppSubscription } from '@/lib/mongo';
import { findPlan } from '@/lib/plans';
import { getPixConfig, buildPixPayload } from '@/lib/pix';
import { randomUUID } from 'crypto';

export interface SubStatus {
  active: boolean;
  status: AppSubscription['status'] | 'none';
  planId?: string;
  expiresAt?: string | null;
}

// Paywall só é aplicado quando SUBSCRIPTION_ENABLED=true. Enquanto desligado,
// todo mundo é tratado como assinante ativo (sugestões liberadas, sem modal).
export function subscriptionEnabled(): boolean {
  return process.env.SUBSCRIPTION_ENABLED === 'true';
}

export async function getSubscriptionStatus(email: string): Promise<SubStatus> {
  if (!subscriptionEnabled()) {
    return { active: true, status: 'active' };
  }
  const subs = await getSubscriptions();
  const sub = await subs.findOne({ email });
  if (!sub) return { active: false, status: 'none' };

  const active =
    sub.status === 'active' &&
    !!sub.expiresAt &&
    new Date(sub.expiresAt).getTime() > Date.now();

  return {
    active,
    status: active ? 'active' : sub.status === 'active' ? 'expired' : sub.status,
    planId: sub.planId,
    expiresAt: sub.expiresAt ? new Date(sub.expiresAt).toISOString() : null,
  };
}

export async function isActive(email: string): Promise<boolean> {
  return (await getSubscriptionStatus(email)).active;
}

export interface CheckoutResult {
  ok: boolean;
  error?: string;
  planName?: string;
  amountCents?: number;
  orderRef?: string;
  pixCode?: string | null;
}

/**
 * Registra (ou atualiza) um pedido PENDENTE de assinatura e devolve os dados
 * do PIX (copia-e-cola). A liberação é feita manualmente (sem gateway ainda).
 */
export async function createCheckout(
  email: string,
  planId: string,
): Promise<CheckoutResult> {
  const plan = findPlan(planId);
  if (!plan) return { ok: false, error: 'Plano inválido.' };

  const orderRef = `REVES${randomUUID().replace(/-/g, '').slice(0, 12).toUpperCase()}`;
  const now = new Date();

  const subs = await getSubscriptions();
  await subs.updateOne(
    { email },
    {
      $set: {
        email,
        status: 'pending',
        planId: plan.id,
        amountCents: plan.priceCents,
        orderRef,
        requestedAt: now,
        atualizadoEm: now,
      },
      $setOnInsert: { criadoEm: now },
    },
    { upsert: true },
  );

  const pixCfg = getPixConfig();
  const pixCode = pixCfg
    ? buildPixPayload(pixCfg, plan.priceCents, orderRef)
    : null;

  return {
    ok: true,
    planName: plan.name,
    amountCents: plan.priceCents,
    orderRef,
    pixCode,
  };
}
