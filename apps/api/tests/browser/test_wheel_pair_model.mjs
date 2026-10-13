import assert from "node:assert/strict";
import test from "node:test";
import { WHEEL, analyzeSelection, summarizeBets, analyzeHeatmap } from "../../static/js/core/wheel-pair-model.js";

const history = (...values) => values.map((value, index) => ({ _id: `spin-${index}`, value }));
const approximately = (actual, expected) => assert.ok(
  Math.abs(actual - expected) < 1e-12,
  `Expected ${actual} to be approximately ${expected}`,
);

test("the canonical wheel has every European roulette number exactly once", () => {
  assert.equal(WHEEL.length, 37);
  assert.deepEqual([...WHEEL].sort((left, right) => left - right), Array.from({ length: 37 }, (_, i) => i));
  assert.equal(Object.isFrozen(WHEEL), true);
});

test("selecting the returning 25 reconstructs the example pair and both sectors", () => {
  const items = history(25, 4, 11, 25, 18);
  const original = JSON.stringify(items);
  const result = analyzeSelection(items, 0);

  assert.equal(result.status, "ready");
  assert.equal(result.selectedId, "spin-0");
  assert.equal(result.selectedIndex, 0);
  assert.equal(result.previousId, "spin-3");
  assert.equal(result.previousIndex, 3);
  assert.equal(result.offsetId, "spin-2");
  assert.equal(result.offsetIndex, 2);
  assert.equal(result.base, 25);
  assert.equal(result.offset, 11);
  assert.equal(result.leftCenter, 12);
  assert.equal(result.rightCenter, 10);
  assert.deepEqual(result.left, [7, 28, 12, 35, 3]);
  assert.deepEqual(result.right, [8, 23, 10, 5, 24]);
  assert.deepEqual(result.bet, [3, 5, 7, 8, 10, 12, 23, 24, 28, 35]);
  assert.deepEqual(result.leftPath, [25, 2, 21, 4, 19, 15, 32, 0, 26, 3, 35, 12]);
  assert.deepEqual(result.rightPath, [25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10]);
  assert.equal(JSON.stringify(items), original);
});

test("lookup is strictly older than the selected occurrence and stops at the first match", () => {
  const result = analyzeSelection(history(25, 31, 25, 3, 11, 25, 8, 25), 2);
  assert.equal(result.previousIndex, 5);
  assert.equal(result.offsetIndex, 4);
  assert.equal(result.offset, 11);

  const consecutive = analyzeSelection(history(25, 25, 11, 25), 0);
  assert.equal(consecutive.previousIndex, 1);
  assert.equal(consecutive.offsetIndex, 0);
  assert.equal(consecutive.offset, 25);
});

test("the oldest visible occurrence explicitly has no older pair", () => {
  const result = analyzeSelection(history(25, 11, 25), 2);
  assert.equal(result.status, "no_previous");
  assert.match(result.message, /ocorrência anterior/);
  assert.equal(result.base, 25);
  assert.equal(result.previousIndex, null);
  assert.equal(result.offset, null);
  assert.deepEqual(result.bet, []);
});

test("wheel paths and neighborhoods wrap correctly through zero", () => {
  const result = analyzeSelection(history(0, 1, 0), 0);
  assert.equal(result.leftCenter, 26);
  assert.equal(result.rightCenter, 32);
  assert.deepEqual(result.leftPath, [0, 26]);
  assert.deepEqual(result.rightPath, [0, 32]);
  assert.deepEqual(result.left, [35, 3, 26, 0, 32]);
  assert.deepEqual(result.right, [26, 0, 32, 15, 19]);
  assert.deepEqual(result.bet, [0, 3, 15, 19, 26, 32, 35]);
});

test("zero houses keeps both centers at the base and produces five unique numbers", () => {
  const result = analyzeSelection(history(25, 0, 25), 0);
  assert.equal(result.status, "ready");
  assert.equal(result.offset, 0);
  assert.equal(result.leftCenter, 25);
  assert.equal(result.rightCenter, 25);
  assert.deepEqual(result.leftPath, [25]);
  assert.deepEqual(result.rightPath, [25]);
  assert.deepEqual(result.left, result.right);
  assert.deepEqual(result.bet, [2, 17, 21, 25, 34]);
});

