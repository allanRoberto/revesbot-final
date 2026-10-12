import assert from "node:assert/strict";
import test from "node:test";
import { WHEEL, analyzeSelection, summarizeBets } from "../../static/js/core/wheel-pair-model.js";

const history = (...values) => values.map((value, index) => ({ _id: `spin-${index}`, value }));

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
