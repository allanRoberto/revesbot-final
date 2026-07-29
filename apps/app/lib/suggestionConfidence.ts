import 'server-only';

// Confiança do sinal do ensemble — NÃO altera os números sugeridos.
// Calibrada no backtest de 05/07/2026 (backtest_suggestion_variants.py e
// backtest_suggestion_gate_sweep.py, na raiz do repo; 8000 gatilhos/mesa):
// quanto menor score9/score1 (ranking com degrau claro), maior o acerto exato
// em até 5 tentativas. Efeito forte na auto-roulette (+3pp), leve na immersive,
// nulo na brazilian naquela amostra — por isso os limiares são por mesa.
// Porte Python (worker de assertividade): apps/monitoring/scripts/suggestion_confidence.py

import {
  ENSEMBLE_WINDOWS,
  ensembleSuggestion,
  topSuggestion,
  type RankedNumber,
} from './suggestion';

// Tamanho do padrão sugerido/apostado. Histórico: 14 números cheios = 90,3–90,9%
// de acerto exato em até 5 tentativas (backtest_pattern_90.py e
// backtest_pnl_top14.py, 05/07/2026); com 9 era ~75%. Em 17/07/2026 voltou a 9
// para comparar em pé de igualdade com o motor de correlações (rota
// /suggestion-motor): mesmos critérios do HTML — 9 números, pagar em até 4
// tentativas.
export const SUGGESTION_COUNT = 9;

export type SignalStrength = 'forte' | 'medio' | 'fraco';

export interface SuggestionConfidence {
  // score do 9º colocado / score do 1º (0..1; menor = mais convicção).
  flat: number;
  // quantos dos 9 sugeridos aparecem por conta própria no top-8 de >=3 janelas.
  consensus: number;
  strength: SignalStrength;
}

export interface EnsembleWithConfidence {
  picks: RankedNumber[];
  confidence: SuggestionConfidence;
}

// flat <= forte → 'forte'; flat >= fraco → 'fraco'; entre os dois → 'medio'.
const LIMIAR_DEFAULT = { forte: 0.45, fraco: 0.6 };
const LIMIARES: Record<string, { forte: number; fraco: number }> = {
  'pragmatic-auto-roulette': { forte: 0.45, fraco: 0.6 },
};

/**
 * Mesmos 9 números do ensembleSuggestion (chama o original), acrescidos da
 * confiança do sinal. Use no lugar do ensembleSuggestion quando quiser exibir
 * ou registrar a força do sinal.
 */
export function ensembleSuggestionWithConfidence(
  numbersMostRecentFirst: number[],
  rouletteId?: string,
  windows: number[] = ENSEMBLE_WINDOWS,
  top: number = SUGGESTION_COUNT,
): EnsembleWithConfidence {
  const picks = ensembleSuggestion(numbersMostRecentFirst, windows, top);

  const valid = numbersMostRecentFirst.filter((x) => x >= 0 && x <= 36);
  const porJanela = windows.map((w) =>
    topSuggestion(valid.slice(0, w), 8).map((r) => r.num),
  );

  // A confiança segue calibrada sobre os 9 PRIMEIROS do ranking (definição do
  // backtest), independente de quantos números o padrão sugere.
  const base9 = picks.slice(0, 9);
  const flat =
    base9.length > 1 && base9[0].score > 0
      ? base9[base9.length - 1].score / base9[0].score
      : 0;
  const consensus = base9.filter(
    ({ num }) => porJanela.filter((p) => p.includes(num)).length >= 3,
  ).length;

  const lim = (rouletteId && LIMIARES[rouletteId]) || LIMIAR_DEFAULT;
  let strength: SignalStrength;
  if (picks.length === 0 || flat >= lim.fraco) strength = 'fraco';
  else if (flat <= lim.forte) strength = 'forte';
  else strength = 'medio';

  return { picks, confidence: { flat, consensus, strength } };
}
