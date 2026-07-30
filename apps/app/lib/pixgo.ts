import crypto from 'crypto';

const PIXGO_BASE_URL = (
  process.env.PIXGO_BASE_URL || 'https://pixgo.org/api/v1'
).replace(/\/$/, '');
const PIXGO_WEBHOOK_TOLERANCE_SECONDS = 24 * 60 * 60;

function apiKey(): string {
  const value = process.env.PIXGO_API_KEY;
  if (!value) throw new Error('PIXGO_API_KEY não configurada.');
  return value;
}

/**
 * A PixGo pode devolver datas sem fuso, usando o horário de Brasília.
 * Sem essa normalização, servidores em UTC interpretam a expiração três horas
 * antes e podem oferecer uma segunda cobrança enquanto a primeira ainda vale.
 */
function parsePixGoDate(value: unknown): Date | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const normalized = value.trim().replace(' ', 'T');
  const withTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized)
    ? normalized
    : `${normalized}-03:00`;
  const parsed = new Date(withTimezone);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed;
}
export interface PixGoPayment {
  paymentId: string;
  externalId: string;
  amountCents: number;
  status: string;
  qrCode: string;
  qrImageUrl?: string;
  expiresAt?: Date;
}

export async function createPixGoPayment(input: {
  amountCents: number;
  description: string;
  externalId: string;
  receiverName: string;
  receiverCpf: string;
  receiverEmail: string;
  receiverPhone?: string;
}): Promise<PixGoPayment> {
  const webhookUrl = process.env.PIXGO_WEBHOOK_URL;
  const res = await fetch(`${PIXGO_BASE_URL}/payment/create`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': apiKey(),
    },
    body: JSON.stringify({
      amount: input.amountCents / 100,
      description: input.description.slice(0, 200),
      external_id: input.externalId.slice(0, 50),
      receiver_name: input.receiverName,
      receiver_cpf: input.receiverCpf,
      receiver_email: input.receiverEmail,
      ...(input.receiverPhone ? { receiver_phone: input.receiverPhone } : {}),
      ...(webhookUrl ? { webhook_url: webhookUrl } : {}),
    }),
    cache: 'no-store',
  });
  const body = await res.json().catch(() => ({}));
  const data = body?.data || {};
  if (!res.ok || !body?.success || !data.payment_id || !data.qr_code) {
    throw new Error(body?.message || body?.error || `PixGo respondeu ${res.status}`);
  }
  return {
    paymentId: String(data.payment_id),
    externalId: String(data.external_id || input.externalId),
    amountCents: Math.round(Number(data.amount) * 100),
    status: String(data.status || 'pending'),
    qrCode: String(data.qr_code),
    qrImageUrl: data.qr_image_url ? String(data.qr_image_url) : undefined,
    expiresAt: parsePixGoDate(data.expires_at),
  };
}

export async function getPixGoPaymentStatus(paymentId: string) {
  const res = await fetch(
    `${PIXGO_BASE_URL}/payment/${encodeURIComponent(paymentId)}/status`,
    {
      headers: { 'x-api-key': apiKey() },
      cache: 'no-store',
    },
  );
  const body = await res.json().catch(() => ({}));
  if ((!res.ok && res.status !== 410) || !body?.success || !body?.data) {
    throw new Error(body?.message || body?.error || `PixGo respondeu ${res.status}`);
  }
  return {
    paymentId: String(body.data.payment_id || paymentId),
    externalId: String(body.data.external_id || ''),
    amountCents: Math.round(Number(body.data.amount) * 100),
    status: String(body.data.status || ''),
    updatedAt: parsePixGoDate(body.data.updated_at) || new Date(),
  };
}

export function verifyPixGoWebhook(
  rawBody: string,
  timestamp: string,
  signature: string,
): boolean {
  const secret = process.env.PIXGO_WEBHOOK_SECRET;
  if (!secret || !timestamp || !/^[a-f0-9]{64}$/i.test(signature)) return false;
  const unix = Number(timestamp);
  if (
    !Number.isFinite(unix) ||
    Math.abs(Date.now() / 1000 - unix) > PIXGO_WEBHOOK_TOLERANCE_SECONDS
  ) {
    return false;
  }
  const expected = crypto
    .createHmac('sha256', secret)
    .update(`${timestamp}.${rawBody}`)
    .digest('hex');
  const expectedBuffer = Buffer.from(expected, 'hex');
  const receivedBuffer = Buffer.from(signature, 'hex');
  return (
    expectedBuffer.length === receivedBuffer.length &&
    crypto.timingSafeEqual(expectedBuffer, receivedBuffer)
  );
}
