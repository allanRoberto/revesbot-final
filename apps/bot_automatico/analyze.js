// ==============================
// Análise de regiões na roda
// ==============================

// Roda europeia (zero único) no sentido horário:
const EURO_WHEEL = [
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6,
  27, 13, 36, 11, 30, 8, 23, 10, 5, 24,
  16, 33, 1, 20, 14, 31, 9, 22, 18, 29,
  7, 28, 12, 35, 3, 26
];

// Mapa: número -> índice na roda
const INDEX_BY_NUMBER = (() => {
  const map = new Map();
  EURO_WHEEL.forEach((num, idx) => map.set(num, idx));
  return map;
})();

/**
 * Distância em casas na roda (menor caminho circular).
 */
function wheelDistance(a, b) {
  const ia = INDEX_BY_NUMBER.get(a);
  const ib = INDEX_BY_NUMBER.get(b);
  if (ia === undefined || ib === undefined) return Infinity;

  const n = EURO_WHEEL.length;
  const diff = Math.abs(ia - ib);
  return Math.min(diff, n - diff);
}

/**
 * Retorna até k vizinhos de cada lado na roda para um número.
 * Ex.: neighbors(16, 2) -> [24, 33, 24, 33, 1, 20] dependendo de como quiser usar.
 */
function getNeighbors(num, k = 1) {
  const idx = INDEX_BY_NUMBER.get(num);
  if (idx === undefined) return [];

  const n = EURO_WHEEL.length;
  const result = [];

  for (let d = 1; d <= k; d++) {
    const left = (idx - d + n) % n;
    const right = (idx + d) % n;
    result.push(EURO_WHEEL[left], EURO_WHEEL[right]);
  }

  return Array.from(new Set(result)); // remove duplicados
}

/**
 * Kernel de distância: peso decresce conforme afasta do centro.
 * d = distância em casas na roda.
 */
function distanceKernel(d, radius) {
  if (d > radius) return 0;
  // Exponencial simples e suave
  const alpha = 0.7;
  return Math.exp(-alpha * d);
}

/**
 * Peso de recência para o i-ésimo elemento do histórico
 * (i = 0 mais recente, 1, 2, ...).
 */
function recencyWeight(i, lambda) {
  return Math.exp(-lambda * i);
}

/**
 * Computa o "heatmap" de região na roda com base no histórico.
 */
function computeHeatMap(history, opts) {
  const {
    windowSize,
    radius,
    lambdaRecency
  } = opts;

  const nWheel = EURO_WHEEL.length;
  const heat = new Array(nWheel).fill(0);

  const maxLen = Math.min(windowSize, history.length);

  for (let i = 0; i < maxLen; i++) {
    const num = history[i];
    if (!INDEX_BY_NUMBER.has(num)) continue;

    const wRec = recencyWeight(i, lambdaRecency);

    // espalha contribuição desse número em volta da roda
    for (let p = 0; p < nWheel; p++) {
      const centerNum = EURO_WHEEL[p];
      const d = wheelDistance(num, centerNum);
      if (d === Infinity) continue;

      const k = distanceKernel(d, radius);
      if (k <= 0) continue;

      heat[p] += wRec * k;
    }
  }

  return heat;
}

/**
 * Normaliza um array para [0, 1].
 */
function normalizeArray(arr) {
  const max = Math.max(...arr);
  if (max <= 0) return arr.map(() => 0);
  return arr.map(v => v / max);
}

/**
 * Detecta picos de calor na roda (centros de região).
 */
function detectRegionPeaks(normHeat, opts) {
  const { peakThreshold } = opts;
  const n = normHeat.length;
  const peaks = [];

  for (let i = 0; i < n; i++) {
    const v = normHeat[i];
    if (v < peakThreshold) continue;

    const left = normHeat[(i - 1 + n) % n];
    const right = normHeat[(i + 1) % n];

    // Pico local simples
    if (v >= left && v >= right) {
      peaks.push(i);
    }
  }

  return peaks;
}

/**
 * Monta regiões a partir dos picos.
 */
function buildRegionsFromPeaks(normHeat, peaks, opts) {
  const { regionHalfWidth } = opts;
  const n = EURO_WHEEL.length;
  const regions = [];

  peaks.forEach((peakIdx, regionId) => {
    const indices = [];
    for (let d = -regionHalfWidth; d <= regionHalfWidth; d++) {
      const idx = (peakIdx + d + n) % n;
      indices.push(idx);
    }

    const numbers = Array.from(new Set(indices.map(i => EURO_WHEEL[i])));
    const score = indices.reduce((acc, idx) => acc + normHeat[idx], 0);

    regions.push({
      id: regionId,
      centerIndex: peakIdx,
      center: EURO_WHEEL[peakIdx],
      indices,
      numbers,
      score,
      recentHits: 0,
      lastHitDist: null,
      membershipRatio: 0
    });
  });

  return regions;
}

/**
 * Associa cada número recente à região de maior score que o contém.
 */
function mapHistoryToRegions(history, regions, opts) {
  const { recentRegionWindow } = opts;

  const maxLen = Math.min(recentRegionWindow, history.length);
  const regionHits = new Map(); // regionId -> count

  regions.forEach(r => regionHits.set(r.id, 0));

  for (let i = 0; i < maxLen; i++) {
    const num = history[i];

    // regiões que incluem esse número
    const candidates = regions.filter(r => r.numbers.includes(num));
    if (!candidates.length) continue;

    // escolhe a região com maior score global
    candidates.sort((a, b) => b.score - a.score);
    const chosenId = candidates[0].id;

    regionHits.set(chosenId, (regionHits.get(chosenId) || 0) + 1);
  }

  // atualiza stats nas regiões
  regions.forEach(r => {
    const hits = regionHits.get(r.id) || 0;
    r.recentHits = hits;
    r.membershipRatio = maxLen > 0 ? hits / maxLen : 0;
  });
}

