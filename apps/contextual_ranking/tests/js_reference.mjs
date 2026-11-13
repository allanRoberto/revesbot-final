// Executes the original browser rules for parity tests.
// Input (stdin): {"cases": [{current_context, sequence, live, selected, occurrences}]}
// Output (stdout): one result per case with the table order and the top-4 ranking.
import fs from "node:fs/promises";
import vm from "node:vm";

const staticRoot = new URL("../../api/static/js/", import.meta.url);
const modelSource = await fs.readFile(new URL("core/contextual-similarity-model.js", staticRoot), "utf8");
const model = await import(`data:text/javascript;base64,${Buffer.from(modelSource).toString("base64")}`);
const pageSource = await fs.readFile(new URL("pages/contextual-similarity.js", staticRoot), "utf8");

function extractFunction(name) {
  const start = pageSource.indexOf(`\nfunction ${name}(`);
  if (start < 0) throw new Error(`function ${name} not found in contextual-similarity.js`);
  const end = pageSource.indexOf("\n}\n", start);
  if (end < 0) throw new Error(`end of function ${name} not found`);
  return pageSource.slice(start + 1, end + 2);
}

const sandbox = {
  neighborsOf: model.neighborsOf,
  liveMarkedNumbers: new Set(),
  selectedOccurrenceNumbers: new Set(),
};
vm.createContext(sandbox);
vm.runInContext(
  ["matchCounts", "compareDistribution", "duplicateCount", "liveHitDistribution", "occurrenceOrder"]
    .map(extractFunction).join("\n"),
  sandbox,
);

let input = "";
for await (const chunk of process.stdin) input += chunk;
const { cases } = JSON.parse(input);

const results = cases.map((item) => {
  sandbox.liveMarkedNumbers = new Set(item.live || []);
  sandbox.selectedOccurrenceNumbers = new Set(item.selected || []);
  const analysis = model.analyzeOccurrences(item.current_context, item.occurrences);
  const ordered = [...analysis.rows].sort((left, right) => sandbox.occurrenceOrder(left, right, item.sequence));
  const ranked = model.rankFollowing(ordered.slice(0, item.top ?? 4));
  return {
    order: ordered.map((row) => row.index),
    scores: analysis.rows.map((row) => row.score
      ? [row.score.valid, row.score.score, row.score.exact, row.score.neighbor, row.score.similarity]
      : null),
    approved: analysis.rows.map((row) => row.approved),
    ranking: ranked.ranking.map((row) => [row.number, row.score, row.exact, row.neighbor, row.percentage]),
    analyzed_results: ranked.analyzedResults,
    maximum: ranked.maximum,
  };
});
process.stdout.write(JSON.stringify(results));
