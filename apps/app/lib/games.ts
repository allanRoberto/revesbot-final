// Lista curada das roletas disponíveis no app.
// gameId = id da mesa no app (/play/:gameId). É o id numérico da LotoGreen,
// que as casas 'auth-api' usam direto na rota /start-game/:gameId.

import { HOUSES, findHouse } from './houses';

export interface RouletteGame {
  gameId: string;
  name: string;
  rouletteId: string;
  // Como cada casa identifica a mesa quando não é pelo gameId numérico:
  // - 'house-agent' (Esportiva, Bateu): slug do start-game-v2;
  // - 'royal' (SorteAgora): '<provedor>/<jogo>' do /game/get-game.
  slugs?: Record<string, string>;
}

export const ROULETTES: RouletteGame[] = [
  {
    gameId: '450',
    name: 'Brazilian Roulette',
    rouletteId: 'pragmatic-brazilian-roulette',
    slugs: {
      sorteagora: 'pragmatic-live/brazilian-roulette',
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

/** Identificador da mesa numa casa que não usa o gameId numérico (ou undefined). */
export function gameSlug(game: RouletteGame, house: string): string | undefined {
  return game.slugs?.[house];
}

// Uma mesa está disponível numa casa se: casa 'auth-api' (a LotoGreen abre
// qualquer mesa pelo gameId) OU casa com slug mapeado para aquela mesa.
export function isGameAvailable(game: RouletteGame, house: string): boolean {
  if (findHouse(house)?.integration === 'auth-api') return true;
  return !!gameSlug(game, house);
}

/** Casas ATIVAS que oferecem esta mesa (para o badge de indisponível). */
export function availableHouseNames(game: RouletteGame): string[] {
  return HOUSES.filter((h) => h.active && isGameAvailable(game, h.id)).map((h) => h.name);
}

/** Texto para mesa indisponível na casa do usuário. */
export function unavailableNote(game: RouletteGame): string {
  const names = availableHouseNames(game);
  return names.length > 0 ? `Disponível apenas em: ${names.join(', ')}` : 'Indisponível no momento';
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
