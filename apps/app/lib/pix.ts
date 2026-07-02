// Gera o "copia e cola" PIX (BR Code estático com valor) — padrão EMV/BACEN.
// Sem gateway: usa uma chave PIX configurada em ambiente. Integração automática vem depois.

function emv(id: string, value: string): string {
  const len = value.length.toString().padStart(2, '0');
  return `${id}${len}${value}`;
}

function crc16(payload: string): string {
  let crc = 0xffff;
  for (let i = 0; i < payload.length; i++) {
    crc ^= payload.charCodeAt(i) << 8;
    for (let j = 0; j < 8; j++) {
      crc = crc & 0x8000 ? (crc << 1) ^ 0x1021 : crc << 1;
      crc &= 0xffff;
    }
  }
  return crc.toString(16).toUpperCase().padStart(4, '0');
}

function sanitize(text: string, max: number): string {
  return text
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '') // remove acentos
    .replace(/[^A-Za-z0-9 ]/g, '')
    .toUpperCase()
    .slice(0, max)
    .trim();
}

export interface PixConfig {
  key: string;
  merchantName: string;
  merchantCity: string;
}

export function getPixConfig(): PixConfig | null {
  const key = process.env.PIX_KEY;
  if (!key) return null;
  return {
    key,
    merchantName: process.env.PIX_MERCHANT_NAME || 'REVESBOT',
    merchantCity: process.env.PIX_MERCHANT_CITY || 'SAO PAULO',
  };
}

/** Monta o BR Code (copia e cola) com valor em centavos e um txid (ref). */
export function buildPixPayload(
  cfg: PixConfig,
  amountCents: number,
  txid: string,
): string {
  const amount = (amountCents / 100).toFixed(2);
  const name = sanitize(cfg.merchantName, 25) || 'REVESBOT';
  const city = sanitize(cfg.merchantCity, 15) || 'SAO PAULO';
  const ref = sanitize(txid, 25).replace(/ /g, '') || '***';

  const merchantAccount = emv(
    '26',
    emv('00', 'br.gov.bcb.pix') + emv('01', cfg.key),
  );
  const additionalData = emv('62', emv('05', ref));

  let payload =
    emv('00', '01') + // payload format indicator
    merchantAccount +
    emv('52', '0000') + // merchant category code
    emv('53', '986') + // currency BRL
    emv('54', amount) +
    emv('58', 'BR') +
    emv('59', name) +
    emv('60', city) +
    additionalData;

  payload += '6304'; // CRC id + len
  return payload + crc16(payload);
}
