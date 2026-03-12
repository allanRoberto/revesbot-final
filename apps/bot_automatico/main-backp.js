// test_regions_gales.js
// Avalia a assertividade da analyzeWheelRegionsV2 com GALES
// - Hit na 1ª tentativa
// - Hit em até 2 tentativas
// - Hit em até 3 tentativas, etc.

const { analyzeWheelRegionsV2 } = require("./analyze_v2");

const HISTORY_URL = "https://api.revesbot.com.br/history/pragmatic-brazilian-roulette?limit=20000";

const WINDOW_SIZE = 10;   // quantos giros usar como contexto da leitura comportamental
const RADIUS = 1;         // raio das regiões na roda
const MAX_SPINS = 20000;    // giros usados no teste
const MAX_GALES = 20;      // total de tentativas (1 = sem gale, 2 = 1 gale, 3 = 2 gales)

async function fetchHistory() {
  const res = await fetch(HISTORY_URL);
  if (!res.ok) {
    throw new Error(`Erro ao buscar history: ${res.status} ${res.statusText}`);
  }
  const results = await res.json();


  data = results["results"]
  let numbers;

  // Formatos possíveis:
  // [n, n, n]  ou  [{ value: n }, ...]  ou  [{ numero: n }, ...]
  if (Array.isArray(data) && typeof data[0] === "number") {
    numbers = data;
  } else if (Array.isArray(data) && typeof data[0] === "object" && data[0] !== null) {
    if ("value" in data[0]) {
      numbers = data.map((d) => d.value);
    } else if ("numero" in data[0]) {
      numbers = data.map((d) => d.numero);
    } else {
      throw new Error("Formato inesperado de history (objetos sem campo value/numero).");
    }
  } else {
    throw new Error("Formato inesperado de history.");
  }

  if (!numbers.length) {
    throw new Error("History vazio.");
  }

  return numbers;
}

function evaluateHistoryWithGales(history, options = {}) {
    const windowSize = options.windowSize ?? WINDOW_SIZE;
    const radius = options.radius ?? RADIUS;
    const maxGales = options.maxGales ?? MAX_GALES;
    const clarityThreshold = 0.9;
  
    const chrono = [...history].reverse(); // mais antigo -> mais recente
  
    const limit = Math.min(chrono.length, MAX_SPINS);
    if (limit <= windowSize + maxGales) {
      throw new Error(
        `Poucos giros para teste: ${limit}. Precisamos de > WINDOW_SIZE + MAX_GALES.`
      );
    }
  
    let total = 0;           // total de previsões *consideradas*
    let skippedClarity = 0;  // quantas previsões foram descartadas por baixa clareza
    let sumClarity = 0;
  
    const hitsCoreAtMost = Array(maxGales + 1).fill(0);
    const hitsCoreExtAtMost = Array(maxGales + 1).fill(0);
  
    const perPattern = {};
  
    for (let t0 = windowSize; t0 < limit - maxGales; t0++) {
      const pastChrono = chrono.slice(t0 - windowSize, t0);
      const pastForFn = [...pastChrono].reverse(); // recente em index 0
  
      const analysis = analyzeWheelRegionsV2(pastForFn, {
        windowSize,
        radius,
      });
  
      const clarity = analysis.clarity ?? 0;
  
      // ⚠️ Filtro de clareza: se abaixo do threshold, pula esse caso
      if (clarity < clarityThreshold) {
        skippedClarity++;
        continue;
      }
  
      const pattern = analysis.pattern || "chaotic";
      if (!perPattern[pattern]) {
        perPattern[pattern] = {
          total: 0,
          hitsCoreAtMost: Array(maxGales + 1).fill(0),
          hitsCoreExtAtMost: Array(maxGales + 1).fill(0),
        };
      }
  
      const core = analysis.coreNumbers || [];
      const ext = analysis.extendedNumbers || [];
  
      const nextNumbers = [];
      for (let g = 0; g < maxGales; g++) {
        const idx = t0 + g;
        if (idx >= limit) break;
        nextNumbers.push(chrono[idx]);
      }
  
      let firstCoreAttempt = null;
      let firstCoreExtAttempt = null;
  
      nextNumbers.forEach((n, i) => {
        const attempt = i + 1;
        if (firstCoreAttempt === null && core.includes(n)) {
          firstCoreAttempt = attempt;
        }
        if (
          firstCoreExtAttempt === null &&
          (core.includes(n) || ext.includes(n))
        ) {
          firstCoreExtAttempt = attempt;
        }
      });
  
      total++;
      perPattern[pattern].total++;
      sumClarity += clarity;
  
      for (let g = 1; g <= maxGales; g++) {
        if (firstCoreAttempt !== null && firstCoreAttempt <= g) {
          hitsCoreAtMost[g]++;
          perPattern[pattern].hitsCoreAtMost[g]++;
        }
        if (firstCoreExtAttempt !== null && firstCoreExtAttempt <= g) {
          hitsCoreExtAtMost[g]++;
          perPattern[pattern].hitsCoreExtAtMost[g]++;
        }
      }
    }
  
    console.log("===== Avaliação regions V2 com GALES + filtro de clareza =====");
    console.log(`Clarity threshold: ${clarityThreshold}`);
    console.log(`Previsões consideradas: ${total}`);
    console.log(`Previsões descartadas por baixa clareza: ${skippedClarity}`);
    console.log("");
  
    if (total === 0) {
      console.log("Nenhuma previsão passou o filtro de clareza. Ajuste o threshold.");
      return;
    }
  
    for (let g = 1; g <= maxGales; g++) {
      const pctCore = (hitsCoreAtMost[g] / total) * 100;
      const pctCoreExt = (hitsCoreExtAtMost[g] / total) * 100;
      console.log(
        `Em até ${g} tentativa(s): CORE=${pctCore.toFixed(
          2
        )}% | CORE+EXT=${pctCoreExt.toFixed(2)}%`
      );
    }
  
    const avgClarity = sumClarity / total;
    console.log("");
    console.log(`Clareza média (apenas casos considerados): ${avgClarity.toFixed(3)}`);
    console.log("");
  
    console.log("Por padrão de comportamento (após filtro de clareza):");
    for (const [pat, stats] of Object.entries(perPattern)) {
      if (!stats.total) continue;
      console.log(`- ${pat}: total=${stats.total}`);
      for (let g = 1; g <= maxGales; g++) {
        const pCore = (stats.hitsCoreAtMost[g] / stats.total) * 100;
        const pCoreExt =
          (stats.hitsCoreExtAtMost[g] / stats.total) * 100;
        console.log(
          `    até ${g} tentativa(s): CORE=${pCore.toFixed(
            2
          )}% | CORE+EXT=${pCoreExt.toFixed(2)}%`
        );
      }
    }
  }

(async () => {
  try {
    const history = await fetchHistory();
    console.log(`History bruto recebido: ${history.length} giros.`);
    const slice = history.slice(0, MAX_SPINS); // primeiros = mais recentes
    console.log(`Usando ${slice.length} giros mais recentes para avaliação.`);
    evaluateHistoryWithGales(slice);
  } catch (err) {
    console.error("Erro na avaliação:", err);
  }
})();