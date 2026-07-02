// Planos de assinatura. Preços em CENTAVOS. Ajuste à vontade.
export interface Plan {
  id: string;
  name: string;
  priceCents: number;
  durationDays: number;
  highlight?: boolean;
  /** Não exibido no paywall público (concedido manualmente como benefício). */
  hidden?: boolean;
}

// Duração usada para o plano vitalício (~100 anos = "para sempre" na prática).
export const LIFETIME_DAYS = 36500;

export const PLANS: Plan[] = [
  { id: 'mensal', name: 'Mensal', priceCents: 4990, durationDays: 30, highlight: true },
  { id: 'trimestral', name: 'Trimestral', priceCents: 11990, durationDays: 90 },
  { id: 'vitalicio', name: 'Vitalício', priceCents: 0, durationDays: LIFETIME_DAYS, hidden: true },
];

export function findPlan(id: string): Plan | undefined {
  return PLANS.find((p) => p.id === id);
}

export function formatBRLfromCents(cents: number): string {
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
  }).format(cents / 100);
}
