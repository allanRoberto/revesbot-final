import 'server-only';

import { createHash, randomUUID } from 'crypto';
import {
  AutomationInvoice,
  ensureAutomationIndexes,
  getAutomationBillingAccounts,
  getAutomationInvoices,
  getAutomationRuns,
  getCommissionPaymentOrders,
} from '@/lib/mongo';
import { getPixGoPaymentStatus } from '@/lib/pixgo';

export const AUTOMATION_ACTIVATION_PRICE_CENTS = 3000;
const RECONCILIATION_WINDOW_MS = 30 * 60 * 1000;

function activationInvoiceId(email: string): string {
  const digest = createHash('sha256')
    .update(email.trim().toLowerCase())
    .digest('hex')
    .slice(0, 24);
  return `activation_${digest}`;
}
export async function ensureActivationInvoice(
  email: string,
): Promise<AutomationInvoice> {
  await ensureAutomationIndexes();
  const invoices = await getAutomationInvoices();
  const normalizedEmail = email.trim().toLowerCase();
  const now = new Date();
  const invoiceId = activationInvoiceId(normalizedEmail);

  await invoices.updateOne(
    { invoiceId },
    {
      $setOnInsert: {
        invoiceId,
        email: normalizedEmail,
        type: 'activation',
        description: 'Ativação do bot automático',
        amountCents: AUTOMATION_ACTIVATION_PRICE_CENTS,
        status: 'pending',
        criadoEm: now,
        atualizadoEm: now,
      },
    },
    { upsert: true },
  );

  const invoice = await invoices.findOne({ invoiceId });
  if (!invoice) throw new Error('Não foi possível criar a fatura de ativação.');
  return invoice;
}

export async function listAutomationInvoices(
  email: string,
): Promise<AutomationInvoice[]> {
  await ensureActivationInvoice(email);
  const invoices = await getAutomationInvoices();
  return invoices
    .find({ email: email.trim().toLowerCase() })
    .sort({ criadoEm: -1 })
    .limit(100)
    .toArray();
}

export async function automationIsActivated(email: string): Promise<boolean> {
  const invoice = await ensureActivationInvoice(email);
  return invoice.status === 'paid';
}

function providerCheckIntervalMs(ageMs: number): number {
  if (ageMs < 2 * 60 * 1000) return 5 * 1000;
  if (ageMs < 10 * 60 * 1000) return 15 * 1000;
  return 60 * 1000;
}

/**
 * Contingência para webhooks atrasados ou temporariamente rejeitados.
 *
 * A interface consulta o status a cada cinco segundos, mas a chamada externa é
 * limitada de forma progressiva e só ocorre para ordens pendentes. Depois de
 * trinta minutos, fazemos apenas uma consulta quando a ordem nunca foi checada.
 */
export async function reconcilePendingPixGoPayments(
  email: string,
): Promise<number> {
  await ensureAutomationIndexes();
  const normalizedEmail = email.trim().toLowerCase();
  const [orders, invoices, billing, runs] = await Promise.all([
    getCommissionPaymentOrders(),
    getAutomationInvoices(),
    getAutomationBillingAccounts(),
    getAutomationRuns(),
  ]);
  const pending = await orders
    .find({ email: normalizedEmail, status: 'pending' })
    .sort({ criadoEm: -1 })
    .limit(5)
    .toArray();
  let reconciled = 0;

  for (const order of pending) {
    const now = new Date();
    const ageMs = Math.max(0, now.getTime() - order.criadoEm.getTime());
    const checks = order.providerChecks ?? 0;
    if (ageMs > RECONCILIATION_WINDOW_MS && checks > 0) continue;

    const cutoff = new Date(
      now.getTime() - providerCheckIntervalMs(ageMs),
    );
    const claimed = await orders.updateOne(
      {
        orderId: order.orderId,
        status: 'pending',
        $or: [
          { lastProviderCheckAt: { $exists: false } },
          { lastProviderCheckAt: { $lte: cutoff } },
        ],
      },
      {
        $set: { lastProviderCheckAt: now, atualizadoEm: now },
        $inc: { providerChecks: 1 },
      },
    );
    if (claimed.modifiedCount === 0) continue;

    let provider;
    try {
      provider = await getPixGoPaymentStatus(order.providerPaymentId);
    } catch {
      continue;
    }
    if (
      provider.externalId !== order.externalId ||
      provider.amountCents !== order.amountCents
    ) {
      continue;
    }

    if (provider.status === 'completed') {
      await orders.updateOne(
        { orderId: order.orderId, status: 'pending' },
        {
          $set: {
            status: 'completed',
            paidAt: provider.updatedAt,
            atualizadoEm: new Date(),
          },
        },
      );
      if (order.invoiceId) {
        await invoices.updateOne(
          {
            invoiceId: order.invoiceId,
            email: normalizedEmail,
            status: { $in: ['pending', 'awaiting_payment'] },
          },
          {
            $set: {
              status: 'paid',
              paidAt: provider.updatedAt,
              atualizadoEm: new Date(),
            },
          },
        );
      }
      if (order.runId) {
        await billing.updateOne(
          { email: normalizedEmail, activeRunId: order.runId },
          {
            $set: {
              status: 'clear',
              outstandingCents: 0,
              atualizadoEm: new Date(),
            },
            $unset: { activeRunId: '' },
          },
        );
        await runs.updateOne(
          { runId: order.runId, status: 'payment_due' },
          { $set: { status: 'completed', atualizadoEm: new Date() } },
        );
      }
      reconciled += 1;
    } else if (
      ['expired', 'canceled', 'cancelled'].includes(provider.status)
    ) {
      await orders.updateOne(
        { orderId: order.orderId, status: 'pending' },
        { $set: { status: 'expired', atualizadoEm: new Date() } },
      );
      if (order.invoiceId) {
        await invoices.updateOne(
          { invoiceId: order.invoiceId, status: 'awaiting_payment' },
          { $set: { status: 'pending', atualizadoEm: new Date() } },
        );
      }
    }
  }

  return reconciled;
}

export async function createCommissionInvoice(input: {
  email: string;
  runId: string;
  amountCents: number;
  netProfitCents: number;
  commissionBps: number;
}): Promise<AutomationInvoice | null> {
  if (input.amountCents <= 0) return null;
  await ensureAutomationIndexes();
  const invoices = await getAutomationInvoices();
  const existing = await invoices.findOne({
    email: input.email,
    type: 'commission',
    runId: input.runId,
  });
  if (existing) return existing;

  const now = new Date();
  const invoice: AutomationInvoice = {
    invoiceId: randomUUID(),
    email: input.email,
    type: 'commission',
    description: 'Comissão de 50% sobre o lucro líquido do bot automático',
    amountCents: input.amountCents,
    status: 'pending',
    runId: input.runId,
    netProfitCents: input.netProfitCents,
    commissionBps: input.commissionBps,
    criadoEm: now,
    atualizadoEm: now,
  };
  await invoices.insertOne(invoice);
  return invoice;
}
