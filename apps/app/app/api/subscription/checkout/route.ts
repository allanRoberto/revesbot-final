import { NextResponse } from 'next/server';
import QRCode from 'qrcode';
import { getSession } from '@/lib/session';
import { createCheckout } from '@/lib/subscription';

// Cria um pedido pendente de assinatura e devolve o PIX (copia-e-cola + QR).
export async function POST(req: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  }

  let body: { planId?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Requisição inválida.' }, { status: 400 });
  }
  if (!body.planId) {
    return NextResponse.json({ error: 'Informe o plano.' }, { status: 400 });
  }

  const result = await createCheckout(session.email, body.planId);
  if (!result.ok) {
    return NextResponse.json({ error: result.error }, { status: 400 });
  }

  let pixQr: string | null = null;
  if (result.pixCode) {
    pixQr = await QRCode.toDataURL(result.pixCode, { margin: 1, width: 280 });
  }

  return NextResponse.json({
    planName: result.planName,
    amountCents: result.amountCents,
    orderRef: result.orderRef,
    pixCode: result.pixCode,
    pixQr,
  });
}
