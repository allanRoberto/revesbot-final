// Lista curada das roletas disponíveis no app.
// gameId = id usado pela LotoGreen na rota /start-game/:gameId.

import { HOUSES, houseMode } from './houses';

export interface RouletteGame {
  gameId: string;
  name: string;
  rouletteId: string;
  // Slug do jogo por casa do modo navegador (ex.: esportiva). Casas 'http'
  // (LotoGreen) usam o gameId numérico e não precisam de slug.
  slugs?: Record<string, string>;
}

export const ROULETTES: RouletteGame[] = [
  {
    gameId: '450',
    name: 'Brazilian Roulette',
    rouletteId: 'pragmatic-brazilian-roulette',
    slugs: {
      esportiva: 'pragmaticplay/roleta-brasileira',
      bateu: 'pragmaticplay/roleta-brasileira',
    },
  },
  { gameId: '373', name: 'Auto Roulette', rouletteId: 'pragmatic-auto-roulette' },
  { gameId: '8261', name: 'Immersive Roulette Deluxe', rouletteId: 'pragmatic-immersive-roulette-deluxe' },
];

export function findRoulette(gameId: string): RouletteGame | undefined {
  return ROULETTES.find((g) => g.gameId === gameId);
}

/** Slug do jogo para uma casa do modo navegador (ou undefined se não mapeado). */
export function gameSlug(game: RouletteGame, house: string): string | undefined {
  return game.slugs?.[house];
}

// Uma mesa está disponível numa casa se: casa 'http' (LotoGreen tem todas) OU
// casa 'browser' com slug mapeado para aquela mesa.
export function isGameAvailable(game: RouletteGame, house: string): boolean {
  if (houseMode(house) === 'http') return true;
  return !!gameSlug(game, house);
}

/** Nomes das casas que oferecem esta mesa (para o badge de indisponível). */
export function availableHouseNames(game: RouletteGame): string[] {
  return HOUSES.filter((h) => isGameAvailable(game, h.id)).map((h) => h.name);
}

// ===== Jogos de cassino (não-roleta) — abrem em NOVA ABA na conta do usuário,
// pois não têm mesa ao vivo/overlay próprio. gameId = id da LotoGreen. =====
export interface CasinoGame {
  gameId: string;
  name: string;
  provider: string;
}

export const CASINO_GAMES: CasinoGame[] = [
  { gameId: '3836', name: 'Mines', provider: 'Spribe' },
];

export function findCasinoGame(gameId: string): CasinoGame | undefined {
  return CASINO_GAMES.find((g) => g.gameId === gameId);
}