test("overlapping sectors remain distinct in the union at all overlap boundaries", () => {
  for (const [offset, expectedSize] of [[0, 5], [1, 7], [2, 9], [17, 8], [18, 6], [19, 6], [20, 8], [35, 9], [36, 7]]) {
    const result = analyzeSelection(history(25, offset, 25), 0);
    assert.equal(result.bet.length, expectedSize, `offset ${offset}`);
    assert.equal(new Set(result.bet).size, expectedSize);
    assert.deepEqual(result.bet, [...result.bet].sort((left, right) => left - right));
    assert.equal(result.leftPath.length, offset + 1);
    assert.equal(result.rightPath.length, offset + 1);
    assert.equal(result.leftPath.at(-1), result.leftCenter);
    assert.equal(result.rightPath.at(-1), result.rightCenter);
  }
});

test("invalid indices and values produce explicit errors without coercing null to zero", () => {
  for (const items of [null, undefined, {}, "25,11,25"]) {
    assert.equal(analyzeSelection(items, 0).status, "invalid");
  }
  for (const index of [-1, 3, 0.5, "0", null, undefined, NaN]) {
    assert.equal(analyzeSelection(history(25, 11, 25), index).status, "invalid");
  }
  for (const value of [null, undefined, "0", "25", false, NaN, Infinity, -1, 37, 2.5]) {
    const selected = analyzeSelection(history(value, 11, value), 0);
    assert.equal(selected.status, "invalid");
    assert.deepEqual(selected.bet, []);
    const intermediate = analyzeSelection(history(25, value, 25), 0);
    assert.equal(intermediate.status, "invalid");
    assert.deepEqual(intermediate.bet, []);
  }
  assert.equal(analyzeSelection(history(0, 11, 0), 0).status, "ready");
});

test("only the searched segment needs to be valid and IDs have consistent fallbacks", () => {
  const result = analyzeSelection([
    { id: "selected", value: 25 },
    { external_game_id: "offset", value: 11 },
    { value: 25 },
    { value: null },
  ], 0);
  assert.equal(result.status, "ready");
  assert.equal(result.selectedId, "selected");
  assert.equal(result.offsetId, "offset");
  assert.equal(result.previousId, null);
});

test("summaries count each number once per ready bet and order by frequency then number", () => {
  const analyses = [
    { status: "ready", bet: [35, 3, 3, 8, 8, 10] },
    { status: "ready", bet: [10, 8, 3, 3] },
    { status: "ready", bet: [35, 8] },
    { status: "no_previous", bet: [3, 35] },
    { status: "invalid", bet: [0, 3] },
  ];
  const original = JSON.stringify(analyses);
  assert.deepEqual(summarizeBets(analyses), {
    union: [3, 8, 10, 35],
    repeated: [
      { number: 8, count: 3 },
      { number: 3, count: 2 },
      { number: 10, count: 2 },
      { number: 35, count: 2 },
    ],
  });
  assert.equal(JSON.stringify(analyses), original);
});

test("summaries handle no bets, single bets, and malformed values safely", () => {
  assert.deepEqual(summarizeBets([]), { union: [], repeated: [] });
  assert.deepEqual(summarizeBets(null), { union: [], repeated: [] });
  assert.deepEqual(summarizeBets([null, { status: "ready" }]), { union: [], repeated: [] });
  assert.deepEqual(summarizeBets([{ status: "ready", bet: [null, "0", false, 0, 36, 36] }]), {
    union: [0, 36], repeated: [],
  });
});

test("two selected occurrences retain separate identities even when their bets match", () => {
  const items = history(25, 4, 11, 25, 8, 11, 25);
  const first = analyzeSelection(items, 0);
  const second = analyzeSelection(items, 3);
  assert.notEqual(first.selectedId, second.selectedId);
  assert.deepEqual(first.bet, second.bet);
  const summary = summarizeBets([first, second]);
  assert.deepEqual(summary.union, first.bet);
  assert.deepEqual(summary.repeated, first.bet.map((number) => ({ number, count: 2 })));
});

