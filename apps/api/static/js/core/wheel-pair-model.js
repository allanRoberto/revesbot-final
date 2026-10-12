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
    leftPath: [],
    rightPath: [],
  };
}

function sector(centerIndex) {
  return [-2, -1, 0, 1, 2].map((delta) => wheelAt(centerIndex + delta));
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
