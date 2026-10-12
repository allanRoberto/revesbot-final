import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "../../../bot_automatico/node_modules/playwright");
const apiDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const staticDirectory = path.join(apiDirectory, "static");
const origin = "http://wheel-pair.test";
const autoSlug = "pragmatic-auto-roulette";
const megaSlug = "pragmatic-mega-roulette";
const roulettes = [
  { slug: autoSlug, name: "Pragmatic Auto Roulette", url: null },
  { slug: megaSlug, name: "Pragmatic Mega Roulette", url: null },
];
const python = process.env.PYTHON || path.resolve(apiDirectory, "../../.venv/bin/python");
const pageHtml = execFileSync(python, ["-c", [
  "import json, pathlib, sys",
  "from jinja2 import Environment, StrictUndefined",
  "template = pathlib.Path(sys.argv[1]).read_text()",
  "print(Environment(undefined=StrictUndefined, autoescape=True).from_string(template).render(**json.loads(sys.stdin.read())))",
].join("\n"), path.join(apiDirectory, "templates/wheel_pair.html")], {
  input: JSON.stringify({ asset_version: "browser-test", slug: autoSlug, roulette: roulettes[0], roulettes, all_roulettes: roulettes }),
  encoding: "utf8",
});

// Newest first: the selected 25 at index 1 uses the earlier 25 at index 4,
// whose immediately following result is 11 at index 3. Index 4 independently
// uses the earlier 25 at index 7 and the 11 at index 6.
const autoValues = Array(1000).fill(17);
[1, 25, 6, 11, 25, 0, 11, 25].forEach((value, index) => { autoValues[index] = value; });
autoValues[999] = 36;
const megaValues = Array(1000).fill(8);
megaValues[0] = 30;
const makeItems = (slug, values) => values.map((value, index) => ({
  _id: `${slug}-${index}`,
  value,
  roulette_id: slug,
  timestamp: new Date(Date.UTC(2026, 9, 12, 7) - index * 38000).toISOString(),
}));
const fixtures = new Map([
  [autoSlug, makeItems(autoSlug, autoValues)],
  [megaSlug, makeItems(megaSlug, megaValues)],
]);
const bet = [3, 5, 7, 8, 10, 12, 23, 24, 28, 35];
const historyCalls = [];
const pendingPlans = new Map();
const sockets = [];
const pageErrors = [];
const routeErrors = [];
const contrastChecks = [];

function nextHistory(slug, plan) {
  const queue = pendingPlans.get(slug) || [];
  queue.push(plan);
  pendingPlans.set(slug, queue);
}

function deferredHistory(slug, overrides = {}) {
  let release;
  let requested;
  const gate = new Promise((resolve) => { release = resolve; });
  const started = new Promise((resolve) => { requested = resolve; });
  nextHistory(slug, { ...overrides, gate, requested });
  return { release, started };
}

const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.on("pageerror", (error) => pageErrors.push(error.message));
page.setDefaultTimeout(10000);

await page.routeWebSocket(/ws:\/\/wheel-pair\.test\/ws(?:\?|$)/, (socket) => {
  sockets.push({ socket, slug: new URL(socket.url()).searchParams.get("slug") });
});

await page.route(`${origin}/**`, async (route) => {
  try {
    const url = new URL(route.request().url());
    if (url.pathname === "/contagem-casas") {
      await route.fulfill({ status: 200, contentType: "text/html", body: pageHtml });
      return;
    }
    if (url.pathname.startsWith("/static/")) {
      const localPath = path.resolve(staticDirectory, `.${url.pathname.slice("/static".length)}`);
      assert.ok(localPath.startsWith(`${staticDirectory}${path.sep}`), "only fixture static files may be served");
      const contentType = url.pathname.endsWith(".js") ? "application/javascript"
        : url.pathname.endsWith(".css") ? "text/css"
          : url.pathname.endsWith(".svg") ? "image/svg+xml" : "application/octet-stream";
      await route.fulfill({ status: 200, contentType, path: localPath });
      return;
    }
    if (url.pathname === "/api/roulettes-list") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(roulettes.map((item) => ({ ...item, id: item.slug, count: 1000 }))) });
      return;
    }
    if (url.pathname.startsWith("/history/")) {
      const slug = decodeURIComponent(url.pathname.slice("/history/".length));
      assert.equal(url.searchParams.get("limit"), "1000", "each table must request the fixed 1,000-result window");
      assert.ok(fixtures.has(slug), `unexpected table ${slug}`);
      historyCalls.push(slug);
      const plan = pendingPlans.get(slug)?.shift() || {};
      plan.requested?.();
      if (plan.gate) await plan.gate;
      const items = plan.empty ? [] : (plan.items || fixtures.get(slug));
      await route.fulfill({
        status: plan.error ? 503 : 200,
        contentType: "application/json",
        body: JSON.stringify(plan.error ? { detail: "Banco de dados indisponível" } : { items, results: items.map((item) => item.value) }),
      });
      return;
    }
    if (url.pathname === "/favicon.ico") {
      await route.fulfill({ status: 204 });
      return;
    }
    throw new Error(`Unexpected fixture request: ${url.pathname}`);
  } catch (error) {
    if (!route.request().failure()) routeErrors.push(error.message);
    await route.abort().catch(() => {});
  }
});

