import { randomUUID } from 'crypto';
import { NextResponse } from 'next/server';
import QRCode from 'qrcode';
import { getSession } from '@/lib/session';
import {
  ensureAutomationIndexes,
  getAutomationBillingAccounts,
  getAutomationRuns,
  getCommissionPaymentOrders,
} from '@/lib/mongo';
import { PIXGO_MIN_PAYMENT_CENTS } from '@/lib/automationPolicy';
import { createPixGoPayment } from '@/lib/pixgo';

function digits(value: string): string {
  return value.replace(/\D/g, '');
}
export async function POST(req: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  }

  let body: {
    name?: string;
    cpf?: string;
    phone?: string;
    disclosureAccepted?: boolean;
  };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Requisição inválida.' }, { status: 400 });
  }

  const name = body.name?.trim() || '';
  const cpf = digits(body.cpf || '');
  const phone = digits(body.phone || '');
  if (name.length < 2 || ![11, 14].includes(cpf.length)) {
    return NextResponse.json(
      { error: 'Informe o nome e um CPF/CNPJ válido do pagador.' },
      { status: 400 },
    );
  }
  if (!body.disclosureAccepted) {
    return NextResponse.json(
      { error: 'É necessário aceitar a informação sobre o processamento PixGo/DEPIX.' },
      { status: 400 },
    );
  }

  await ensureAutomationIndexes();
  const [billing, orders, runs] = await Promise.all([
    getAutomationBillingAccounts(),
    getCommissionPaymentOrders(),
    getAutomationRuns(),
  ]);
  const account = await billing.findOne({ email: session.email });
  if (
    !account ||
    !['payment_due', 'awaiting_payment'].includes(account.status) ||
    account.outstandingCents < PIXGO_MIN_PAYMENT_CENTS ||
    !account.activeRunId
  ) {
    return NextResponse.json(
      { error: 'Não existe comissão disponível para cobrança.' },
      { status: 409 },
    );
  }

  const existing = await orders.findOne(
    { email: session.email, status: 'pending' },
    { sort: { criadoEm: -1 } },
  );
  if (existing && (!existing.expiresAt || existing.expiresAt > new Date())) {
    const pixQr = existing.qrCode
      ? await QRCode.toDataURL(existing.qrCode, { margin: 1, width: 280 })
      : null;
    return NextResponse.json({ order: existing, pixQr });
  }

  if (existing) {
    await orders.updateOne(
      { orderId: existing.orderId, status: 'pending' },
      { $set: { status: 'expired', atualizadoEm: new Date() } },
    );
  }

  const run = await runs.findOne({ runId: account.activeRunId });
  if (!run) {
    return NextResponse.json({ error: 'Execução de origem não encontrada.' }, { status: 409 });
  }

  const orderId = randomUUID();
  const externalId = `revesbot_${orderId.replace(/-/g, '').slice(0, 24)}`;
  try {
    const payment = await createPixGoPayment({
      amountCents: account.outstandingCents,
      description: `Comissão de 50% sobre o lucro líquido automático`,
      externalId,
      receiverName: name,
      receiverCpf: cpf,
      receiverEmail: session.email,
      receiverPhone: phone || undefined,
    });
    if (payment.amountCents !== account.outstandingCents) {
      throw new Error('A PixGo devolveu um valor diferente da cobrança.');
    }
    const now = new Date();
    const order = {
      orderId,
      email: session.email,
      runId: run.runId,
      provider: 'pixgo' as const,
      providerPaymentId: payment.paymentId,
      externalId,
      amountCents: account.outstandingCents,
      status: 'pending' as const,
      qrCode: payment.qrCode,
      qrImageUrl: payment.qrImageUrl,
      expiresAt: payment.expiresAt,
      criadoEm: now,
      atualizadoEm: now,
    };
    await orders.insertOne(order);
    await billing.updateOne(
      { email: session.email, status: 'payment_due' },
      { $set: { status: 'awaiting_payment', atualizadoEm: now } },
    );
    const pixQr = await QRCode.toDataURL(payment.qrCode, { margin: 1, width: 280 });
    return NextResponse.json({ order, pixQr });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Falha ao criar cobrança PixGo.' },
      { status: 502 },
    );
  }
}
