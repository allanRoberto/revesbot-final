// Casas de apostas suportadas. Cada casa diz POR ONDE o app conversa com ela
// (`integration`) e se está ATIVA. Casa inativa some do login e as sessões
// abertas nela deixam de valer: o usuário entra de novo numa casa ativa.
//
// Para adicionar uma casa de uma plataforma já integrada, basta um item aqui
// (casas 'auth-api' e 'house-agent' também precisam do mesmo id/domínio no
// registry do auth_api ou do house_agent).

export type HouseIntegration =
  /** Proxy HTTP pelo Express (apps/auth_api). Plataforma da LotoGreen. */
  | 'auth-api'
  /** Login headless pelo apps/house_agent (Nuxt/BFF com Cloudflare): Esportiva, Bateu. */
  | 'house-agent'
  /** API HTTP direta da plataforma Royal Bets Solutions (lib/royal.ts): SorteAgora. */
  | 'royal';

export interface House {
  id: string;
  name: string;
  domain: string;
  integration: HouseIntegration;
  /** Endereço da API, para as integrações que falam direto com a casa ('royal'). */
  apiBase?: string;
  /** false = fora do ar para os clientes (não aparece no login). */
  active: boolean;
}

export const HOUSES: House[] = [
  {
    id: 'sorteagora',
    name: 'SorteAgora',
    domain: 'sorteagora.co',
    integration: 'royal',
    apiBase: 'https://api.sorteagora.co',
    active: true,
  },
  // Inativas desde 24/11/2026. LotoGreen e Bateu: o site redireciona para
  // brasilsembets.gov.br. Esportiva: desativada a pedido (SorteAgora é a casa única).
  { id: 'lotogreen', name: 'LotoGreen', domain: 'lotogreen.bet.br', integration: 'auth-api', active: false },
  { id: 'esportiva', name: 'Esportiva', domain: 'esportiva.bet.br', integration: 'house-agent', active: false },
  { id: 'bateu', name: 'Bateu', domain: 'bateu.bet.br', integration: 'house-agent', active: false },
];

/** Casa pré-selecionada no login. Precisa estar ativa. */
export const DEFAULT_HOUSE = 'sorteagora';

/**
 * Casa dos registros criados antes do multicasa: sessões sem `house` e
 * documentos de app_users sem o campo. Todos eram da LotoGreen.
 */
export const LEGACY_HOUSE = 'lotogreen';

export function findHouse(id?: string | null): House | undefined {
  return HOUSES.find((h) => h.id === id);
}

export function isHouseActive(id?: string | null): boolean {
  return findHouse(id)?.active === true;
}

/** Casas que o cliente pode escolher no login. */
export function activeHouses(): House[] {
  return HOUSES.filter((h) => h.active);
}

export function houseName(id?: string | null): string {
  return findHouse(id)?.name ?? 'casa de apostas';
}

// 'browser' = a casa só abre jogo com login headless (house-agent), então a
// senha precisa ficar guardada. As demais falam por HTTP direto.
export function houseMode(id?: string | null): 'http' | 'browser' {
  return findHouse(id)?.integration === 'house-agent' ? 'browser' : 'http';
}
