export const COMMISSION_BPS = 5000; // 50%
export const PIXGO_MIN_PAYMENT_CENTS = 1000; // R$ 10,00

function envBps(name: string, fallback: number): number {
  const value = Number(process.env[name]);
  if (!Number.isFinite(value) || value <= 0 || value > 10_000) return fallback;
  return Math.round(value);
}
/** Percentual inicial da meta sobre a banca. Centralizado para ajuste futuro. */
export function targetRateBps(): number {
  return envBps('AUTO_TARGET_RATE_BPS', 1000); // 10% da banca
}

/** Limite de perda padrão da execução. */
export function maxLossRateBps(): number {
  return envBps('AUTO_MAX_LOSS_RATE_BPS', 2000); // 20% da banca
}

export function calculateTargetProfitCents(bankrollCents: number): number {
  return Math.max(1, Math.round((bankrollCents * targetRateBps()) / 10_000));
}

export function calculateMaxLossCents(bankrollCents: number): number {
  return Math.max(1, Math.round((bankrollCents * maxLossRateBps()) / 10_000));
}

export function calculateCommissionCents(netProfitCents: number): number {
  return Math.floor((Math.max(0, netProfitCents) * COMMISSION_BPS) / 10_000);
}
