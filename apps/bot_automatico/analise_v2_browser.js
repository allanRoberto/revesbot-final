// analyze_v2_browser.js

(function (global) {
  // analyzeWheelRegionsV2.js
// Leitura comportamental da mesa em cima da roda física da roleta europeia

// Ordem oficial da roleta europeia (único zero), no sentido horário
const WHEEL = [
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34,
  6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
  24, 16, 33, 1, 20, 14, 31, 9, 22, 18,
  29, 7, 28, 12, 35, 3, 26
];

const SIZE = WHEEL.length;
const INDEX = new Map(WHEEL.map((n, i) => [n, i]));

/**
 * Distância circular mínima entre dois índices na roda
 */
function circularDist(i, j) {
  const diff = Math.abs(i - j);
  return Math.min(diff, SIZE - diff);
}

/**
 * Clampa valor para [min, max]
 */
function clamp(value, min = 0, max = 1) {
  return Math.max(min, Math.min(max, value));
}

/**
 * Converte histórico de números para índices da roda (mais recente primeiro)
 */
function historyToIndices(history) {
  return history
    .map((n) => INDEX.get(n))
    .filter((i) => i !== undefined);
}

/**
 * Calcula densidade local em cada posição da roda,
 * contando quantas vezes o histórico caiu num raio R em torno da posição.
 */
function computeDensity(idxHist, radius) {
  const density = new Array(SIZE).fill(0);

  for (const idx of idxHist) {
    for (let offset = -radius; offset <= radius; offset++) {
      const pos = (idx + offset + SIZE) % SIZE;
      density[pos] += 1;
    }
  }

  return density;
}

/**
 * Encontra picos de densidade (máximos locais),
 * garantindo que não fiquem colados (separação mínima).
 */
function findPeaks(density, maxPeaks = 3, minSeparation = 3) {
  const indices = [...density.keys()];

  // ordena por densidade desc
  indices.sort((a, b) => density[b] - density[a]);

  const peaks = [];

  for (const idx of indices) {
    if (density[idx] === 0) break; // nada relevante após zeros

    // evita pegar pico muito perto de outro já escolhido
    const tooClose = peaks.some(
      (p) => circularDist(p.index, idx) < minSeparation
    );
    if (tooClose) continue;

    peaks.push({
      index: idx,
      number: WHEEL[idx],
      density: density[idx]
    });

    if (peaks.length >= maxPeaks) break;
  }

  return peaks;
}

/**
 * Constrói a região (lista de números) em torno de um pico (index) com raio R
 */
function buildRegion(index, radius) {
  const region = [];
  for (let offset = -radius; offset <= radius; offset++) {
    const pos = (index + offset + SIZE) % SIZE;
    region.push(WHEEL[pos]);
  }
  return region;
}

/**
 * Calcula concentração, dominância e estabilidade temporal.
 */
function computeBehaviorScores(idxHist, radius) {
  if (!idxHist.length) {
    return {
      concentrationScore: 0,
      dominanceScore: 0,
      stabilityScore: 0,
      density: new Array(SIZE).fill(0),
      peaks: []
    };
  }

  // densidade global (histórico completo)
  const density = computeDensity(idxHist, radius);
  const peaks = findPeaks(density, 3, radius + 1);

  const totalHits = idxHist.length;
  const windowSpan = radius * 2 + 1;
  const avgDensity = (totalHits * windowSpan) / SIZE;
  const maxDensity = peaks.length ? peaks[0].density : 0;

  // 1) Concentração (quão acima da média está o maior pico)
  let concentrationScore = 0;
  if (avgDensity > 0 && maxDensity > 0) {
    const ratio = maxDensity / avgDensity; // 1 ~ aleatório, >1 concentrado
    // se ratio = 1 -> 0; ratio = 1.5 -> 1
    concentrationScore = clamp((ratio - 1.0) / 0.5, 0, 1);
  }

  // 2) Dominância entre picos
  let dominanceScore = 0;
  if (peaks.length >= 2) {
    const p1 = peaks[0].density;
    const p2 = peaks[1].density;
    if (p1 > 0) {
      const dominance = (p1 - p2) / p1; // 0 => iguais; 1 => só o primeiro importa
      // dominance 0 -> 0; dominance 0.4 -> 1
      dominanceScore = clamp(dominance / 0.4, 0, 1);
    }
  } else if (peaks.length === 1) {
    // só um pico relevante: dominância máxima
    dominanceScore = 1;
  }

  // 3) Estabilidade temporal: compara pico principal da metade antiga vs recente
  let stabilityScore = 0;
  if (idxHist.length >= 10) {
    const mid = Math.floor(idxHist.length / 2);
    const early = idxHist.slice(mid); // mais antigos
    const recent = idxHist.slice(0, mid); // mais recentes (assumindo history mais recente primeiro)

    const densityEarly = computeDensity(early, radius);
    const densityRecent = computeDensity(recent, radius);

    const peaksEarly = findPeaks(densityEarly, 1, radius + 1);
    const peaksRecent = findPeaks(densityRecent, 1, radius + 1);

    if (peaksEarly.length && peaksRecent.length) {
      const iE = peaksEarly[0].index;
      const iR = peaksRecent[0].index;
      const d = circularDist(iE, iR);

      // se d = 0 → 1.0; se d ~ SIZE/4 (bem longe) → ~0
      const norm = d / (SIZE / 4);
      stabilityScore = clamp(1 - norm, 0, 1);
    }
  }

  return {
    concentrationScore,
    dominanceScore,
    stabilityScore,
    density,
    peaks
  };
}

/**
 * Analisa regiões da roleta com v2 (com clareza e classificação de regime).
 *
 * @param {number[]} history - Lista de números (mais recente em history[0]).
 * @param {Object} [options]
 * @param {number} [options.windowSize=50] - Quantidade máxima de giros a olhar.
 * @param {number} [options.radius=2] - Raio em casas da roda para compor cada região.
 *
 * @returns {{
 *   clarity: number,
 *   pattern: "chaotic" | "focused" | "binary" | "triangular",
 *   coreNumbers: number[],
 *   extendedNumbers: number[],
 *   diagnostics: {
 *     concentrationScore: number,
 *     dominanceScore: number,
 *     stabilityScore: number,
 *     density: number[],
 *     peaks: { index: number, number: number, density: number }[],
 *     peakRatios: { rel2: number, rel3: number }
 *   }
 * }}
 */
function analyzeWheelRegionsV2(history, options = {}) {
  const {
    windowSize = 50,
    radius = 2
  } = options;

  if (!Array.isArray(history) || history.length === 0) {
    return {
      clarity: 0,
      pattern: "chaotic",
      coreNumbers: [],
      extendedNumbers: [],
      diagnostics: {
        concentrationScore: 0,
        dominanceScore: 0,
        stabilityScore: 0,
        density: new Array(SIZE).fill(0),
        peaks: [],
        peakRatios: { rel2: 0, rel3: 0 }
      }
    };
  }

  const slice = history.slice(0, windowSize);
  const idxHist = historyToIndices(slice);
  if (!idxHist.length) {
    return {
      clarity: 0,
      pattern: "chaotic",
      coreNumbers: [],
      extendedNumbers: [],
      diagnostics: {
        concentrationScore: 0,
        dominanceScore: 0,
        stabilityScore: 0,
        density: new Array(SIZE).fill(0),
        peaks: [],
        peakRatios: { rel2: 0, rel3: 0 }
      }
    };
  }

  const {
    concentrationScore,
    dominanceScore,
    stabilityScore,
    density,
    peaks
  } = computeBehaviorScores(idxHist, radius);

  // clareza global do comportamento
  const clarity =
    0.4 * concentrationScore +
    0.3 * dominanceScore +
    0.3 * stabilityScore;

  // Se não tiver pico relevante, é caótico
  if (!peaks.length || clarity < 0.35) {
    return {
      clarity,
      pattern: "chaotic",
      coreNumbers: [],
      extendedNumbers: [],
      diagnostics: {
        concentrationScore,
        dominanceScore,
        stabilityScore,
        density,
        peaks,
        peakRatios: { rel2: 0, rel3: 0 }
      }
    };
  }

  // Relação entre densidades dos 3 picos
  const p1 = peaks[0]?.density ?? 0;
  const p2 = peaks[1]?.density ?? 0;
  const p3 = peaks[2]?.density ?? 0;

  const rel2 = p1 > 0 ? p2 / p1 : 0;
  const rel3 = p1 > 0 ? p3 / p1 : 0;

  // Classificação do regime
  let pattern;
  if (rel2 < 0.5) {
    // um pico claramente dominante
    pattern = "focused";
  } else if (rel2 >= 0.5 && rel3 < 0.4) {
    // dois picos fortes, terceiro bem menor
    pattern = "binary";
  } else {
    // três picos relevantes
    pattern = "triangular";
  }

  // Construir core / extended de acordo com o padrão
  let coreSet = new Set();
  let extSet = new Set();

  if (pattern === "focused") {
    const main = peaks[0];
    const mainRegion = buildRegion(main.index, radius);
    coreSet = new Set(mainRegion);

    if (peaks[1]) {
      const secRegion = buildRegion(peaks[1].index, radius);
      secRegion.forEach((n) => extSet.add(n));
    }

    // extended um pouco maior em torno do pico principal
    const extendedAroundMain = buildRegion(main.index, radius + 1);
    extendedAroundMain.forEach((n) => extSet.add(n));
  } else if (pattern === "binary") {
    const region1 = buildRegion(peaks[0].index, radius);
    const region2 = buildRegion(peaks[1].index, radius);

    region1.forEach((n) => coreSet.add(n));
    region2.forEach((n) => coreSet.add(n));

    if (peaks[2]) {
      const region3 = buildRegion(peaks[2].index, radius);
      region3.forEach((n) => extSet.add(n));
    }
  } else {
    // triangular: três regiões relevantes
    peaks.forEach((p) => {
      const region = buildRegion(p.index, radius);
      region.forEach((n) => coreSet.add(n));
    });
  }

  // limpa interseção: tudo que está em core não precisa estar repetido em extended
  for (const n of coreSet) {
    if (extSet.has(n)) extSet.delete(n);
  }

  const coreNumbers = Array.from(coreSet);
  const extendedNumbers = Array.from(extSet);

  // Ordenar por posição na roda para ficar visualmente coerente
  coreNumbers.sort((a, b) => INDEX.get(a) - INDEX.get(b));
  extendedNumbers.sort((a, b) => INDEX.get(a) - INDEX.get(b));

  return {
    clarity: Number(clarity.toFixed(3)),
    pattern,
    coreNumbers,
    extendedNumbers,
    diagnostics: {
      concentrationScore: Number(concentrationScore.toFixed(3)),
      dominanceScore: Number(dominanceScore.toFixed(3)),
      stabilityScore: Number(stabilityScore.toFixed(3)),
      density,
      peaks,
      peakRatios: {
        rel2: Number(rel2.toFixed(3)),
        rel3: Number(rel3.toFixed(3))
      }
    }
  };
}

  // 🔹 expõe no escopo global do browser
  global.analyzeWheelRegionsV2 = analyzeWheelRegionsV2;
})(window);