import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("../../../bot_automatico/node_modules/playwright");
const apiDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const staticDirectory = path.join(apiDirectory, "static");
const origin = "http://contextual-similarity.test";
const html = await fs.readFile(path.join(apiDirectory, "templates/contextual_similarity.html"), "utf8");
const chronological = [1, 2, 3, 4, 5, 5, 28, 0, 4];
const items = chronological.slice().reverse().map((value, index) => ({ _id: `spin-${index}`, value }));
const occurrences = ["episode-a", "episode-b", "episode-c"].map((id) => ({
  id, context: [5, 28, 0, 4], preceding: [1, 2, 3, 4, 5],
  following: [5, 0, 17, 28, 36], preceding_complete: true, preceding_lookup_status: "complete",
}));
const searchRequests = [];
const staticScripts = [];
const errors = [];
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith("/contextual-similarity.js") || url.pathname.endsWith("/contextual-similarity-model.js")) {
      staticScripts.push(url);
    }
  });
  await page.route(`${origin}/**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/analise-similaridade-contextual") {
      await route.fulfill({ status: 200, contentType: "text/html", body: html });
      return;
    }
    if (url.pathname.startsWith("/static/")) {
      const localPath = path.resolve(staticDirectory, `.${url.pathname.slice("/static".length)}`);
      assert.ok(localPath.startsWith(`${staticDirectory}${path.sep}`));
      const contentType = url.pathname.endsWith(".js") ? "application/javascript" : "text/css";
      await route.fulfill({ status: 200, contentType, path: localPath });
      return;
    }
    if (url.pathname === "/history/pragmatic-brazilian-roulette") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items }) });
      return;
    }
    if (url.pathname === "/busca-vetorial/api/search") {
      searchRequests.push(JSON.parse(route.request().postData()));
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ total_matches: 3, occurrences }) });
      return;
    }
    await route.fulfill({ status: 404, body: "not found" });
  });

  await page.goto(`${origin}/analise-similaridade-contextual`);
  await page.locator("#analysis-status").getByText("3 ocorrência(s) selecionada(s)").waitFor();
  assert.deepEqual(searchRequests[0].sequence, [5, 28, 0, 4]);
  assert.equal(staticScripts.some((url) => url.pathname.endsWith("/contextual-similarity.js") && url.searchParams.get("v") === "20261108-live-marks"), true);
  assert.equal(staticScripts.some((url) => url.pathname.endsWith("/contextual-similarity-model.js") && url.searchParams.get("v") === "20261107-click-select"), true);
  const stylesheets = await page.locator('link[rel="stylesheet"]').evaluateAll((links) => links.map((link) => new URL(link.href)));
  assert.equal(stylesheets.some((url) => url.pathname.endsWith("/contextual-similarity.css") && url.searchParams.get("v") === "20261108-live-marks"), true);
  assert.equal(searchRequests[0].roulette_id, "pragmatic-brazilian-roulette");
  assert.equal(await page.locator("#current-context .cs-number").count(), 5);
  assert.equal(await page.locator("#current-sequence .cs-number").count(), 4);
  assert.equal(await page.locator("#occurrence-rows tr").count(), 3);
  assert.equal(await page.locator("#ranking-rows tr").count(), 37);
  assert.equal(await page.locator("#selected-details .cs-selected-card").count(), 3);
  assert.equal(await page.locator("#selected-details .cs-match-list li").count(), 30);
  assert.equal(await page.locator("#ranking-denominator").textContent(), "Máximo individual: 300 pontos (30 resultados × 10)");
  assert.deepEqual(errors, []);

  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.locator(".cs-header").evaluate((node) => getComputedStyle(node).flexDirection), "column");
  assert.equal(await page.locator(".cs-table-wrap").first().evaluate((node) => node.scrollWidth > node.clientWidth), true);
} finally {
  await browser.close();
}
