// Lista curada das roletas disponíveis no app.
// gameId = id usado pela LotoGreen na rota /start-game/:gameId.

export interface RouletteGame {
  gameId: string;
  name: string;
  rouletteId: string;
}

export const ROULETTES: RouletteGame[] = [
  { gameId: '450', name: 'Brazilian Roulette', rouletteId: 'pragmatic-brazilian-roulette' },
  { gameId: '373', name: 'Auto Roulette', rouletteId: 'pragmatic-auto-roulette' },
  { gameId: '8261', name: 'Immersive Roulette Deluxe', rouletteId: 'pragmatic-immersive-roulette-deluxe' },
];

export function findRoulette(gameId: string): RouletteGame | undefined {
  return ROULETTES.find((g) => g.gameId === gameId);
}
