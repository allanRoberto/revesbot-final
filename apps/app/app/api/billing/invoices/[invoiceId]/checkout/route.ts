import { randomUUID } from 'crypto';
import { NextResponse } from 'next/server';
import QRCode from 'qrcode';
import { getSession } from '@/lib/session';
import {
  ensureAutomationIndexes,
  getAutomationInvoices,
  getCommissionPaymentOrders,
} from '@/lib/mongo';
import { createPixGoPayment } from '@/lib/pixgo';
import { reconcilePendingPixGoPayments } from '@/lib/invoices';

function digits(value: string): string {
  return value.replace(/\D/g, '');
}
export async function POST(
  req: Request,
  { params }: { params: Promise<{ invoiceId: string }> },
) {
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

  const { invoiceId } = await params;
  await ensureAutomationIndexes();
  await reconcilePendingPixGoPayments(session.email);
  const [invoices, orders] = await Promise.all([
    getAutomationInvoices(),
    getCommissionPaymentOrders(),
  ]);
  const invoice = await invoices.findOne({
    invoiceId,
    email: session.email,
  });
  if (!invoice) {
    return NextResponse.json({ error: 'Fatura não encontrada.' }, { status: 404 });
  }
  if (invoice.status === 'paid') {
    return NextResponse.json({ error: 'Esta fatura já foi paga.' }, { status: 409 });
  }
  if (invoice.status === 'canceled') {
    return NextResponse.json({ error: 'Esta fatura foi cancelada.' }, { status: 409 });
  }

  const existing = await orders.findOne(
    { email: session.email, invoiceId, status: 'pending' },
    { sort: { criadoEm: -1 } },
  );
  if (existing && (!existing.expiresAt || existing.expiresAt > new Date())) {
    const pixQr = existing.qrCode
      ? await QRCode.toDataURL(existing.qrCode, { margin: 1, width: 280 })
      : null;
    return NextResponse.json({ invoice, order: existing, pixQr });
  }
  if (existing) {
    await orders.updateOne(
      { orderId: existing.orderId, status: 'pending' },
      { $set: { status: 'expired', atualizadoEm: new Date() } },
    );
  }

  const orderId = randomUUID();
  const externalId = `revesbot_${orderId.replace(/-/g, '').slice(0, 24)}`;
  try {
    const payment = await createPixGoPayment({
      amountCents: invoice.amountCents,
      description: invoice.description,
      externalId,
      receiverName: name,
      receiverCpf: cpf,
      receiverEmail: session.email,
      receiverPhone: phone || undefined,
    });
    if (payment.amountCents !== invoice.amountCents) {
      throw new Error('A PixGo devolveu um valor diferente da fatura.');
    }

    const now = new Date();
    const order = {
      orderId,
      invoiceId: invoice.invoiceId,
      email: session.email,
      ...(invoice.runId ? { runId: invoice.runId } : {}),
      provider: 'pixgo' as const,
      providerPaymentId: payment.paymentId,
      externalId,
      amountCents: invoice.amountCents,
      status: 'pending' as const,
      qrCode: payment.qrCode,
      qrImageUrl: payment.qrImageUrl,
      expiresAt: payment.expiresAt,
      criadoEm: now,
      atualizadoEm: now,
    };
    await orders.insertOne(order);
    await invoices.updateOne(
      { invoiceId: invoice.invoiceId, status: 'pending' },
      { $set: { status: 'awaiting_payment', atualizadoEm: now } },
    );
    const pixQr = await QRCode.toDataURL(payment.qrCode, { margin: 1, width: 280 });
    return NextResponse.json({
      invoice: { ...invoice, status: 'awaiting_payment' },
      order,
      pixQr,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Falha ao gerar o PIX.' },
      { status: 502 },
    );
  }
}
