// Clockwise order of the European wheel; left moves toward decreasing indices.
export const WHEEL = Object.freeze([
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
  5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
]);

const wheelPositions = new Map(WHEEL.map((number, index) => [number, index]));
const wheelAt = (index) => WHEEL[((index % WHEEL.length) + WHEEL.length) % WHEEL.length];
const validNumber = (value) => Number.isInteger(value) && value >= 0 && value <= 36;
const itemId = (item) => item?._id ?? item?.id ?? item?.external_game_id ?? null;
const numericOrder = (left, right) => left - right;
const sectorWeights = Object.freeze([0.3, 0.7, 1, 0.7, 0.3]);

function initialAnalysis(index) {
  return {
    status: "invalid",
    message: "",
    selectedId: null,
    selectedIndex: Number.isInteger(index) ? index : null,
    previousId: null,
    previousIndex: null,
    offsetId: null,
    offsetIndex: null,
    base: null,
    offset: null,
    leftCenter: null,
    rightCenter: null,
    left: [],
    right: [],
    bet: [],
    leftWeighted: [],
    rightWeighted: [],
    betWeighted: [],
    leftPath: [],
    rightPath: [],
  };
}

function sector(centerIndex) {
  return [-2, -1, 0, 1, 2].map((delta) => wheelAt(centerIndex + delta));
}

function weightedSector(numbers) {
  return numbers.map((number, index) => ({ number, weight: sectorWeights[index] }));
}

function mergeWeightedSectors(left, right) {
  const weights = new Map();
  for (const { number, weight } of [...left, ...right]) {
    weights.set(number, Math.max(weights.get(number) || 0, weight));
  }
  return [...weights.entries()]
    .map(([number, weight]) => ({ number, weight }))
    .sort((leftEntry, rightEntry) => leftEntry.number - rightEntry.number);
}

/**
 * Analyze one selected occurrence in a newest-first history of { value, _id? }.
 * The first older occurrence supplies the pair: its immediately newer result is
 * the offset. Paths include the base (step 0) and end at the respective center.
 * Values must already be integers from 0 through 36; invalid data is not coerced.
 */
export function analyzeSelection(items, index) {
  const analysis = initialAnalysis(index);
  if (!Array.isArray(items)) {
    analysis.message = "O histórico deve ser uma lista de resultados.";
    return analysis;
  }
  if (!Number.isInteger(index) || index < 0 || index >= items.length) {
    analysis.message = "A ocorrência selecionada não existe no histórico.";
    return analysis;
  }

  const base = items[index]?.value;
  analysis.selectedId = itemId(items[index]);
  if (!validNumber(base)) {
    analysis.message = "O resultado selecionado deve ser um número inteiro entre 0 e 36.";
    return analysis;
  }
  analysis.base = base;

  let previousIndex = null;
  for (let candidate = index + 1; candidate < items.length; candidate += 1) {
    const value = items[candidate]?.value;
    if (!validNumber(value)) {
      analysis.message = `O resultado na posição ${candidate + 1} é inválido.`;
      return analysis;
    }
    if (value === base) {
      previousIndex = candidate;
      break;
    }
  }
  if (previousIndex === null) {
    analysis.status = "no_previous";
    analysis.message = "Não há ocorrência anterior deste número nos resultados carregados.";
    return analysis;
  }

  const offsetIndex = previousIndex - 1;
  const offset = items[offsetIndex].value;
  const basePosition = wheelPositions.get(base);
  const leftIndex = basePosition - offset;
  const rightIndex = basePosition + offset;
  const left = sector(leftIndex);
  const right = sector(rightIndex);
  const leftWeighted = weightedSector(left);
  const rightWeighted = weightedSector(right);

  return {
    ...analysis,
    status: "ready",
    previousId: itemId(items[previousIndex]),
    previousIndex,
    offsetId: itemId(items[offsetIndex]),
    offsetIndex,
    offset,
    leftCenter: wheelAt(leftIndex),
    rightCenter: wheelAt(rightIndex),
    left,
    right,
    bet: [...new Set([...left, ...right])].sort(numericOrder),
    leftWeighted,
    rightWeighted,
    betWeighted: mergeWeightedSectors(leftWeighted, rightWeighted),
    leftPath: Array.from({ length: offset + 1 }, (_, step) => wheelAt(basePosition - step)),
    rightPath: Array.from({ length: offset + 1 }, (_, step) => wheelAt(basePosition + step)),
  };
}

