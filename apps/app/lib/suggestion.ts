import 'server-only';

// ALGORITMO PROPRIETÁRIO — "Pendências de Pagamento / Análise de Pivôs".
// Roda SOMENTE no servidor (import 'server-only' impede uso no cliente).
// Portado da lógica de referência; não expor este arquivo ao front-end.

// ===== Roleta europeia =====
const WHEEL = [
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24,
  16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
];
const POS: Record<number, number> = {};
WHEEL.forEach((n, i) => (POS[n] = i));

export interface SuggestionConfig {
  raio: number;
  janela: number;
  ruido: number;
  decay: 'none' | 'linear' | 'inverse';
  direto: boolean;
  vizinho: boolean;
  espelho: boolean;
  soma: boolean;
  seq: boolean;
}

// Parâmetros default (iguais aos do arquivo de referência).
export const DEFAULT_CONFIG: SuggestionConfig = {
  raio: 2,
  janela: 5,
  ruido: 3,
  decay: 'linear',
  direto: true,
  vizinho: true,
  espelho: true,
  soma: true,
  seq: true,
};

// ===== Camuflagens =====
function vizinhosRoda(x: number): number[] {
  const i = POS[x];
  return [WHEEL[(i + 36) % 37], WHEEL[(i + 1) % 37]];
}
function espelho(x: number): number[] {
  const s = String(x);
  if (s.length === 2 && s[0] !== s[1]) {
    const m = parseInt(s.split('').reverse().join(''));
    if (m >= 0 && m <= 36 && m !== x) return [m];
  }
  return [];
}
function somaDig(x: number): number[] {
  if (x >= 10) {
    const s = String(x)
      .split('')
      .reduce((a, b) => a + +b, 0);
    if (s !== x) return [s];
  }
  return [];
}
function seq(x: number): number[] {
  return [x - 1, x + 1].filter((y) => y >= 0 && y <= 36);
}

function formasDePagar(x: number, cfg: SuggestionConfig): Set<number> {
  const s = new Set<number>();
  if (cfg.direto) s.add(x);
  if (cfg.vizinho) vizinhosRoda(x).forEach((v) => s.add(v));
  if (cfg.espelho) espelho(x).forEach((v) => s.add(v));
  if (cfg.soma) somaDig(x).forEach((v) => s.add(v));
  if (cfg.seq) seq(x).forEach((v) => s.add(v));
  if (s.size === 0) s.add(x);
  return s;
}

export interface RankedNumber {
  num: number;
  score: number;
}

// ===== Núcleo da análise =====
// listaReversa: números com o MAIS RECENTE primeiro (mesmo formato da tela).
function analisar(listaReversa: number[], cfg: SuggestionConfig): RankedNumber[] {
  const crono = [...listaReversa].reverse();
  const n = crono.length;
  const pivos = crono.slice(-5).reverse();
  const pesosPivo = [5, 4, 3, 2, 1];

  const occ: Record<number, number[]> = {};
  crono.forEach((x, i) => {
    (occ[x] = occ[x] || []).push(i);
  });

  const score = new Float64Array(37);
  const contribuicoes: number[][] = Array.from({ length: 37 }, () => []);

  pivos.forEach((pivo, k) => {
    const wPivo = pesosPivo[k];
    const idxs = occ[pivo] || [];
    const pendencias = new Map<number, { dividas: number[] }>();

    idxs.forEach((idx) => {
      const ini = Math.max(0, idx - cfg.raio);
      const fim = Math.min(n - 1, idx + cfg.raio);
      for (let j = ini; j <= fim; j++) {
        if (j === idx) continue;
        const alvo = crono[j];
        const pagadores = formasDePagar(alvo, cfg);
        let pago = false;
        const fimJ = Math.min(n - 1, idx + cfg.janela);
        for (let t = idx + 1; t <= fimJ; t++) {
          if (t === j) continue;
          if (pagadores.has(crono[t])) {
            pago = true;
            break;
          }
        }
        if (!pago) {
          const idade = n - 1 - idx;
          if (!pendencias.has(alvo)) pendencias.set(alvo, { dividas: [] });
          pendencias.get(alvo)!.dividas.push(idade);
        }
      }
    });

    pendencias.forEach((info, num) => {
      info.dividas.forEach((idade) => {
        let wIdade = 1;
        if (cfg.decay === 'linear') wIdade = Math.max(0.15, 1 - idade / n);
        else if (cfg.decay === 'inverse') wIdade = Math.min(3, 1 + idade / (n / 2));
        score[num] += wPivo * wIdade;
        contribuicoes[num].push(pivo);
      });
    });
  });

  // filtro de ruído: amortecer quem acabou de sair
  if (cfg.ruido > 0) {
    const recentes = new Set(crono.slice(-cfg.ruido));
    recentes.forEach((num) => {
      score[num] *= 0.35;
    });
  }

  return [...Array(37).keys()]
    .map((num) => ({ num, score: score[num] }))
    .filter((r) => r.score > 0)
    .sort((a, b) => b.score - a.score);
}

/**
 * Recebe os números com o mais recente primeiro e devolve os TOP `top`
 * candidatos (default 8) usando os parâmetros padrão.
 */
export function topSuggestion(
  numbersMostRecentFirst: number[],
  top = 8,
  cfg: SuggestionConfig = DEFAULT_CONFIG,
): RankedNumber[] {
  const valid = numbersMostRecentFirst.filter((x) => x >= 0 && x <= 36);
  if (valid.length < 30) return [];
  return analisar(valid, cfg).slice(0, top);
}
