export const CONFIG = Object.freeze({
  rouletteId: "pragmatic-brazilian-roulette",
  contextLength: 5,
  sequenceLength: 4,
  followingLength: 5,
  selectedOccurrences: 6,
  exactPoints: 10,
  neighborPoints: 8,
  minimumSimilarity: 30,
});

export const WHEEL = Object.freeze([
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
  5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
]);

const wheelPositions = new Map(WHEEL.map((number, index) => [number, index]));
const wheelAt = (index) => WHEEL[(index + WHEEL.length) % WHEEL.length];
export const neighborsOf = (number) => {
  const index = wheelPositions.get(number);
  return index === undefined ? [] : [wheelAt(index - 1), wheelAt(index + 1)];
};
const validNumber = (value) => Number.isInteger(value) && value >= 0 && value <= 36;
const validNumbers = (values, length) => Array.isArray(values) && values.length === length && values.every(validNumber);

function bestMatching(current, historical) {
  let best = { score: 0, exact: 0, neighbor: 0, matches: [] };
  const used = new Set();
  const chosen = [];

  function visit(index, score, exact, neighbor) {
    if (index === current.length) {
      if (score > best.score || (score === best.score && exact > best.exact)) {
        best = { score, exact, neighbor, matches: chosen.map((match) => ({ ...match })) };
      }
      return;
    }
    visit(index + 1, score, exact, neighbor);
    for (let historicalIndex = 0; historicalIndex < historical.length; historicalIndex += 1) {
      if (used.has(historicalIndex)) continue;
      const value = historical[historicalIndex];
      const type = current[index] === value ? "exact"
        : neighborsOf(current[index]).includes(value) ? "neighbor" : null;
      if (!type) continue;
      used.add(historicalIndex);
      chosen.push({ current: current[index], historical: value, currentIndex: index,
        historicalIndex, type, points: type === "exact" ? CONFIG.exactPoints : CONFIG.neighborPoints });
      visit(index + 1, score + chosen.at(-1).points, exact + Number(type === "exact"),
        neighbor + Number(type === "neighbor"));
      chosen.pop();
      used.delete(historicalIndex);
    }
  }

  visit(0, 0, 0, 0);
  return best;
}

export function scoreContext(current, historical) {
  if (!validNumbers(current, CONFIG.contextLength) || !validNumbers(historical, CONFIG.contextLength)) {
    return { valid: false, score: 0, similarity: 0, exact: 0, neighbor: 0, matches: [] };
  }
  const result = bestMatching(current, historical);
  return { valid: true, ...result, similarity: (result.score / 50) * 100 };
}

export function analyzeOccurrences(current, occurrences) {
  const rows = (Array.isArray(occurrences) ? occurrences : []).map((occurrence, index) => {
    const precedingValid = occurrence?.preceding_complete === true && validNumbers(occurrence.preceding, 5);
    const contextValid = validNumbers(occurrence?.context, 4);
    const followingValid = validNumbers(occurrence?.following, 5);
    const score = precedingValid ? scoreContext(current, occurrence.preceding) : null;
    return {
      id: typeof occurrence?.id === "string" ? occurrence.id : "",
      context: occurrence?.context,
      preceding: occurrence?.preceding,
      following: occurrence?.following,
      preceding_lookup_status: occurrence?.preceding_lookup_status || "unavailable",
      score,
      precedingValid,
      contextValid,
      followingValid,
      index,
      approved: Boolean(score?.valid && score.similarity >= CONFIG.minimumSimilarity && contextValid),
    };
  });
  const comparable = rows.filter((row) => row.precedingValid && row.contextValid);
  const selected = rows.filter((row) => row.approved).sort((left, right) =>
    right.score.score - left.score.score || right.score.exact - left.score.exact || left.index - right.index)
    .slice(0, CONFIG.selectedOccurrences);
  return { rows, comparableCount: comparable.length, selected };
}

export function rankFollowing(selected) {
  const scores = Array.from({ length: 37 }, (_, number) => ({
    number, score: 0, exact: 0, neighbor: 0, exactSources: [], neighborSources: [],
  }));
  const results = (Array.isArray(selected) ? selected : []).flatMap((row) =>
    validNumbers(row?.following, CONFIG.followingLength) ? row.following.map((number) => ({ number, id: row.id })) : []);

  for (const result of results) {
    const exact = scores[result.number];
    exact.score += CONFIG.exactPoints;
    exact.exact += 1;
    exact.exactSources.push(result.id);
    for (const neighborNumber of neighborsOf(result.number)) {
      const neighbor = scores[neighborNumber];
      neighbor.score += CONFIG.neighborPoints;
      neighbor.neighbor += 1;
      neighbor.neighborSources.push(result.id);
    }
  }
  const maximum = results.length * CONFIG.exactPoints;
  const ranking = scores.map((row) => ({ ...row, percentage: maximum ? (row.score / maximum) * 100 : 0 }))
    .sort((left, right) => right.score - left.score || right.exact - left.exact ||
      right.neighbor - left.neighbor || left.number - right.number);
  return { ranking, analyzedResults: results.length, maximum };
}

export function signalMarkCounts(row, markedNumbers, currentContext = [], searchSequence = []) {
  const contextMarks = new Set(currentContext);
  const sequenceMarks = new Set(searchSequence);
  const columns = [
    row?.precedingValid ? row.preceding : null,
    row?.contextValid ? row.context : null,
    row?.followingValid ? row.following : null,
  ];
  return columns.map((values, index) => {
    if (!Array.isArray(values)) return 0;
    return values.filter((number) => markedNumbers.has(number) ||
      (index === 0 && contextMarks.has(number)) || (index === 1 && sequenceMarks.has(number))).length;
  });
}

export function signalActivation(row, markedNumbers, currentContext = [], searchSequence = []) {
  const counts = signalMarkCounts(row, markedNumbers, currentContext, searchSequence);
  const total = counts.reduce((sum, count) => sum + count, 0);
  return { active: total >= 6 && counts.every((count) => count >= 1), total, counts };
}

export function unmarkedBetNumbers(row, markedNumbers, currentContext = [], searchSequence = []) {
  const contextMarks = new Set(currentContext);
  const sequenceMarks = new Set(searchSequence);
  const excluded = new Set(markedNumbers);
  if (row?.precedingValid) row.preceding.filter((number) => contextMarks.has(number)).forEach((number) => excluded.add(number));
  if (row?.contextValid) row.context.filter((number) => sequenceMarks.has(number)).forEach((number) => excluded.add(number));
  return [...new Set([
    ...(row?.precedingValid ? row.preceding : []),
    ...(row?.contextValid ? row.context : []),
    ...(row?.followingValid ? row.following : []),
  ].filter((number) => !excluded.has(number)))].sort((a, b) => a - b);
}
