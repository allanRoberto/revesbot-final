import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("../../../bot_automatico/node_modules/playwright");
const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const apiDirectory = path.resolve(testDirectory, "../..");
const templatePath = path.join(apiDirectory, "templates/jev.html");
const scriptPath = path.join(apiDirectory, "static/js/pages/jev.js");
const stylePath = path.join(apiDirectory, "static/css/jev.css");

const rawTemplate = await fs.readFile(templatePath, "utf8");
const pageHtml = rawTemplate
  .replaceAll("{{ asset_version }}", "browser-test")
  .replaceAll("{{ csrf_token }}", "csrf-browser-test")
  .replaceAll("{{ max_history }}", "10000")
  .replaceAll("{{ suggested_history }}", "300");

let historyCalls = 0;
let analysisCalls = 0;
let analysisBody = null;
let failNextAnalysis = false;
let rankingCalls = 0;
let rankingBody = null;
let evaluationCalls = 0;
let evaluationBody = null;

const systemChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const browser = await chromium.launch({
  headless: true,
  executablePath: systemChrome,
});
const page = await browser.newPage();

await page.route("http://jev.test/**", async (route) => {
  const request = route.request();
  const url = new URL(request.url());
  if (url.pathname === "/jev") {
    await route.fulfill({ status: 200, contentType: "text/html", body: pageHtml });
    return;
  }
  if (url.pathname === "/static/js/pages/jev.js") {
    await route.fulfill({ status: 200, contentType: "application/javascript", path: scriptPath });
    return;
  }
  if (url.pathname === "/static/css/jev.css") {
    await route.fulfill({ status: 200, contentType: "text/css", path: stylePath });
    return;
  }
  if (url.pathname === "/api/jev/historico") {
    historyCalls += 1;
    assert.equal(url.searchParams.get("quantidade"), "3");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        roulette_slug: "pragmatic-auto-roulette",
        quantidade_solicitada: 3,
        quantidade_retornada: 3,
        history_order: "oldest_to_newest",
        historico: [1, 7, 0],
        buscado_em: "2026-09-25T12:00:00Z",
        ultimo_resultado_em: "2026-09-25T11:59:55Z",
      }),
    });
    return;
  }
  if (url.pathname === "/api/jev/analisar") {
    analysisCalls += 1;
    analysisBody = request.postDataJSON();
    await new Promise((resolve) => setTimeout(resolve, 120));
    if (failNextAnalysis) {
      failNextAnalysis = false;
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({ detail: { code: "openrouter_http_error", message: "Falha simulada do provedor." } }),
      });
      return;
    }
    const groups = Object.entries(analysisBody.grupos);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        analysis_id: "analysis-browser-test",
        roulette_slug: "pragmatic-auto-roulette",
        history_order: "oldest_to_newest",
        historico_utilizado: [9, 7, 7, 0],
        quantidade_analisada: 4,
        ultimo_numero: 0,
        forecast_horizon_spins: 3,
        modelo_solicitado: "typesafe/jev-1.13",
        modelo_retornado: "typesafe/jev-1.13-returned",
        solicitado_em: "2026-09-25T12:01:00Z",
        respondido_em: "2026-09-25T12:01:00Z",
        latencia_ms: 12,
        resultados: groups.map(([group, numbers], index) => ({
          grupo: group,
          numeros: numbers,
          estimativa_jev_nao_validada: (index + 1) / 10,
          probabilidade_base: 0.41186109411091154,
        })),
        resposta_jev: { id: "gen-test", usage: { cost: 0 } },
        avisos: [],
      }),
    });
    return;
  }
  if (url.pathname === "/api/jev/ranking") {
    rankingCalls += 1;
    rankingBody = request.postDataJSON();
    await new Promise((resolve) => setTimeout(resolve, 120));
    const ranking = Array.from({ length: 37 }, (_unused, index) => {
      const number = index === 0 ? 0 : index;
      return {
        posicao: index + 1,
        numero: number,
        estimativa_jev_nao_validada: index === 0 ? 0.19 : 0.12 - index / 1000,
        probabilidade_base: 0.07890944267861726,
        diferenca_da_base: (index === 0 ? 0.19 : 0.12 - index / 1000) - 0.07890944267861726,
        lift_jev_sobre_base: 1.1,
        probabilidade_proxima_rodada: index === 0 ? 0.2 : 0.8 / 36,
        posicao_proxima_rodada: index + 1,
        relacao_do_ultimo_numero: {
          source_number: 0,
          target_number: number,
          support: 40,
          hits: index === 0 ? 8 : 3,
          lift_vs_baseline: index === 0 ? 1.6 : 1.0,
          classification: index === 0 ? "stable_positive_pull" : "neutral_relation",
        },
        padroes_associados: [],
      };
    });
    const immediateRanking = Array.from({ length: 37 }, (_unused, number) => ({
      posicao: number + 1,
      numero: number,
      probabilidade: number === 0 ? 0.2 : 0.8 / 36,
      probabilidade_base: 1 / 37,
      diferenca_da_base: (number === 0 ? 0.2 : 0.8 / 36) - 1 / 37,
    }));
    const metaRanking = ranking.map((item) => ({
      posicao: item.posicao,
      numero: item.numero,
      probabilidade_meta: item.estimativa_jev_nao_validada,
      probabilidade_jev: item.estimativa_jev_nao_validada,
      probabilidade_calibrada_deterministica: item.estimativa_jev_nao_validada,
      probabilidade_base: item.probabilidade_base,
      diferenca_da_base: item.diferenca_da_base,
      lift_sobre_base: item.estimativa_jev_nao_validada / item.probabilidade_base,
      confiabilidade_meta: item.numero === 0 ? 0.62 : 0.28,
      status_validacao: item.numero === 0 ? "validated" : "experimental",
      amostras_walk_forward: 40,
      modelos_walk_forward: {},
    }));
    const metaImmediateRanking = immediateRanking.map((item) => ({
      posicao: item.posicao,
      numero: item.numero,
      probabilidade_meta: item.probabilidade,
      probabilidade_jev: item.probabilidade,
      probabilidade_calibrada_deterministica: item.probabilidade,
      probabilidade_base: item.probabilidade_base,
      diferenca_da_base: item.diferenca_da_base,
      lift_sobre_base: item.probabilidade / item.probabilidade_base,
      confiabilidade_meta: item.numero === 0 ? 0.62 : 0.28,
      status_validacao: item.numero === 0 ? "validated" : "experimental",
      amostras_walk_forward: 40,
      modelos_walk_forward: {},
    }));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        analysis_id: "ranking-browser-test",
        analysis_type: "number_ranking",
        quantidade_analisada: 4,
        ultimo_numero: 0,
        forecast_horizon_spins: 3,
        modelo_retornado: "typesafe/jev-1.13-returned",
        respondido_em: "2026-09-25T12:02:00Z",
        latencia_ms: 18,
        ranking,
        ranking_proxima_rodada: immediateRanking,
        ranking_meta: metaRanking,
        ranking_meta_proxima_rodada: metaImmediateRanking,
        sinal_meta: {
          status: "validated",
          available: true,
          reason: "Há candidatos validados.",
          validated_numbers: [0],
          coverage: 1 / 37,
          regime: "transition_driven",
        },
        validacao_walk_forward: {
          version: "source_conditioned_v1",
          method: "chronological_source_conditioned_no_future_leakage",
          minimum_training_support: 12,
          maximum_recent_samples_per_model: 300,
        },
        proxima_rodada: {
          numero_escolhido: 0,
          confidence: 0.72,
          probabilities: Object.fromEntries(immediateRanking.map((item) => [String(item.numero), item.probabilidade])),
        },
        proxima_rodada_meta: {
          numero_escolhido: 0,
          probabilidade: 0.2,
          confiabilidade_meta: 0.62,
          status_validacao: "validated",
        },
        regime_atual: {
          choice: "transition_driven",
          confidence: 0.64,
          probabilities: { neutral: 0.1, frequency_concentration: 0.1, transition_driven: 0.6, gap_driven: 0.1, unstable: 0.1 },
        },
        catalogo_padroes: [{
          relation_id: "pull:0->0:h3",
          source_number: 0,
          target_number: 0,
          classification: "stable_positive_pull",
          support: 40,
          hits: 8,
          lift_vs_baseline: 1.6,
          qualidade_jev: { score: 2.6, score_normalizado: 2.6 / 3, confidence: 0.82, probabilities: { 0: 0.02, 1: 0.08, 2: 0.18, 3: 0.72 }, legend: {} },
        }],
        resposta_jev: { id: "gen-ranking", usage: { cost: 0 } },
        avisos: [],
      }),
    });
    return;
  }
  if (url.pathname === "/api/jev/avaliar") {
    evaluationCalls += 1;
    evaluationBody = request.postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        evaluation_id: "evaluation-browser-test",
        analysis_id: evaluationBody.analysis_id,
        metricas_tres_rodadas: {
          brier_medio_37_numeros: 0.071234,
          log_loss_binario_medio_37_numeros: 0.245678,
          acertos_por_corte: { top_1: true, top_3: true, top_5: true, top_10: true },
          posicoes_dos_resultados_reais: [],
        },
        metrica_proxima_rodada: {
          numero_escolhido: 0,
          numero_real: 0,
          acertou_escolha: true,
          posicao_do_numero_real: 1,
          probabilidade_do_numero_real: 0.2,
        },
        metricas_meta_tres_rodadas: {
          brier_medio_37_numeros: 0.061234,
          log_loss_binario_medio_37_numeros: 0.225678,
          acertos_por_corte: { top_1: true, top_3: true, top_5: true, top_10: true },
          posicoes_dos_resultados_reais: [],
        },
        comparacao_meta_vs_jev: {
          ganho_brier: 0.01,
          ganho_log_loss: 0.02,
          positivo_significa_meta_melhor: true,
          sinal_meta_disponivel_na_previsao: true,
        },
        avisos: [],
      }),
    });
    return;
  }
  await route.fulfill({ status: 404, body: "not found" });
});

