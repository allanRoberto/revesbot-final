import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

const source = await fs.readFile(new URL("../../static/js/core/contextual-similarity-model.js", import.meta.url), "utf8");
const model = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

test("European wheel wraps at zero and neighbors 5 are 10 and 24", () => {
  assert.deepEqual(model.neighborsOf(0), [26, 32]);
  assert.deepEqual(model.neighborsOf(5), [10, 24]);
  assert.deepEqual(model.neighborsOf(28), [7, 12]);
});

test("context score finds the maximum one-to-one matching and favors exact pairs", () => {
  const result = model.scoreContext([0, 32, 1, 2, 3], [32, 26, 4, 5, 6]);
  assert.equal(result.score, 18);
  assert.equal(result.exact, 1);
  assert.equal(result.neighbor, 1);
  assert.equal(result.similarity, 36);
  assert.equal(new Set(result.matches.map((match) => match.historicalIndex)).size, result.matches.length);
  assert.equal(new Set(result.matches.map((match) => match.currentIndex)).size, result.matches.length);
});

test("incomplete contexts are excluded without filling missing values", () => {
  const result = model.analyzeOccurrences([1, 2, 3, 4, 5], [
    { id: "partial", preceding_complete: false, preceding: [1, 2], context: [1, 2, 3, 4], following: [5, 6, 7, 8, 9] },
    { id: "wrong-length", preceding_complete: true, preceding: [1, 2, 3, 4], context: [1, 2, 3, 4], following: [5, 6, 7, 8, 9] },
  ]);
  assert.equal(result.comparableCount, 0);
  assert.equal(result.selected.length, 0);
  assert.equal(result.rows.every((row) => row.score === null), true);
});

test("contextual selection applies the 30 percent cutoff and returns at most six", () => {
  const occurrences = Array.from({ length: 8 }, (_, index) => ({
    id: `match-${index}`, context: [5, 28, 0, 4], preceding: [1, 2, 3, 4, 5],
    preceding_complete: true, following: [5, 9, 7, 19, 0],
  }));
  occurrences[6].preceding = [26, 13, 15, 17, 6];
  occurrences[7].preceding_complete = false;
  const result = model.analyzeOccurrences([1, 2, 3, 4, 5], occurrences);
  assert.equal(result.comparableCount, 7);
  assert.equal(result.selected.length, 6);
  assert.deepEqual(result.selected.map((row) => row.id), ["match-0", "match-1", "match-2", "match-3", "match-4", "match-5"]);
});

test("the 30 percent cutoff accepts a 32 percent context and rejects 16 percent", () => {
  const occurrences = [
    { id: "above", context: [5, 28, 0, 4], preceding: [26, 33, 13, 17, 6], preceding_complete: true, following: [1, 2, 3, 4, 5] },
    { id: "below", context: [5, 28, 0, 4], preceding: [26, 13, 15, 17, 6], preceding_complete: true, following: [1, 2, 3, 4, 5] },
  ];
  const result = model.analyzeOccurrences([0, 1, 2, 3, 4], occurrences);
  assert.deepEqual(result.rows.map((row) => row.score.similarity), [32, 16]);
  assert.deepEqual(result.selected.map((row) => row.id), ["above"]);
});

test("following observations distribute to self and both physical neighbors, including zero rows", () => {
  const result = model.rankFollowing([
    { id: "a", following: [5, 5, 0, 1, 2] },
  ]);
  const byNumber = new Map(result.ranking.map((row) => [row.number, row]));
  assert.equal(result.ranking.length, 37);
  assert.equal(result.analyzedResults, 5);
  assert.equal(result.maximum, 50);
  assert.deepEqual([byNumber.get(5).score, byNumber.get(5).exact, byNumber.get(5).neighbor], [20, 2, 0]);
  assert.deepEqual([byNumber.get(10).score, byNumber.get(10).exact, byNumber.get(10).neighbor], [16, 0, 2]);
  assert.deepEqual([byNumber.get(24).score, byNumber.get(24).exact, byNumber.get(24).neighbor], [16, 0, 2]);
  assert.equal(byNumber.get(17).score, 0);
  assert.equal(byNumber.get(17).percentage, 0);
});

test("ranking denominator follows the number of validated posterior results", () => {
  const result = model.rankFollowing([
    { id: "a", following: [5, 6, 7, 8, 9] },
    { id: "bad", following: [5, 6, 7] },
  ]);
  assert.equal(result.analyzedResults, 5);
  assert.equal(result.maximum, 50);
  assert.equal(result.ranking.find((row) => row.number === 5).percentage, 20);
});