const result = (index) => page.locator(`#result-grid .result-card[data-result-index="${index}"]`);
const selection = (index) => page.locator(`#wheel-pair-list .wheel-pair-card[data-selection-index="${index}"]`);
const selectedCards = () => page.locator("#wheel-pair-list .wheel-pair-card");
const repeatedNumbers = () => page.locator("#wheel-pair-summary [data-repeated-number]");
const heatCell = (number) => page.locator(`#heatmap-race .number-cell[data-heat-number="${number}"]`);

async function assertHeat(number, weight, rawCount) {
  await page.waitForFunction(({ number: pocket, weight: expected, rawCount: raw }) => {
    const cell = document.querySelector(`#heatmap-race [data-heat-number="${pocket}"]`);
    return cell && cell.hasAttribute("data-heat-weight") && cell.hasAttribute("data-heat-raw-count")
      && Math.abs(Number(cell.dataset.heatWeight) - expected) < 1e-9 && Number(cell.dataset.heatRawCount) === raw;
  }, { number, weight, rawCount });
}

async function heatSnapshot() {
  return page.locator("#heatmap-race [data-heat-number]").evaluateAll((cells) => cells.map((cell) => [
    Number(cell.dataset.heatNumber), Number(cell.dataset.heatWeight), Number(cell.dataset.heatRawCount),
  ]));
}

