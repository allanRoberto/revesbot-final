import { NextResponse } from 'next/server';
import { MongoServerError } from 'mongodb';
import {
  ensureAutomationIndexes,
  getAutomationBillingAccounts,
  getAutomationInvoices,
  getAutomationRuns,
  getCommissionPaymentOrders,
  getPaymentWebhookEvents,
} from '@/lib/mongo';
import { getPixGoPaymentStatus, verifyPixGoWebhook } from '@/lib/pixgo';

export async function POST(req: Request) {
  const rawBody = await req.text();
  const timestamp = req.headers.get('x-webhook-timestamp') || '';
  const signature = req.headers.get('x-webhook-signature') || '';
  if (!verifyPixGoWebhook(rawBody, timestamp, signature)) {
    return NextResponse.json({ error: 'Assinatura inválida.' }, { status: 401 });
  }

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return NextResponse.json({ error: 'Payload inválido.' }, { status: 400 });
  }
  const event = String(payload.event || req.headers.get('x-webhook-event') || '');
  const data = ((payload.data as Record<string, unknown>) || payload);
  const paymentId = String(data.payment_id || payload.payment_id || '');
  const externalId = String(data.external_id || payload.external_id || '');
  if (!event || !paymentId) {
    return NextResponse.json({ error: 'Evento incompleto.' }, { status: 400 });
  }

  await ensureAutomationIndexes();
  const events = await getPaymentWebhookEvents();
  const eventKey = `${event}:${paymentId}:${timestamp}`;
  if (await events.findOne({ eventKey })) {
    return NextResponse.json({ received: true, duplicate: true });
  }

  const [orders, invoices, billing, runs] = await Promise.all([
    getCommissionPaymentOrders(),
    getAutomationInvoices(),
    getAutomationBillingAccounts(),
    getAutomationRuns(),
  ]);
  const order = await orders.findOne({ providerPaymentId: paymentId });
  if (!order || (externalId && order.externalId !== externalId)) {
    return NextResponse.json({ error: 'Cobrança não reconhecida.' }, { status: 404 });
  }
  const now = new Date();

  if (event === 'payment.completed') {
    const confirmed = await getPixGoPaymentStatus(paymentId);
    if (
      confirmed.status !== 'completed' ||
      confirmed.externalId !== order.externalId ||
      confirmed.amountCents !== order.amountCents
    ) {
      return NextResponse.json({ error: 'Confirmação divergente.' }, { status: 409 });
    }
    await orders.updateOne(
      { orderId: order.orderId, status: { $in: ['pending', 'expired'] } },
      {
        $set: {
          status: 'completed',
          paidAt: confirmed.updatedAt,
          atualizadoEm: now,
        },
      },
    );
    if (order.invoiceId) {
      await invoices.updateOne(
        {
          invoiceId: order.invoiceId,
          email: order.email,
          status: { $in: ['pending', 'awaiting_payment'] },
        },
        {
          $set: {
            status: 'paid',
            paidAt: confirmed.updatedAt,
            atualizadoEm: now,
          },
        },
      );
    }
    if (order.runId) {
      await billing.updateOne(
        { email: order.email, activeRunId: order.runId },
        {
          $set: {
            status: 'clear',
            outstandingCents: 0,
            atualizadoEm: now,
          },
          $unset: { activeRunId: '' },
        },
      );
      await runs.updateOne(
        { runId: order.runId, status: 'payment_due' },
        { $set: { status: 'completed', atualizadoEm: now } },
      );
    }
  } else if (event === 'payment.expired') {
    const changed = await orders.updateOne(
      { orderId: order.orderId, status: 'pending' },
      { $set: { status: 'expired', atualizadoEm: now } },
    );
    if (changed.modifiedCount > 0) {
      if (order.invoiceId) {
        await invoices.updateOne(
          { invoiceId: order.invoiceId, status: 'awaiting_payment' },
          { $set: { status: 'pending', atualizadoEm: now } },
        );
      }
      if (order.runId) {
        await billing.updateOne(
          { email: order.email },
          { $set: { status: 'payment_due', atualizadoEm: now } },
        );
      }
    }
  } else if (event === 'payment.refunded') {
    const changed = await orders.updateOne(
      { orderId: order.orderId, status: 'completed' },
      { $set: { status: 'refunded', atualizadoEm: now } },
    );
    if (changed.modifiedCount > 0) {
      if (order.invoiceId) {
        await invoices.updateOne(
          { invoiceId: order.invoiceId },
          {
            $set: { status: 'pending', atualizadoEm: now },
            $unset: { paidAt: '' },
          },
        );
      }
      if (order.runId) {
        await billing.updateOne(
          { email: order.email },
          {
            $set: {
              status: 'payment_due',
              outstandingCents: order.amountCents,
              activeRunId: order.runId,
              atualizadoEm: now,
            },
          },
          { upsert: true },
        );
        await runs.updateOne(
          { runId: order.runId },
          { $set: { status: 'payment_due', atualizadoEm: now } },
        );
      }
    }
  }

  // Só marca o evento como processado depois de concluir os efeitos. Se a
  // consulta de confirmação ou o banco falhar, a PixGo poderá tentar de novo.
  try {
    await events.insertOne({
      eventKey,
      provider: 'pixgo',
      event,
      providerPaymentId: paymentId,
      externalId: externalId || undefined,
      payload,
      recebidoEm: new Date(),
    });
  } catch (error) {
    if (!(error instanceof MongoServerError && error.code === 11000)) {
      throw error;
    }
  }

  return NextResponse.json({ received: true });
}