/**
 * Calcula distância do último número até o centro de cada região.
 */
function computeLastHitDistance(history, regions) {
  if (!history.length) return;
  const last = history[0];

  regions.forEach(r => {
    r.lastHitDist = wheelDistance(last, r.center);
  });
}

/**
 * Classifica padrão geral de comportamento das regiões:
 *  - "single": praticamente só 1 região domina
 *  - "binary": 2 regiões relevantes
 *  - "triangular": 3 regiões relevantes
 *  - "mixed": caso geral
 */
function classifyRegionPattern(regions) {
  const sorted = [...regions].sort((a, b) => b.membershipRatio - a.membershipRatio);
  const top = sorted.filter(r => r.membershipRatio > 0);

  if (!top.length) return { pattern: "none", activeRegions: [] };

  const strong = top.filter(r => r.membershipRatio >= 0.4);
  const mid = top.filter(r => r.membershipRatio >= 0.25);

  if (strong.length === 1) {
    return { pattern: "single", activeRegions: [strong[0].id] };
  }

  if (mid.length === 2) {
    return { pattern: "binary", activeRegions: mid.map(r => r.id) };
  }

  if (mid.length >= 3) {
    return { pattern: "triangular", activeRegions: mid.map(r => r.id) };
  }

  return { pattern: "mixed", activeRegions: top.map(r => r.id) };
}

/**
 * Pega a região recomendada (região "de trabalho"):
 * leva em conta score, membershipRatio e proximidade ao último número.
 */
function pickMainRegion(history, regions) {
  if (!history.length || !regions.length) return null;
  const last = history[0];

  let best = null;
  let bestScore = -Infinity;

  regions.forEach(r => {
    const dist = r.lastHitDist != null ? r.lastHitDist : wheelDistance(last, r.center);
    const closeness = dist > 0 ? 1 / (dist + 0.5) : 2.0; // maior se estiver colado / dentro
    const composite = r.score * 0.5 + r.membershipRatio * 0.4 + closeness * 0.1;

    if (composite > bestScore) {
      bestScore = composite;
      best = r;
    }
  });

  return best;
}

/**
 * Monta sugestão de números da região principal:
 * - núcleo compacto (centro ±1)
 * - região estendida (toda a região)
 */
function buildRegionRecommendation(mainRegion, coreRadius = 1) {
  if (!mainRegion) {
    return {
      mainRegionId: null,
      coreNumbers: [],
      extendedNumbers: []
    };
  }

  const coreNumbers = Array.from(
    new Set([
      mainRegion.center,
      ...getNeighbors(mainRegion.center, coreRadius)
    ])
  );

  return {
    mainRegionId: mainRegion.id,
    coreNumbers,
    extendedNumbers: mainRegion.numbers
  };
}

/**
 * Função principal:
 *  - history: array de números, MAIS RECENTE no índice 0.
 *  - options: configurações finas (tudo opcional).
 */
function analyzeWheelRegions(history, options = {}) {
  const opts = {
    windowSize: options.windowSize ?? 40,          // quantos giros considerar
    radius: options.radius ?? 4,                   // raio em casas pro heatmap
    lambdaRecency: options.lambdaRecency ?? 0.08,  // decaimento de recência
    peakThreshold: options.peakThreshold ?? 0.35,  // limiar p/ pico de região
    regionHalfWidth: options.regionHalfWidth ?? 2, // largura da região (centro ± N)
    recentRegionWindow: options.recentRegionWindow ?? 20 // janela p/ padrão de regiões
  };

  if (!Array.isArray(history) || history.length === 0) {
    return {
      regions: [],
      pattern: "none",
      lastNumber: null,
      recommended: {
        mainRegionId: null,
        coreNumbers: [],
        extendedNumbers: []
      }
    };
  }

  // 1) Mapa de calor de região
  const heat = computeHeatMap(history, opts);
  const normHeat = normalizeArray(heat);

  // 2) Detectar picos (centros de região)
  const peaks = detectRegionPeaks(normHeat, opts);
  if (!peaks.length) {
    return {
      regions: [],
      pattern: "none",
      lastNumber: history[0],
      recommended: {
        mainRegionId: null,
        coreNumbers: [],
        extendedNumbers: []
      }
    };
  }

  // 3) Construir regiões
  const regions = buildRegionsFromPeaks(normHeat, peaks, opts);

  // 4) Estatísticas de hits recentes por região
  mapHistoryToRegions(history, regions, opts);

  // 5) Distância do último número ao centro de cada região
  computeLastHitDistance(history, regions);

  // 6) Classificar padrão (single / binary / triangular / mixed)
  const patternInfo = classifyRegionPattern(regions);

  // 7) Escolher região principal (de trabalho)
  const mainRegion = pickMainRegion(history, regions);

  // 8) Sugestão de números dessa região
  const recommendation = buildRegionRecommendation(mainRegion, 3);

  return {
    regions: regions
      .map(r => ({
        id: r.id,
        center: r.center,
        numbers: r.numbers,
        score: r.score,
        recentHits: r.recentHits,
        lastHitDist: r.lastHitDist,
        membershipRatio: r.membershipRatio
      }))
      .sort((a, b) => b.score - a.score), // ordena por calor global
    pattern: patternInfo.pattern,
    activeRegions: patternInfo.activeRegions,
    lastNumber: history[0],
    recommended: recommendation
  };
}

// Export se estiver usando Node/CommonJS
module.exports = { analyzeWheelRegions };