/** Summarize ready analyses; a number contributes at most once per bet. */
export function summarizeBets(analyses) {
  const counts = new Map();
  for (const analysis of Array.isArray(analyses) ? analyses : []) {
    if (analysis?.status !== "ready" || !Array.isArray(analysis.bet)) continue;
    const distinct = new Set(analysis.bet.filter(validNumber));
    for (const number of distinct) counts.set(number, (counts.get(number) || 0) + 1);
  }

  return {
    union: [...counts.keys()].sort(numericOrder),
    repeated: [...counts.entries()]
      .filter(([, count]) => count > 1)
      .map(([number, count]) => ({ number, count }))
      .sort((left, right) => right.count - left.count || left.number - right.number),
  };
}

/**
 * Weight the bets born after the sourceLimit newest occurrences, using the full history
 * to reconstruct each pair. Only strictly newer results can pay a bet. Hits are
 * chronological, from the first following spin toward the newest one.
 *
 * A ready slot has complete valid follow-up; other slots contribute no scores.
 * Unknown follow-up is distinct from zero hits. rawCount includes paid ready
 * bets, while activeCount includes only ready bets with positive residual weight.
 * Scores combine spatial weights with the temporal factor retained in slot.weight;
 * overlapping sectors contribute their maximum spatial weight within each bet.
 * lookback excludes newer spins entirely. All returned indices are relative to
 * that historical suffix, whose full older context remains available for pairs.
 */
export function analyzeHeatmap(items, decayPercent = 100, sourceLimit = 10, lookback = 0) {
  if (!Number.isInteger(decayPercent) || decayPercent < 0 || decayPercent > 100) {
    throw new RangeError("A redução por acerto deve ser um percentual inteiro entre 0 e 100.");
  }
  if (!Number.isInteger(sourceLimit) || sourceLimit < 1 || sourceLimit > 10) {
    throw new RangeError("A quantidade de giros deve ser um número inteiro entre 1 e 10.");
  }
  if (!Array.isArray(items)) {
    throw new TypeError("O histórico deve ser uma lista de resultados.");
  }
  if (!Number.isInteger(lookback) || lookback < 0 || lookback > Math.max(0, items.length - 1)) {
    throw new RangeError("A referência deve ser um número inteiro dentro do histórico disponível.");
  }

  const referenceItems = items.slice(lookback);
  const sourceCount = Math.min(sourceLimit, referenceItems.length);
  const scores = Array.from({ length: WHEEL.length }, (_, number) => ({
    number, weight: 0, rawCount: 0, activeCount: 0,
  }));
  const slots = [];
  let unpaidCount = 0;
  let paidCount = 0;
  let skippedCount = 0;

  for (let index = 0; index < sourceCount; index += 1) {
    const analysis = analyzeSelection(referenceItems, index);
    const slot = {
      analysis, index, hits: [], hitCount: null, weight: null, status: analysis.status,
    };
    if (analysis.status !== "ready") {
      skippedCount += 1;
      slots.push(slot);
      continue;
    }

    let followupValid = true;
    const hits = [];
    for (let newerIndex = index - 1; newerIndex >= 0; newerIndex -= 1) {
      const item = referenceItems[newerIndex];
      if (!validNumber(item?.value)) {
        followupValid = false;
        break;
      }
      if (analysis.bet.includes(item.value)) {
        hits.push({ index: newerIndex, id: itemId(item), value: item.value });
      }
    }
    if (!followupValid) {
      slot.status = "unknown";
      skippedCount += 1;
      slots.push(slot);
      continue;
    }

    slot.hits = hits;
    slot.hitCount = hits.length;
    slot.weight = (1 - decayPercent / 100) ** slot.hitCount;
    if (slot.hitCount === 0) unpaidCount += 1;
    else paidCount += 1;
    for (const { number, weight: spatialWeight } of analysis.betWeighted) {
      scores[number].rawCount += 1;
      scores[number].weight += slot.weight * spatialWeight;
      if (slot.weight > 0) scores[number].activeCount += 1;
    }
    slots.push(slot);
  }

  return {
    decayPercent,
    sourceLimit,
    lookback,
    sourceCount,
    slots,
    scores,
    readyCount: unpaidCount + paidCount,
    unpaidCount,
    paidCount,
    skippedCount,
    maxScore: Math.max(...scores.map((score) => score.weight)),
  };
}