const paidHeatmapFixture = () => history(20, 20, 20, 20, 20, 20, 26, 2, 21, 25, 8, 25, 5, 21, 8, 2);

test("one later 26 pays three independently formed bets with centers 26, 0, and 3", () => {
  const result = analyzeHeatmap(paidHeatmapFixture());
  assert.deepEqual([9, 8, 7].map((index) => result.slots[index].analysis.leftCenter), [26, 0, 3]);
  assert.deepEqual([9, 8, 7].map((index) => result.slots[index].analysis.previousIndex), [11, 13, 15]);
  for (const index of [9, 8, 7]) {
    const slot = result.slots[index];
    assert.equal(slot.status, "ready");
    assert.equal(slot.analysis.bet.length, 10);
    assert.deepEqual(slot.hits, [{ index: 6, id: "spin-6", value: 26 }]);
    assert.equal(slot.hitCount, 1);
    assert.equal(slot.weight, 0);
  }
  assert.deepEqual(result.scores[26], { number: 26, weight: 0, rawCount: 3, activeCount: 0 });
  assert.equal(result.sourceCount, 10);
  assert.equal(result.readyCount, 8);
  assert.equal(result.paidCount, 3);
  assert.equal(result.unpaidCount, 5);
  assert.equal(result.skippedCount, 2);
  assert.equal(result.maxScore, 5);

  const half = analyzeHeatmap(paidHeatmapFixture(), 50);
  approximately(half.scores[26].weight, 1.2);
  assert.equal(half.scores[26].rawCount, 3);
  assert.equal(half.scores[26].activeCount, 3);
  assert.equal(half.maxScore, 5);
});

test("every later hit reduces the whole bet again and records hits in chronological order", () => {
  const items = paidHeatmapFixture();
  items[5].value = 26;
  const half = analyzeHeatmap(items, 50);
  for (const index of [9, 8, 7]) {
    assert.deepEqual(half.slots[index].hits, [
      { index: 6, id: "spin-6", value: 26 },
      { index: 5, id: "spin-5", value: 26 },
    ]);
    assert.equal(half.slots[index].hitCount, 2);
    assert.equal(half.slots[index].weight, 0.25);
  }
  approximately(half.scores[26].weight, 0.6);
  // 35 also belongs to these paid bets even though the paying result was 26.
  approximately(half.scores[35].weight, 0.25);
  assert.equal(analyzeHeatmap(items, 100).scores[26].weight, 0);
});

test("a 25 percent reduction compounds per hit and zero percent preserves paid weights", () => {
  const items = paidHeatmapFixture();
  const first = analyzeHeatmap(items, 25);
  assert.equal(first.slots[9].weight, 0.75);
  approximately(first.scores[26].weight, 1.8);
  items[5].value = 26;
  const second = analyzeHeatmap(items, 25);
  assert.equal(second.slots[9].weight, 0.5625);
  approximately(second.scores[26].weight, 1.35);

  const noReduction = analyzeHeatmap(items, 0);
  assert.equal(noReduction.slots[9].weight, 1);
  approximately(noReduction.scores[26].weight, 2.4);
  assert.equal(noReduction.scores[26].rawCount, 3);
  assert.equal(noReduction.scores[26].activeCount, 3);
  assert.equal(noReduction.slots[9].hitCount, 2);
  assert.ok(noReduction.paidCount > 0);
});

test("a bet is born after its base and older results cannot pay it", () => {
  const ownBase = analyzeHeatmap(history(25, 0, 25));
  assert.ok(ownBase.slots[0].analysis.bet.includes(25));
  assert.equal(ownBase.slots[0].hitCount, 0);
  assert.equal(ownBase.slots[0].weight, 1);
  assert.deepEqual(ownBase.scores[25], { number: 25, weight: 1, rawCount: 1, activeCount: 1 });

  const olderHit = analyzeHeatmap(history(25, 3, 11, 25));
  assert.ok(olderHit.slots[0].analysis.bet.includes(3));
  assert.equal(olderHit.slots[0].hitCount, 0);
  assert.equal(olderHit.slots[0].weight, 1);
});