try {
  await page.goto("http://jev.test/jev");
  assert.equal(historyCalls, 0, "opening the page must not fetch history");
  assert.equal(analysisCalls, 0, "opening the page must not call Jev");
  assert.equal(rankingCalls, 0, "opening the page must not call ranking");

  await page.click("#open-history-dialog");
  assert.equal(await page.locator("#history-dialog").evaluate((element) => element.open), true);
  await page.click("#cancel-history-dialog");
  assert.equal(historyCalls, 0, "opening and cancelling the dialog must not fetch");

  await page.click("#open-history-dialog");
  await page.fill("#history-quantity", "3");
  await page.click("#confirm-history-fetch");
  await page.waitForFunction(() => document.getElementById("history-input").value === "1, 7, 0");
  assert.equal(historyCalls, 1, "confirming must fetch exactly once");

  await page.fill("#history-input", "9, 7, 7, 0");
  assert.equal(await page.textContent("#history-origin"), "Histórico editado manualmente.");
  assert.equal(await page.isEnabled("#analyze-button"), true);

  await page.locator("#analyze-button").evaluate((button) => {
    button.click();
    button.click();
  });
  await page.waitForSelector("#results-section:not([hidden])");
  assert.equal(analysisCalls, 1, "double click must result in one paid request");
  assert.equal(analysisBody.historico_texto, "9, 7, 7, 0");
  assert.equal(analysisBody.history_order, "oldest_to_newest");
  assert.equal(await page.locator("#results-body tr").count(), 6);
  assert.equal(await page.isVisible("#result-cost-row"), true, "zero cost must remain visible");

  await page.locator("#ranking-button").evaluate((button) => {
    button.click();
    button.click();
  });
  await page.waitForSelector("#ranking-results-section:not([hidden])");
  assert.equal(rankingCalls, 1, "double click must result in one paid ranking request");
  assert.deepEqual(Object.keys(rankingBody).sort(), ["historico_texto", "history_order"]);
  assert.equal(rankingBody.historico_texto, "9, 7, 7, 0");
  assert.equal(await page.locator("#ranking-results-body tr").count(), 37);
  assert.equal(await page.textContent("#ranking-results-body tr:first-child .ranking-number"), "0");
  assert.equal(await page.locator("#ranking-catalog-body tr").count(), 1);
  assert.equal(await page.isVisible("#ranking-result-cost-row"), true, "zero ranking cost must remain visible");
  assert.match(await page.textContent("#ranking-next-choice"), /Meta 0/);
  assert.match(await page.textContent("#ranking-regime"), /transições/);
  assert.match(await page.textContent("#ranking-meta-signal"), /validado/);
  assert.equal(await page.inputValue("#ranking-view"), "meta_three");

  await page.selectOption("#ranking-pattern-filter", "zero");
  assert.equal(await page.locator("#ranking-results-body tr").count(), 1, "zero filter must keep only zero");
  await page.selectOption("#ranking-pattern-filter", "all");
  await page.selectOption("#ranking-validation-filter", "validated");
  assert.equal(await page.locator("#ranking-results-body tr").count(), 1, "validation filter must keep validated rows");
  await page.selectOption("#ranking-validation-filter", "all");
  await page.selectOption("#ranking-view", "next_one");
  assert.match(await page.textContent("#ranking-estimate-heading"), /próxima rodada/);
  assert.equal(await page.textContent("#ranking-results-body tr:first-child .ranking-number"), "0");

  await page.fill("#ranking-actual-results", "0, 7, 17");
  await page.click("#ranking-evaluate-button");
  await page.waitForSelector("#ranking-evaluation-results:not([hidden])");
  assert.equal(evaluationCalls, 1, "manual evaluation must use one non-paid endpoint call");
  assert.equal(evaluationBody.analysis_id, "ranking-browser-test");
  assert.match(await page.textContent("#evaluation-next-hit"), /Acertou/);
  assert.match(await page.textContent("#evaluation-meta-comparison"), /Brier/);

  await page.fill("#grupo_1", "0, 1, 2");
  assert.equal(await page.isVisible("#result-stale"), true);
  assert.equal(await page.isVisible("#ranking-result-stale"), false, "group edits must not stale the independent ranking");
  failNextAnalysis = true;
  await page.click("#analyze-button");
  await page.waitForFunction(() => !document.getElementById("operation-error").hidden);
  assert.equal(await page.isEnabled("#history-input"), true, "controls must recover after an error");
  assert.equal(await page.isEnabled("#analyze-button"), true);
  assert.match(await page.textContent("#operation-error"), /Falha simulada/);

  await page.waitForTimeout(250);
  assert.equal(historyCalls, 1, "there must be no periodic history refresh");
  assert.equal(analysisCalls, 2, "there must be no automatic analysis retry");
  assert.equal(rankingCalls, 1, "there must be no automatic ranking retry");
  assert.equal(evaluationCalls, 1, "there must be no automatic evaluation retry");
  console.log("jev-browser-tests: ok");
} finally {
  await browser.close();
}
