// Casas de apostas suportadas. Todas usam a MESMA API (mesma plataforma);
// muda só o domínio. Para adicionar uma casa nova, basta um item aqui
// (e o mesmo id/domínio no registry do auth_api).

export interface House {
  id: string;
  name: string;
  domain: string;
  // 'http' = proxy servidor-a-servidor (auth_api). 'browser' = login headless
  // (house-agent) para casas Nuxt/BFF com Cloudflare (Esportiva, Bateu).
  mode: 'http' | 'browser';
}

export const HOUSES: House[] = [
  { id: 'lotogreen', name: 'LotoGreen', domain: 'lotogreen.bet.br', mode: 'http' },
  { id: 'esportiva', name: 'Esportiva', domain: 'esportiva.bet.br', mode: 'browser' },
  { id: 'bateu', name: 'Bateu', domain: 'bateu.bet.br', mode: 'browser' },
];

export const DEFAULT_HOUSE = 'lotogreen';

export function findHouse(id?: string | null): House | undefined {
  return HOUSES.find((h) => h.id === id);
}

export function houseName(id?: string | null): string {
  return findHouse(id)?.name ?? 'casa de apostas';
}

export function houseMode(id?: string | null): 'http' | 'browser' {
  return findHouse(id)?.mode ?? 'http';
}
