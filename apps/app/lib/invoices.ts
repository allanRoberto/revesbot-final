import 'server-only';

import { createHash, randomUUID } from 'crypto';
import {
  AutomationInvoice,
  ensureAutomationIndexes,
  getAutomationInvoices,
} from '@/lib/mongo';

export const AUTOMATION_ACTIVATION_PRICE_CENTS = 3000;

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