test("overlapping sectors count a number once per occurrence without grouping equal bases", () => {
  const overlap = analyzeHeatmap(history(0, 1, 0));
  assert.equal(overlap.slots[0].analysis.bet.length, 7);
  assert.deepEqual(overlap.scores[0], { number: 0, weight: 0.7, rawCount: 1, activeCount: 1 });
  approximately(overlap.scores.reduce((total, score) => total + score.weight, 0), 4.7);

  const equalBases = analyzeHeatmap(history(0, 0, 0), 0);
  assert.equal(equalBases.readyCount, 2);
  assert.notEqual(equalBases.slots[0].analysis.selectedId, equalBases.slots[1].analysis.selectedId);
  assert.equal(equalBases.slots[0].hitCount, 0);
  assert.equal(equalBases.slots[1].hitCount, 1);
  assert.deepEqual(equalBases.scores[0], { number: 0, weight: 2, rawCount: 2, activeCount: 2 });
});

test("the source window is exactly ten occurrences but pair lookup uses the full history", () => {
  const items = paidHeatmapFixture();
  const full = analyzeHeatmap(items);
  assert.equal(full.sourceCount, 10);
  assert.deepEqual(full.slots.map((slot) => slot.index), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  assert.equal(full.slots[9].analysis.previousIndex, 11);
  assert.equal(full.slots[9].status, "ready");
  assert.equal(analyzeHeatmap(items.slice(0, 10)).slots[9].status, "no_previous");

  const short = analyzeHeatmap(history(25, 11, 25));
  assert.equal(short.sourceCount, 3);
  assert.equal(short.slots.length, 3);
});

test("unpaid older bets keep their weight regardless of age", () => {
  const items = paidHeatmapFixture();
  items[6].value = 20;
  const result = analyzeHeatmap(items, 100);
  for (const index of [9, 8, 7]) {
    assert.equal(result.slots[index].hitCount, 0);
    assert.equal(result.slots[index].weight, 1);
  }
  approximately(result.scores[26].weight, 2.4);
});

test("recomputing and switching reduction settings is idempotent without mutating inputs", () => {
  const items = Object.freeze(paidHeatmapFixture().map((item) => Object.freeze(item)));
  const before = JSON.stringify(items);
  const first = analyzeHeatmap(items, 50);
  analyzeHeatmap(items, 100);
  const refreshed = analyzeHeatmap(items, 50);
  assert.deepEqual(refreshed, first);
  assert.equal(JSON.stringify(items), before);
  assert.notEqual(refreshed.slots, first.slots);
  assert.notEqual(refreshed.scores, first.scores);
});

test("missing previous occurrences and empty histories produce zero scores without filling the window", () => {
  const result = analyzeHeatmap(history(25, 11, 4));
  assert.equal(result.sourceCount, 3);
  assert.equal(result.readyCount, 0);
  assert.equal(result.skippedCount, 3);
  assert.ok(result.slots.every((slot) => slot.status === "no_previous" && slot.weight === null));
  assert.equal(result.maxScore, 0);
  assert.deepEqual(result.scores.map((score) => score.number), Array.from({ length: 37 }, (_, index) => index));
  assert.ok(result.scores.every((score) => score.weight === 0 && score.rawCount === 0 && score.activeCount === 0));
  const empty = analyzeHeatmap([]);
  assert.equal(empty.sourceCount, 0);
  assert.equal(empty.skippedCount, 0);
  assert.deepEqual(empty.slots, []);
  assert.equal(empty.scores.length, 37);
  assert.equal(empty.maxScore, 0);
});

test("invalid newer results mark follow-up unknown rather than inferring no payment", () => {
  for (const invalid of [null, undefined, "0", false, NaN, Infinity, -1, 37, 2.5]) {
    const result = analyzeHeatmap(history(invalid, 25, 11, 25));
    const unknown = result.slots[1];
    assert.equal(unknown.analysis.status, "ready");
    assert.equal(unknown.status, "unknown");
    assert.deepEqual(unknown.hits, []);
    assert.equal(unknown.hitCount, null);
    assert.equal(unknown.weight, null);
    assert.equal(result.slots[0].status, "invalid");
    assert.equal(result.readyCount, 0);
    assert.equal(result.skippedCount, 4);
    assert.equal(result.scores[3].rawCount, 0);
    assert.equal(result.scores[3].weight, 0);
  }
  // A known hit before an unknown result is still incomplete follow-up.
  const partial = analyzeHeatmap(history(null, 3, 25, 11, 25), 50).slots[2];
  assert.equal(partial.status, "unknown");
  assert.deepEqual(partial.hits, []);
  assert.equal(partial.hitCount, null);
  assert.equal(partial.weight, null);
});

test("decay requires an integer percentage without coercion", () => {
  for (const invalid of [-1, 101, 0.5, "50", null, false, NaN, Infinity, {}, []]) {
    assert.throws(() => analyzeHeatmap([], invalid), RangeError);
  }
  for (const invalid of [null, undefined, {}, "25,11,25"]) {
    assert.throws(() => analyzeHeatmap(invalid), TypeError);
  }
  assert.equal(analyzeHeatmap([]).decayPercent, 100);
  assert.equal(analyzeHeatmap([], 0).decayPercent, 0);
  assert.equal(analyzeHeatmap([], 100).decayPercent, 100);
});

test("spatial sector weights follow physical distance and the merged bet stays numerically ordered", () => {
  const result = analyzeSelection(history(25, 4, 11, 25), 0);
  assert.deepEqual(result.leftWeighted, [
    { number: 7, weight: 0.3 },
    { number: 28, weight: 0.7 },
    { number: 12, weight: 1 },
    { number: 35, weight: 0.7 },
    { number: 3, weight: 0.3 },
  ]);
  assert.deepEqual(result.rightWeighted, [
    { number: 8, weight: 0.3 },
    { number: 23, weight: 0.7 },
    { number: 10, weight: 1 },
    { number: 5, weight: 0.7 },
    { number: 24, weight: 0.3 },
  ]);
  assert.deepEqual(result.betWeighted, [
    { number: 3, weight: 0.3 },
    { number: 5, weight: 0.7 },
    { number: 7, weight: 0.3 },
    { number: 8, weight: 0.3 },
    { number: 10, weight: 1 },
    { number: 12, weight: 1 },
    { number: 23, weight: 0.7 },
    { number: 24, weight: 0.3 },
    { number: 28, weight: 0.7 },
    { number: 35, weight: 0.7 },
  ]);
  assert.deepEqual(result.betWeighted.map(({ number }) => number), result.bet);
  approximately(result.betWeighted.reduce((sum, entry) => sum + entry.weight, 0), 6);
});

test("coincident sectors at zero houses preserve one weight per pocket rather than doubling", () => {
  const result = analyzeSelection(history(25, 0, 25), 0);
  assert.deepEqual(result.leftWeighted, result.rightWeighted);
  assert.deepEqual(result.betWeighted, [
    { number: 2, weight: 0.7 },
    { number: 17, weight: 0.7 },
    { number: 21, weight: 0.3 },
    { number: 25, weight: 1 },
    { number: 34, weight: 0.3 },
  ]);
  approximately(result.betWeighted.reduce((sum, entry) => sum + entry.weight, 0), 3);
});

test("overlapping sectors choose the maximum weight for shared pockets through zero", () => {
  const result = analyzeSelection(history(0, 1, 0), 0);
  assert.deepEqual(result.betWeighted, [
    { number: 0, weight: 0.7 },
    { number: 3, weight: 0.7 },
    { number: 15, weight: 0.7 },
    { number: 19, weight: 0.3 },
    { number: 26, weight: 1 },
    { number: 32, weight: 1 },
    { number: 35, weight: 0.3 },
  ]);
  assert.equal(result.leftWeighted.find(({ number }) => number === 26).weight, 1);
  assert.equal(result.rightWeighted.find(({ number }) => number === 26).weight, 0.3);
  assert.equal(result.betWeighted.find(({ number }) => number === 26).weight, 1);
});

test("spatial weights multiply the temporal factor without changing how hits are counted", () => {
  const unpaid = analyzeHeatmap(history(25, 4, 11, 25));
  assert.equal(unpaid.slots[0].weight, 1);
  assert.deepEqual(unpaid.scores[12], { number: 12, weight: 1, rawCount: 1, activeCount: 1 });
  assert.deepEqual(unpaid.scores[35], { number: 35, weight: 0.7, rawCount: 1, activeCount: 1 });
  assert.deepEqual(unpaid.scores[3], { number: 3, weight: 0.3, rawCount: 1, activeCount: 1 });

  // A hit on a distant neighbor pays the whole bet, despite its lower spatial weight.
  const once = analyzeHeatmap(history(3, 25, 4, 11, 25), 50);
  assert.equal(once.slots[1].hitCount, 1);
  assert.equal(once.slots[1].weight, 0.5);
  assert.deepEqual(once.scores[12], { number: 12, weight: 0.5, rawCount: 1, activeCount: 1 });
  approximately(once.scores[35].weight, 0.35);
  approximately(once.scores[3].weight, 0.15);

  const twice = analyzeHeatmap(history(35, 3, 25, 4, 11, 25), 50);
  assert.equal(twice.slots[2].hitCount, 2);
  assert.equal(twice.slots[2].weight, 0.25);
  approximately(twice.scores[12].weight, 0.25);
  approximately(twice.scores[35].weight, 0.175);
  approximately(twice.scores[3].weight, 0.075);

  const removed = analyzeHeatmap(history(3, 25, 4, 11, 25), 100);
  assert.deepEqual(removed.scores[35], { number: 35, weight: 0, rawCount: 1, activeCount: 0 });
});

test("unavailable selections expose empty weighted sectors with the existing status", () => {
  for (const analysis of [analyzeSelection(null, 0), analyzeSelection(history(25, 11, 4), 0)]) {
    assert.notEqual(analysis.status, "ready");
    assert.deepEqual(analysis.leftWeighted, []);
    assert.deepEqual(analysis.rightWeighted, []);
    assert.deepEqual(analysis.betWeighted, []);
  }
});

test("the default ranking window is identical to an explicit ten-occurrence window", () => {
  const items = paidHeatmapFixture();
  for (const decayPercent of [0, 25, 100]) {
    assert.deepEqual(analyzeHeatmap(items, decayPercent), analyzeHeatmap(items, decayPercent, 10));
  }
  assert.equal(analyzeHeatmap(items).sourceLimit, 10);
  assert.equal(analyzeHeatmap(items).sourceCount, 10);
});

test("a one-occurrence window uses only the newest bet without counting its own base as a hit", () => {
  const result = analyzeHeatmap(history(25, 0, 25), 50, 1);
  assert.equal(result.sourceLimit, 1);
  assert.equal(result.sourceCount, 1);
  assert.equal(result.slots.length, 1);
  assert.equal(result.slots[0].index, 0);
  assert.equal(result.slots[0].analysis.previousIndex, 2);
  assert.ok(result.slots[0].analysis.bet.includes(25));
  assert.equal(result.slots[0].hitCount, 0);
  assert.equal(result.slots[0].weight, 1);
  assert.equal(result.readyCount, 1);
  assert.equal(result.unpaidCount, 1);
  assert.equal(result.paidCount, 0);
  assert.deepEqual(result.scores[25], { number: 25, weight: 1, rawCount: 1, activeCount: 1 });
});

test("a three-occurrence window still finds older pairs and counts all causal newer hits", () => {
  const items = history(35, 3, 25, 4, 11, 25);
  const result = analyzeHeatmap(items, 50, 3);
  assert.equal(result.sourceCount, 3);
  assert.deepEqual(result.slots.map((slot) => slot.index), [0, 1, 2]);
  assert.equal(result.slots[2].analysis.previousIndex, 5);
  assert.equal(result.slots[2].analysis.offsetIndex, 4);
  assert.equal(result.slots[2].analysis.offset, 11);
  assert.deepEqual(result.slots[2].hits, [
    { index: 1, id: "spin-1", value: 3 },
    { index: 0, id: "spin-0", value: 35 },
  ]);
  assert.equal(result.slots[2].hitCount, 2);
  assert.equal(result.slots[2].weight, 0.25);
  assert.equal(result.readyCount, 1);
  assert.equal(result.skippedCount, 2);
  assert.deepEqual(result.scores[12], { number: 12, weight: 0.25, rawCount: 1, activeCount: 1 });
  assert.deepEqual(result.slots, analyzeHeatmap(items, 50, 10).slots.slice(0, 3));
});

test("window changes preserve common slots and do not accumulate weights across refreshes", () => {
  const items = Object.freeze(paidHeatmapFixture().map((item) => Object.freeze(item)));
  const before = JSON.stringify(items);
  const five = analyzeHeatmap(items, 50, 5);
  const ten = analyzeHeatmap(items, 50, 10);
  assert.deepEqual(five.slots, ten.slots.slice(0, 5));
  assert.equal(five.slots[4].analysis.previousIndex, 5);
  assert.equal(five.scores[26].weight, 0);
  approximately(ten.scores[26].weight, 1.2);
  analyzeHeatmap(items, 50, 3);
  assert.deepEqual(analyzeHeatmap(items, 50, 10), ten);
  assert.deepEqual(analyzeHeatmap(items, 50, 5), five);
  assert.equal(JSON.stringify(items), before);
});

test("the requested window is preserved when fewer occurrences are available", () => {
  const result = analyzeHeatmap(history(25, 11, 25), 100, 8);
  assert.equal(result.sourceLimit, 8);
  assert.equal(result.sourceCount, 3);
  assert.equal(result.slots.length, 3);
  const empty = analyzeHeatmap([], 100, 1);
  assert.equal(empty.sourceLimit, 1);
  assert.equal(empty.sourceCount, 0);
  assert.deepEqual(empty.slots, []);
  assert.equal(empty.maxScore, 0);
});

test("ranking windows require an integer between one and ten without coercion", () => {
  for (const invalid of [0, -1, 11, 1.5, "1", "10", null, false, NaN, Infinity, {}, []]) {
    assert.throws(() => analyzeHeatmap([], 100, invalid), RangeError);
  }
  assert.equal(analyzeHeatmap([], 100, 1).sourceLimit, 1);
  assert.equal(analyzeHeatmap([], 100, 10).sourceLimit, 10);
  assert.equal(analyzeHeatmap([], 100, undefined).sourceLimit, 10);
});

test("the default historical reference is identical to an explicit zero lookback", () => {
  const items = paidHeatmapFixture();
  for (const sourceLimit of [1, 3, 10]) {
    for (const decayPercent of [25, 100]) {
      assert.deepEqual(
        analyzeHeatmap(items, decayPercent, sourceLimit),
        analyzeHeatmap(items, decayPercent, sourceLimit, 0),
      );
    }
  }
  assert.equal(analyzeHeatmap(items).lookback, 0);
});

test("historical rankings exclude future paying results and keep suffix-relative indices", () => {
  const items = paidHeatmapFixture();
  const past = analyzeHeatmap(items, 100, 3, 7);
  assert.equal(past.lookback, 7);
  assert.equal(past.sourceCount, 3);
  assert.deepEqual(past.slots.map((slot) => slot.index), [0, 1, 2]);
  assert.deepEqual(past.slots.map((slot) => slot.analysis.selectedId), ["spin-7", "spin-8", "spin-9"]);
  assert.deepEqual(past.slots.map((slot) => slot.analysis.selectedIndex), [0, 1, 2]);
  assert.deepEqual(past.slots.map((slot) => slot.analysis.previousIndex), [8, 6, 4]);
  assert.deepEqual(past.slots.map((slot) => slot.analysis.leftCenter), [3, 0, 26]);
  assert.ok(past.slots.every((slot) => slot.hitCount === 0 && slot.weight === 1));
  assert.equal(past.readyCount, 3);
  assert.equal(past.unpaidCount, 3);
  assert.equal(past.paidCount, 0);
  approximately(past.scores[26].weight, 2.4);
  assert.equal(past.scores[26].rawCount, 3);
  assert.equal(past.scores[26].activeCount, 3);
  // The 26 at absolute index 6 happens after the historical reference.
  assert.equal(analyzeHeatmap(items, 100, 10, 0).scores[26].weight, 0);
});

test("historical one-occurrence windows retain older pairing context but ignore future hits", () => {
  const result = analyzeHeatmap(history(25, 3, 25, 4, 11, 25), 100, 1, 2);
  const slot = result.slots[0];
  assert.equal(result.sourceCount, 1);
  assert.equal(slot.analysis.selectedId, "spin-2");
  assert.equal(slot.analysis.previousId, "spin-5");
  assert.equal(slot.analysis.previousIndex, 3);
  assert.equal(slot.analysis.offsetIndex, 2);
  assert.equal(slot.analysis.offset, 11);
  assert.equal(slot.hitCount, 0);
  assert.equal(slot.weight, 1);
  assert.deepEqual(result.scores[3], { number: 3, weight: 0.3, rawCount: 1, activeCount: 1 });
});

test("invalid data from the future cannot invalidate an otherwise valid historical ranking", () => {
  const items = paidHeatmapFixture();
  const expected = analyzeHeatmap(items, 100, 3, 7);
  for (const invalid of [null, undefined, "0", false, NaN, 37]) {
    const changedFuture = items.map((item) => ({ ...item }));
    changedFuture[0].value = invalid;
    assert.deepEqual(analyzeHeatmap(changedFuture, 100, 3, 7), expected);
  }
});

test("the oldest reference and empty histories expose insufficient context without inventing pairs", () => {
  const oldest = analyzeHeatmap(history(25, 11, 25), 100, 10, 2);
  assert.equal(oldest.lookback, 2);
  assert.equal(oldest.sourceCount, 1);
  assert.equal(oldest.slots[0].analysis.selectedId, "spin-2");
  assert.equal(oldest.slots[0].index, 0);
  assert.equal(oldest.slots[0].status, "no_previous");
  assert.equal(oldest.readyCount, 0);
  assert.equal(oldest.skippedCount, 1);
  assert.equal(oldest.maxScore, 0);
  const empty = analyzeHeatmap([], 100, 10, 0);
  assert.equal(empty.lookback, 0);
  assert.equal(empty.sourceCount, 0);
  assert.deepEqual(empty.slots, []);
  assert.equal(empty.scores.length, 37);
});

test("historical computations are pure and a preserved reference is unaffected by new live data", () => {
  const snapshot = Object.freeze(paidHeatmapFixture().map((item) => Object.freeze(item)));
  const before = JSON.stringify(snapshot);
  const past = analyzeHeatmap(snapshot, 50, 3, 7);
  const live = [{ _id: "new-spin", value: 26 }, ...snapshot];
  const shifted = analyzeHeatmap(live, 50, 3, 8);
  assert.deepEqual({ ...shifted, lookback: 7 }, past);
  analyzeHeatmap(live, 50, 10, 0);
  assert.deepEqual(analyzeHeatmap(snapshot, 50, 3, 7), past);
  assert.equal(JSON.stringify(snapshot), before);
});

test("historical offsets require an integer within available history without coercion", () => {
  const items = history(25, 11, 25);
  for (const invalid of [-1, 3, 999, 0.5, "0", "2", null, false, NaN, Infinity, {}, []]) {
    assert.throws(() => analyzeHeatmap(items, 100, 10, invalid), RangeError);
  }
  assert.throws(() => analyzeHeatmap([], 100, 10, 1), RangeError);
  assert.equal(analyzeHeatmap(items, 100, 10, 0).lookback, 0);
  assert.equal(analyzeHeatmap(items, 100, 10, 2).lookback, 2);
  assert.equal(analyzeHeatmap(items, 100, 10, undefined).lookback, 0);
});