async function assertPositiveHeatContrast() {
  const pockets = await page.locator('#heatmap-race [data-heat-number]').evaluateAll((cells) => cells
    .filter((cell) => Number(cell.dataset.heatWeight) > 0)
    .map((cell) => ({
      number: Number(cell.dataset.heatNumber),
      background: getComputedStyle(cell.querySelector("path, rect")).fill,
      foreground: getComputedStyle(cell.querySelector(".number-text")).fill,
    })));
  assert.ok(pockets.length > 0, "the contrast fixture must include active pockets");
  // Evaluate the computed SVG colors against WCAG's text contrast threshold;
  // this does not assume a particular palette or text-color selection algorithm.
  const luminance = (color) => {
    assert.match(color, /^rgba?\(/, `expected a resolved SVG color, received ${color}`);
    const channels = color.match(/[\d.]+/g).slice(0, 3).map(Number).map((channel) => {
      const normalized = channel / 255;
      return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
    });
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  };
  for (const pocket of pockets) {
    const light = luminance(pocket.foreground);
    const dark = luminance(pocket.background);
    const ratio = (Math.max(light, dark) + 0.05) / (Math.min(light, dark) + 0.05);
    assert.ok(ratio >= 4.5, `pocket ${pocket.number} must have at least 4.5:1 text contrast: ${ratio.toFixed(3)} (${pocket.foreground} over ${pocket.background})`);
    contrastChecks.push(ratio);
  }
}

async function chooseDecay(value) {
  const preset = page.locator(`#wheel-heatmap [data-decay-preset="${value}"]`);
  if (await preset.count()) await preset.click();
  else await page.locator("#heatmap-decay").evaluate((input, next) => {
    input.value = String(next);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, value);
  assert.equal(await page.inputValue("#heatmap-decay"), String(value));
  assert.equal(await page.textContent("#heatmap-decay-value"), `${value}%`);
}

async function waitForHistory(slug, firstValue) {
  await page.waitForFunction(({ slug: expected, first }) => {
    const app = document.getElementById("history-app");
    const cards = document.querySelectorAll("#result-grid .result-card");
    return app.dataset.slug === expected && cards.length === 1000 && Number(cards[0].dataset.value) === first
      && document.getElementById("result-grid").getAttribute("aria-busy") !== "true"
      && document.getElementById("live-status").dataset.state === "online";
  }, { slug, first: firstValue });
}

async function chooseRoulette(slug) {
  await page.click("#roulette-picker-open");
  await page.locator(`#roulette-list a[data-roulette-slug="${slug}"]`).click();
}

async function assertSelectionBet(index) {
  assert.deepEqual(await selection(index).locator("[data-bet-number]").evaluateAll((nodes) => nodes.map((node) => Number(node.dataset.betNumber))), bet,
    "a selection must use its earlier occurrence, not the next displayed number of the clicked result");
  assert.deepEqual(await selection(index).locator("[data-bet-number]").evaluateAll((nodes) => nodes.map((node) => [Number(node.dataset.betNumber), Number(node.dataset.numberWeight)])), [
    [3, 0.3], [5, 0.7], [7, 0.3], [8, 0.3], [10, 1], [12, 1], [23, 0.7], [24, 0.3], [28, 0.7], [35, 0.7],
  ], "the sorted bet must retain each pocket's center or neighbor weight");
  for (const side of ["left", "right"]) {
    assert.deepEqual(await selection(index).locator(`.wheel-pair-sector--${side} [data-number-weight]`).evaluateAll((nodes) => nodes.map((node) => Number(node.dataset.numberWeight))), [0.3, 0.7, 1, 0.7, 0.3],
      "each sector must show two lighter neighbors around its full-weight center");
  }
  assert.equal(await selection(index).locator(".wheel-pair-race .number-cell[data-n]").count(), 37, "each selection needs its own full racetrack");
  assert.equal(await selection(index).locator('.wheel-pair-race .number-cell[data-n="25"].wp-base').count(), 1);
  assert.equal(await selection(index).locator('.wheel-pair-race .number-cell[data-n="12"].wp-left').count(), 1);
  assert.equal(await selection(index).locator('.wheel-pair-race .number-cell[data-n="10"].wp-right').count(), 1);
}

try {
  await page.goto(`${origin}/contagem-casas?slug=${autoSlug}`);
  await waitForHistory(autoSlug, 1);
  assert.equal(historyCalls.length, 2, "initial subscription must reconcile the bootstrap window exactly once");
  assert.equal(await selectedCards().count(), 0);

  await result(1).focus();
  await page.keyboard.press("Enter");
  await page.waitForSelector('#wheel-pair-list .wheel-pair-card[data-selection-index="1"]');
  assert.equal(await result(1).getAttribute("aria-pressed"), "true", "native keyboard activation must select the exact occurrence");
  assert.equal(await result(4).getAttribute("aria-pressed"), "false", "another occurrence of 25 must remain unselected");
  await assertSelectionBet(1);
  assert.equal(await repeatedNumbers().count(), 0, "one bet alone must not produce repeated numbers");

  await result(4).click();
  assert.equal(await selectedCards().count(), 2, "two occurrences of the same base must coexist");
  await assertSelectionBet(4);
  assert.deepEqual(await repeatedNumbers().evaluateAll((nodes) => nodes.map((node) => [Number(node.dataset.repeatedNumber), Number(node.dataset.count)])), bet.map((number) => [number, 2]),
    "the summary counts presence once in each bet and sorts equal counts numerically");

  await result(1).focus();
  await page.keyboard.press("Space");
  assert.equal(await selectedCards().count(), 1, "keyboard toggle must remove only that occurrence");
  assert.equal(await selection(4).count(), 1);
  assert.equal(await result(1).getAttribute("aria-pressed"), "false");
  assert.equal(await repeatedNumbers().count(), 0);
  await result(1).click();

  // A new result shifts positions but must preserve the selected identities.
  await page.waitForFunction(() => document.getElementById("live-status-text")?.textContent !== "Conectando");
  const autoSocket = sockets.findLast((entry) => entry.slug === autoSlug);
  assert.ok(autoSocket, "the page must subscribe to its own table");
  autoSocket.socket.send(JSON.stringify({ result: 25, full_result: { _id: "auto-live-new", value: 25, roulette_id: autoSlug, timestamp: "2026-10-12T07:00:38Z" } }));
  await page.waitForFunction(() => document.querySelector('#result-grid .result-card[data-result-index="0"]')?.dataset.value === "25");
  assert.equal(await selectedCards().count(), 2);
  assert.equal(await result(0).getAttribute("aria-pressed"), "false", "a live 25 must not inherit another occurrence's selection");
  assert.equal(await result(2).getAttribute("aria-pressed"), "true");
  assert.equal(await result(5).getAttribute("aria-pressed"), "true");
  await assertSelectionBet(2);
  await assertSelectionBet(5);

  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    const dimensions = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth }));
    assert.ok(dimensions.scrollWidth <= dimensions.width, `page must fit ${viewport.width}px without horizontal overflow: ${JSON.stringify(dimensions)}`);
    assert.equal(await page.locator("#wheel-pair-panel").isVisible(), true, "the selected bets must remain available on mobile");
    if (viewport.width === 390) {
      assert.equal(await selection(2).locator(".wheel-pair-race .number-text").first().evaluate((node) => getComputedStyle(node).fontSize), "20px",
        "the shared racetrack plugin's injected mobile rule must not shrink the page's SVG number labels");
    }
    const screenshotDirectory = process.env.WHEEL_PAIR_BROWSER_SCREENSHOT_DIR;
    if (screenshotDirectory) {
      await fs.mkdir(screenshotDirectory, { recursive: true });
      await page.screenshot({ path: path.join(screenshotDirectory, `wheel-pair-${viewport.width}.png`), fullPage: true });
      await page.locator("#wheel-pair-summary").scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(screenshotDirectory, `wheel-pair-summary-${viewport.width}.png`), fullPage: true });
      await page.locator(".wheel-pair-scroll").evaluate((element) => { element.scrollTop = 0; });
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await selection(5).locator(".wheel-pair-card__remove").click();
  assert.equal(await selectedCards().count(), 1, "a sidebar remove button must remove only its own bet");
  assert.equal(await selection(2).count(), 1);
  assert.equal(await result(5).getAttribute("aria-pressed"), "false");
  assert.equal(await repeatedNumbers().count(), 0);
  await result(5).click();
  await page.keyboard.press("Escape");
  assert.equal(await page.locator("#wheel-pair-panel").isVisible(), false, "Escape must close the sidebar");
  assert.equal(await selectedCards().count(), 2, "Escape must preserve both selected bets");
  assert.equal(await result(5).evaluate((node) => node === document.activeElement), true, "Escape must return focus to the selected occurrence");
  await page.click("#selection-toggle");
  await page.click("#wheel-pair-close");
  assert.equal(await selectedCards().count(), 2, "closing the sidebar must preserve selections");
  await page.click("#selection-toggle");
  await page.click("#wheel-pair-clear");
  assert.equal(await selectedCards().count(), 0);
  assert.equal(await page.locator('#result-grid .result-card[aria-pressed="true"]').count(), 0);

  await page.click("#refresh-history");
  await waitForHistory(autoSlug, 1);
  await result(999).click();
  assert.equal(await selectedCards().count(), 1);
  assert.match(await selection(999).textContent(), /(?:nenhuma|não|sem).*(?:anterior|ocorrência)|(?:anterior|ocorrência).*(?:encontrad|disponível)/i,
    "a base with no older occurrence must show an explanation");
  assert.equal(await selection(999).locator("[data-bet-number]").count(), 0);
  assert.equal(await repeatedNumbers().count(), 0);

  // A table change clears the old selection even when the new request fails.
  nextHistory(megaSlug, { error: true });
  await chooseRoulette(megaSlug);
  await page.waitForFunction(() => !document.getElementById("page-message").hidden && document.getElementById("page-message").textContent.length > 0);
  assert.equal(await selectedCards().count(), 0);
  assert.equal(await page.locator("#result-grid .result-card").count(), 0, "failed table loading must not leave Auto results labelled as Mega");
  assert.match(await page.locator("#page-message").textContent(), /falha|carregar|possível|indisponível/i);
  await page.click("#refresh-history");
  await waitForHistory(megaSlug, 30);
  assert.equal(await selectedCards().count(), 0);

  // Resolve Mega after a newer Auto request: stale data must not replace Auto.
  await chooseRoulette(autoSlug);
  await waitForHistory(autoSlug, 1);
  await result(1).click();
  const staleMega = deferredHistory(megaSlug);
  await chooseRoulette(megaSlug);
  await staleMega.started;
  assert.equal(await selectedCards().count(), 0);
  await chooseRoulette(autoSlug);
  await waitForHistory(autoSlug, 1);
  await result(4).click();
  staleMega.release();
  await page.waitForTimeout(150);
  await waitForHistory(autoSlug, 1);
  assert.equal(new URL(page.url()).searchParams.get("slug"), autoSlug, "the URL must continue to identify the current table");
  assert.equal(await selectedCards().count(), 1, "a stale response must not clear a selection made on the current table");
  await assertSelectionBet(4);
  assert.match(await page.locator("#roulette-title").textContent(), /Auto/);

  fixtures.set(megaSlug, []);
  await chooseRoulette(megaSlug);
  await page.waitForFunction(() => !document.getElementById("empty-state").hidden
    && document.getElementById("result-grid").getAttribute("aria-busy") !== "true"
    && document.getElementById("live-status").dataset.state === "online");
  assert.equal(await page.locator("#result-grid .result-card").count(), 0);
  assert.equal(await selectedCards().count(), 0);
  assert.equal(await repeatedNumbers().count(), 0);

  // A round can land between the bootstrap request and opening the socket.
  // The subscribed snapshot must replace that initial, already stale window.
  const bootstrapWindow = fixtures.get(autoSlug);
  const initialMissedItems = [
    { _id: "auto-before-subscribe-newer", value: 34, roulette_id: autoSlug, timestamp: "2026-10-12T07:01:16Z" },
    { _id: "auto-before-subscribe-older", value: 10, roulette_id: autoSlug, timestamp: "2026-10-12T07:00:38Z" },
  ];
  const subscribedWindow = [...initialMissedItems, ...bootstrapWindow].slice(0, 1000);
  fixtures.set(autoSlug, subscribedWindow);
  nextHistory(autoSlug, { items: bootstrapWindow });
  nextHistory(autoSlug, { items: subscribedWindow });
  const historyCallsBeforeSubscribe = historyCalls.length;
  await chooseRoulette(autoSlug);
  await waitForHistory(autoSlug, 34);
  assert.equal(historyCalls.length, historyCallsBeforeSubscribe + 2, "bootstrap and subscribed synchronization must both run");
  await result(3).click();
  await result(6).click();
  await assertSelectionBet(3);
  await assertSelectionBet(6);

  // Redis Pub/Sub has no replay. Reconcile offline rounds and retain events
  // arriving while the reconciliation query itself is still in flight.
  const historyCallsBeforeReconnect = historyCalls.length;
  const disconnectedSocket = sockets.findLast((entry) => entry.slug === autoSlug);
  const missedItems = [
    { _id: "auto-offline-newer", value: 30, roulette_id: autoSlug, timestamp: "2026-10-12T07:02:32Z" },
    { _id: "auto-offline-older", value: 25, roulette_id: autoSlug, timestamp: "2026-10-12T07:01:54Z" },
  ];
  fixtures.set(autoSlug, [...missedItems, ...fixtures.get(autoSlug)].slice(0, 1000));
  const reconnectFetch = deferredHistory(autoSlug, { items: fixtures.get(autoSlug) });
  disconnectedSocket.socket.close({ code: 1012, reason: "Simulated offline rounds without replay" });
  await reconnectFetch.started;
  const reconnectedSocket = sockets.findLast((entry) => entry.slug === autoSlug);
  assert.notEqual(reconnectedSocket, disconnectedSocket);
  // One buffered event is already in the snapshot; the second is newer.
  reconnectedSocket.socket.send(JSON.stringify({ result: 30, full_result: missedItems[0] }));
  reconnectedSocket.socket.send(JSON.stringify({ result: 11, full_result: { _id: "auto-during-sync", value: 11, roulette_id: autoSlug, timestamp: "2026-10-12T07:03:10Z" } }));
  await page.waitForTimeout(50);
  reconnectFetch.release();
  await waitForHistory(autoSlug, 11);
  assert.equal(await selectedCards().count(), 2, "socket reconciliation must preserve selected result IDs");
  assert.equal(await result(6).getAttribute("aria-pressed"), "true");
  assert.equal(await result(9).getAttribute("aria-pressed"), "true");
  assert.equal(await result(6).getAttribute("data-result-id"), `${autoSlug}-1`);
  assert.equal(await result(9).getAttribute("data-result-id"), `${autoSlug}-4`);
  await assertSelectionBet(6);
  await assertSelectionBet(9);
  assert.equal(await page.locator('#result-grid [data-result-id="auto-offline-newer"]').count(), 1, "snapshot and buffered copies of the same result must be deduplicated");
  assert.equal(await page.locator('#result-grid [data-result-id="auto-during-sync"]').count(), 1, "a round arriving during synchronization must be retained");
  await result(2).click();
  assert.deepEqual(await selection(2).locator("[data-bet-number]").evaluateAll((nodes) => nodes.map((node) => Number(node.dataset.betNumber))), [2, 4, 6, 17, 21, 25, 34],
    "a round missed while offline must be selectable and use the reconciled earlier pair");
  assert.deepEqual(await selection(2).locator("[data-bet-number]").evaluateAll((nodes) => nodes.map((node) => [Number(node.dataset.betNumber), Number(node.dataset.numberWeight)])), [
    [2, 1], [4, 0.3], [6, 0.3], [17, 1], [21, 0.7], [25, 0.7], [34, 0.7],
  ], "overlapping sectors must keep the larger pocket weight once rather than adding both sides");
  assert.equal(await selectedCards().count(), 3);
  await page.waitForTimeout(250);
  assert.equal(historyCalls.length, historyCallsBeforeReconnect + 1,
    "reconnection must fetch one fresh window without creating a subscription refresh loop");

  // The automatic heatmap has its own ten occurrence window and searches the
  // full 1,000 results for their older pairs, independent of manual selections.
  await page.click("#wheel-pair-clear");
  const heatValues = [20, 20, 20, 20, 20, 20, 26, 2, 21, 25, 8, 25, 5, 21, 8, 2];
  heatValues.push(...Array(1000 - heatValues.length).fill(36));
  const heatItems = makeItems(autoSlug, heatValues).map((item, index) => ({ ...item, _id: `heat-auto-${index}` }));
  fixtures.set(autoSlug, heatItems);
  await page.click("#refresh-history");
  await waitForHistory(autoSlug, 20);
  assert.equal(await selectedCards().count(), 0);
  assert.equal(await page.inputValue("#heatmap-decay"), "100", "the heatmap starts with complete reduction after a hit");
  assert.equal(await page.textContent("#heatmap-decay-value"), "100%");
  assert.equal(await page.locator("#wheel-heatmap").isVisible(), true);
  assert.equal(await page.locator("#wheel-heatmap").evaluate((node) => node.parentElement.classList.contains("result-grid-viewport")
    && Boolean(node.compareDocumentPosition(document.getElementById("result-grid")) & Node.DOCUMENT_POSITION_FOLLOWING)), true,
  "the heatmap belongs before the results in the history viewport");
  assert.deepEqual((await heatSnapshot()).map(([number]) => number).sort((left, right) => left - right), Array.from({ length: 37 }, (_, index) => index));
  assert.equal(await page.locator("#heatmap-status").getAttribute("role"), "status");
  assert.match(await page.textContent("#heatmap-status"), /8 apostas analisadas/);
  assert.deepEqual(await page.locator("#heatmap-details tr[data-heat-source-index]").evaluateAll((rows) => rows.map((row) => Number(row.dataset.heatSourceIndex))), Array.from({ length: 10 }, (_, index) => index));
  assert.equal(await page.locator('#heatmap-details tr[data-heat-source-index="7"]').getAttribute("data-heat-hit-count"), "1");
  await assertHeat(26, 0, 3);

  const beforeManualSelection = await heatSnapshot();
  await result(7).click();
  await result(8).click();
  assert.equal(await selectedCards().count(), 2);
  assert.deepEqual(await heatSnapshot(), beforeManualSelection, "manual bets must not become additional heatmap sources");
  await page.click("#wheel-pair-clear");
  assert.deepEqual(await heatSnapshot(), beforeManualSelection, "clearing manual bets must preserve the automatic heatmap");

  const historyCallsBeforeDecay = historyCalls.length;
  await chooseDecay(0);
  await assertHeat(26, 2.4, 3);
  await assertPositiveHeatContrast();
  const fullColor = await heatCell(26).evaluate((node) => getComputedStyle(node.querySelector("path, rect")).fill);
  await chooseDecay(50);
  await assertHeat(26, 1.2, 3);
  await assertPositiveHeatContrast();
  const halfColor = await heatCell(26).evaluate((node) => getComputedStyle(node.querySelector("path, rect")).fill);
  await chooseDecay(100);
  await assertHeat(26, 0, 3);
  const zeroColor = await heatCell(26).evaluate((node) => getComputedStyle(node.querySelector("path, rect")).fill);
  assert.equal(new Set([fullColor, halfColor, zeroColor]).size, 3, "the rendered pocket color must cool as its absolute weight falls");
  await chooseDecay(25);
  await assertHeat(26, 1.8, 3);
  await assertPositiveHeatContrast();
  const ranking = await page.locator("#heatmap-ranking [data-heat-ranked-number]").evaluateAll((chips) => chips.map((chip) => ({ number: Number(chip.dataset.heatRankedNumber), weight: Number(chip.dataset.heatWeight) })));
  assert.equal(ranking.length, 8);
  assert.deepEqual(ranking, [...ranking].sort((left, right) => right.weight - left.weight || left.number - right.number));
  for (const ranked of ranking) assert.equal(Number(await heatCell(ranked.number).getAttribute("data-heat-weight")), ranked.weight);
  assert.equal(historyCalls.length, historyCallsBeforeDecay, "changing decay must use the already loaded snapshot");
  await chooseDecay(50);
  await assertHeat(26, 1.2, 3);
  await heatCell(26).click();
  assert.match(await page.textContent("#heatmap-pocket-info"), /26.*1,2.*3 apostas/);

  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.locator(".result-grid-viewport").evaluate((node) => { node.scrollTop = 0; });
    const dimensions = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth }));
    assert.ok(dimensions.scrollWidth <= dimensions.width, `heatmap must fit ${viewport.width}px without document overflow: ${JSON.stringify(dimensions)}`);
    assert.equal(await page.locator("#wheel-heatmap").isVisible(), true);
    const screenshotDirectory = process.env.WHEEL_PAIR_BROWSER_SCREENSHOT_DIR;
    if (screenshotDirectory) {
      await page.screenshot({ path: path.join(screenshotDirectory, `wheel-heatmap-${viewport.width}.png`), fullPage: true });
      await page.locator("#heatmap-details > summary").click();
      await page.screenshot({ path: path.join(screenshotDirectory, `wheel-heatmap-details-${viewport.width}.png`), fullPage: true });
      await page.locator("#heatmap-details > summary").click();
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });

  // A new 26 changes both the newest ten sources and their subsequent hits.
  // Two contributing bets remain, each with spatial weight 0.7 and two hits.
  const heatLiveItem = { _id: "heat-live-26", value: 26, roulette_id: autoSlug, timestamp: "2026-10-12T07:00:38Z" };
  fixtures.set(autoSlug, [heatLiveItem, ...heatItems].slice(0, 1000));
  const heatSocket = sockets.findLast((entry) => entry.slug === autoSlug);
  heatSocket.socket.send(JSON.stringify({ result: 26, full_result: heatLiveItem }));
  await waitForHistory(autoSlug, 26);
  await assertHeat(26, 0.35, 2);
  assert.equal(await page.locator('#heatmap-details tr[data-heat-source-index="0"]').getAttribute("data-heat-source-id"), "heat-live-26");
  heatSocket.socket.send(JSON.stringify({ result: 26, full_result: heatLiveItem }));
  await page.waitForTimeout(50);
  await assertHeat(26, 0.35, 2);
  assert.equal(await page.locator('#result-grid [data-result-id="heat-live-26"]').count(), 1, "duplicate live events must not add a heatmap source or another hit");
  assert.equal(await selectedCards().count(), 0, "automatic heatmap updates must not select manual bets");

  // Reconnection contributes a missed zero: the one remaining contributing
  // bet has spatial weight 0.7 and three hits: 0.7 * (1 - 0.5)^3 = 0.0875.
  const heatMissedItem = { _id: "heat-offline-0", value: 0, roulette_id: autoSlug, timestamp: "2026-10-12T07:01:16Z" };
  fixtures.set(autoSlug, [heatMissedItem, ...fixtures.get(autoSlug)].slice(0, 1000));
  const callsBeforeHeatReconnect = historyCalls.length;
  heatSocket.socket.close({ code: 1012, reason: "Heatmap fixture missed a round" });
  await waitForHistory(autoSlug, 0);
  await assertHeat(26, 0.0875, 1);
  assert.equal(await page.inputValue("#heatmap-decay"), "50");
  assert.equal(historyCalls.length, callsBeforeHeatReconnect + 1);

  const emptyHeatTable = deferredHistory(megaSlug, { items: [] });
  await chooseRoulette(megaSlug);
  await emptyHeatTable.started;
  assert.equal(await page.locator("#wheel-heatmap").isVisible(), false, "switching tables must immediately hide the previous table's heatmap");
  assert.equal(await page.inputValue("#heatmap-decay"), "50", "the global decay preference must survive table changes");
  emptyHeatTable.release();
  await page.waitForFunction(() => document.getElementById("live-status").dataset.state === "online"
    && document.getElementById("result-grid").getAttribute("aria-busy") !== "true");
  assert.equal(await page.locator("#wheel-heatmap").isVisible(), false);
  await chooseRoulette(autoSlug);
  await waitForHistory(autoSlug, 0);
  await assertHeat(26, 0.0875, 1);

  // The selected occurrence is the trigger, not a subsequent hit. With a zero
  // offset, base 25 belongs to its own five-number bet but must retain weight 1.
  const selfValues = [25, 0, 25, ...Array(997).fill(36)];
  fixtures.set(autoSlug, makeItems(autoSlug, selfValues).map((item, index) => ({ ...item, _id: `heat-self-${index}` })));
  await page.click("#refresh-history");
  await waitForHistory(autoSlug, 25);
  await chooseDecay(100);
  await assertHeat(25, 1, 1);
  assert.equal(await page.locator('#heatmap-details tr[data-heat-source-index="0"]').getAttribute("data-heat-hit-count"), "0");
  assert.equal(await page.locator('#heatmap-details tr[data-heat-source-index="0"]').getAttribute("data-heat-source-weight"), "1");
  await chooseDecay(25);
  await page.reload();
  await waitForHistory(autoSlug, 25);
  assert.equal(await page.inputValue("#heatmap-decay"), "25", "a reload must restore the saved decay preference");
  assert.equal(await page.textContent("#heatmap-decay-value"), "25%");
  await assertHeat(25, 1, 1);

  // Ten overlapping, unreduced bets reach the darkest end of the heat scale.
  // Its label must remain readable without tying the test to black or white ink.
  fixtures.set(autoSlug, makeItems(autoSlug, Array(1000).fill(36)).map((item, index) => ({ ...item, _id: `heat-maximum-${index}` })));
  await page.click("#refresh-history");
  await waitForHistory(autoSlug, 36);
  await chooseDecay(0);
  await assertHeat(11, 10, 10);
  await assertHeat(13, 10, 10);
  await assertHeat(36, 7, 10);
  await assertHeat(6, 3, 10);
  await assertPositiveHeatContrast();
  await heatCell(11).click();
  await page.locator("#heatmap-title").hover();
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.locator(".result-grid-viewport").evaluate((node) => { node.scrollTop = 0; });
    const screenshotDirectory = process.env.WHEEL_PAIR_BROWSER_SCREENSHOT_DIR;
    if (screenshotDirectory) await page.screenshot({ path: path.join(screenshotDirectory, `wheel-heatmap-maximum-${viewport.width}.png`), fullPage: true });
  }

  assert.deepEqual(routeErrors, [], "all browser fixture requests must succeed or be explicitly simulated failures");
  assert.deepEqual(pageErrors, [], "the page must not emit JavaScript errors");
  console.log(JSON.stringify({ status: "wheel-pair-browser-tests: ok", historyCalls: historyCalls.length, resultsPerTable: 1000, minimumActivePocketContrast: Math.min(...contrastChecks) }));
} finally {
  await browser.close();
}
