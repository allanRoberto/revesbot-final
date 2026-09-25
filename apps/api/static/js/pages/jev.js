(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const groupIds = ["grupo_1", "grupo_2", "grupo_3", "grupo_4", "grupo_5", "grupo_6"];
  const maxHistory = Number(document.querySelector('meta[name="jev-max-history"]').content);
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const form = byId("jev-form");
  const historyInput = byId("history-input");
  const analyzeButton = byId("analyze-button");
  const rankingButton = byId("ranking-button");
  const dialog = byId("history-dialog");
  const quantityInput = byId("history-quantity");
  const operationStatus = byId("operation-status");
  const operationError = byId("operation-error");
  let busy = false;
  let historyEdited = false;

  function parseSequence(text, label) {
    const stripped = text.replace(/^[ ,;\t\r\n]+|[ ,;\t\r\n]+$/g, "");
    if (!stripped) return { values: [], error: "" };
    const tokens = stripped.split(/[ ,;\t\r\n]+/);
    const values = [];
    for (let index = 0; index < tokens.length; index += 1) {
      const token = tokens[index];
      if (!/^[0-9]+$/.test(token)) {
        return { values: [], error: `${label} contém um valor inválido na posição ${index + 1}: “${token}”.` };
      }
      const number = Number(token);
      if (!Number.isSafeInteger(number) || number < 0 || number > 36) {
        return { values: [], error: `${label} contém um número fora do intervalo de 0 a 36 na posição ${index + 1}.` };
      }
      values.push(number);
    }
    return { values, error: "" };
  }

  function setOperation(message, error = "") {
    operationStatus.textContent = message;
    operationError.textContent = error;
    operationError.hidden = !error;
  }

  function markResultStale(scope = "all") {
    if ((scope === "all" || scope === "groups") && !byId("results-section").hidden) {
      byId("result-stale").hidden = false;
    }
    if ((scope === "all" || scope === "ranking") && !byId("ranking-results-section").hidden) {
      byId("ranking-result-stale").hidden = false;
    }
  }

  function validateForm() {
    const parsedHistory = parseSequence(historyInput.value, "Histórico");
    const historyError = parsedHistory.error || (parsedHistory.values.length === 0 ? "O histórico não pode estar vazio." : "")
      || (parsedHistory.values.length > maxHistory ? `O histórico excede o limite de ${maxHistory} números.` : "");
    byId("history-error").textContent = historyError;
    byId("history-error").hidden = !historyError;
    historyInput.setAttribute("aria-invalid", String(Boolean(historyError)));
    byId("current-count").textContent = historyError ? "—" : String(parsedHistory.values.length);
    byId("current-last").textContent = historyError || parsedHistory.values.length === 0
      ? "—" : String(parsedHistory.values[parsedHistory.values.length - 1]);

    const groups = {};
    let groupError = false;
    groupIds.forEach((groupId, index) => {
      const input = byId(groupId);
      const parsed = parseSequence(input.value, `Grupo ${index + 1}`);
      let error = parsed.error;
      if (!error && parsed.values.length === 0) error = `Grupo ${index + 1} não pode estar vazio.`;
      if (!error && new Set(parsed.values).size !== parsed.values.length) error = `Grupo ${index + 1} contém números repetidos.`;
      byId(`${groupId}_error`).textContent = error;
      input.setAttribute("aria-invalid", String(Boolean(error)));
      if (error) groupError = true;
      groups[groupId] = parsed.values;
    });
    const rankingValid = !historyError;
    const valid = rankingValid && !groupError;
    rankingButton.disabled = busy || !rankingValid;
    analyzeButton.disabled = busy || !valid;
    return { valid, rankingValid, history: parsedHistory.values, groups };
  }

  function setBusy(nextBusy, label = "") {
    busy = nextBusy;
    document.querySelectorAll(".editable-control, [data-operation-control]").forEach((control) => {
      control.disabled = nextBusy;
    });
    byId("analyze-label").textContent = nextBusy && label === "analysis" ? "Analisando grupos..." : "Analisar seis grupos";
    byId("ranking-label").textContent = nextBusy && label === "ranking" ? "Gerando ranking..." : "Gerar ranking 0–36";
    byId("open-history-dialog").textContent = nextBusy && label === "history" ? "Buscando números..." : "Buscar números";
    if (!nextBusy) validateForm();
  }

  function formatDate(value) {
    if (!value) return "Não informado";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Não informado";
    return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "medium" }).format(date);
  }

  function responseMessage(data, fallback) {
    const detail = data && typeof data === "object" ? data.detail : null;
    if (detail && typeof detail === "object" && typeof detail.message === "string") return detail.message;
    if (data && typeof data.message === "string") return data.message;
    return fallback;
  }

  async function readResponse(response) {
    let data;
    try {
      data = await response.json();
    } catch (_error) {
      throw new Error("A API retornou uma resposta que não é JSON válido.");
    }
    if (!response.ok) throw new Error(responseMessage(data, "A operação não pôde ser concluída."));
    return data;
  }

  async function fetchHistory(event) {
    event.preventDefault();
    if (busy) return;
    const quantity = quantityInput.valueAsNumber;
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > maxHistory) {
      byId("quantity-error").textContent = `Informe um inteiro entre 1 e ${maxHistory}.`;
      byId("quantity-error").hidden = false;
      quantityInput.focus();
      return;
    }
    byId("quantity-error").hidden = true;
    dialog.close();
    const previousText = historyInput.value;
    setBusy(true, "history");
    setOperation("Buscando números...");
    try {
      const response = await fetch(`/api/jev/historico?quantidade=${encodeURIComponent(String(quantity))}`, {
        method: "GET",
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
      });
      const data = await readResponse(response);
      if (!data || data.roulette_slug !== "pragmatic-auto-roulette"
          || data.history_order !== "oldest_to_newest" || !Array.isArray(data.historico)
          || !data.historico.every((number) => Number.isInteger(number) && number >= 0 && number <= 36)) {
        throw new Error("A API retornou um histórico inválido.");
      }
      historyInput.value = data.historico.join(", ");
      historyEdited = false;
      byId("history-origin").textContent = data.historico.length
        ? "Histórico carregado do servidor; revise antes de analisar."
        : "A busca foi concluída, mas nenhum resultado estava disponível.";
      byId("fetch-metadata").hidden = false;
      byId("fetched-requested").textContent = String(data.quantidade_solicitada);
      byId("fetched-returned").textContent = String(data.quantidade_retornada);
      byId("fetched-at").textContent = formatDate(data.buscado_em);
      byId("last-result-row").hidden = !data.ultimo_resultado_em;
      byId("last-result-at").textContent = formatDate(data.ultimo_resultado_em);
      const fewer = data.quantidade_retornada < data.quantidade_solicitada;
      byId("fetch-note").hidden = !fewer;
      byId("fetch-note").textContent = data.quantidade_retornada === 0
        ? "A fonte não retornou resultados para esta busca."
        : `A fonte retornou ${data.quantidade_retornada} de ${data.quantidade_solicitada} números solicitados.`;
      byId("results-section").hidden = true;
      byId("result-stale").hidden = true;
      byId("ranking-results-section").hidden = true;
      byId("ranking-result-stale").hidden = true;
      setOperation(data.historico.length ? "Busca concluída. Você pode revisar e editar o histórico." : "Busca concluída sem resultados.");
    } catch (error) {
      historyInput.value = previousText;
      setOperation("A atualização do histórico falhou.", error instanceof Error ? error.message : "Falha inesperada na busca.");
    } finally {
      setBusy(false);
    }
  }

  function appendCell(row, value) {
    const cell = document.createElement("td");
    cell.textContent = value;
    row.append(cell);
    return cell;
  }

  function renderAnalysis(data) {
    if (!data || !Array.isArray(data.resultados) || data.resultados.length !== 6) {
      throw new Error("A API retornou uma análise incompleta.");
    }
    const percent = new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const fragment = document.createDocumentFragment();
    data.resultados.forEach((result, index) => {
      const expectedGroup = groupIds[index];
      if (!result || result.grupo !== expectedGroup || !Array.isArray(result.numeros)
          || typeof result.estimativa_jev_nao_validada !== "number"
          || typeof result.probabilidade_base !== "number") {
        throw new Error("A API retornou um resultado de grupo inválido.");
      }
      const row = document.createElement("tr");
      appendCell(row, `Grupo ${index + 1}`);
      appendCell(row, result.numeros.join(", "));
      appendCell(row, percent.format(result.estimativa_jev_nao_validada));
      appendCell(row, percent.format(result.probabilidade_base));
      fragment.append(row);
    });
    byId("results-body").replaceChildren(fragment);
    byId("result-count").textContent = String(data.quantidade_analisada);
    byId("result-last").textContent = String(data.ultimo_numero);
    byId("result-horizon").textContent = `${data.forecast_horizon_spins} rodadas`;
    byId("result-model").textContent = data.modelo_retornado || "Não informado";
    byId("result-at").textContent = formatDate(data.respondido_em);
    byId("result-latency").textContent = `${data.latencia_ms} ms`;

    const usage = data.resposta_jev && typeof data.resposta_jev === "object" ? data.resposta_jev.usage : null;
    const hasCost = usage && typeof usage === "object"
      && Object.prototype.hasOwnProperty.call(usage, "cost") && typeof usage.cost === "number";
    byId("result-cost-row").hidden = !hasCost;
    byId("result-cost").textContent = hasCost
      ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 6 }).format(usage.cost)
      : "—";

    const warnings = Array.isArray(data.avisos) ? data.avisos : [];
    const warningNodes = warnings.map((warning) => {
      const item = document.createElement("li");
      item.textContent = String(warning);
      return item;
    });
    byId("analysis-warnings").replaceChildren(...warningNodes);
    byId("analysis-warnings").hidden = warningNodes.length === 0;
    byId("jev-json").textContent = JSON.stringify(data.resposta_jev, null, 2);
    byId("result-stale").hidden = true;
    byId("results-section").hidden = false;
  }

  function patternLabel(value) {
    const labels = {
      stable_positive_pull: "atração positiva estável",
      positive_pull: "atração positiva",
      recent_positive_pull: "atração positiva recente",
      stable_negative_relation: "relação negativa estável",
      recent_negative_relation: "relação negativa recente",
      unstable_relation: "relação instável",
      neutral_relation: "relação neutra",
      low_support: "suporte insuficiente",
    };
    return labels[value] || String(value || "não classificada");
  }

  function renderRanking(data) {
    if (!data || data.analysis_type !== "number_ranking"
        || !Array.isArray(data.ranking) || data.ranking.length !== 37
        || !Array.isArray(data.catalogo_padroes)) {
      throw new Error("A API retornou um ranking incompleto.");
    }
    const percent = new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const decimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const seenNumbers = new Set();
    const rankingFragment = document.createDocumentFragment();
    data.ranking.forEach((result, index) => {
      const relation = result && result.relacao_do_ultimo_numero;
      if (!result || result.posicao !== index + 1 || !Number.isInteger(result.numero)
          || result.numero < 0 || result.numero > 36 || seenNumbers.has(result.numero)
          || typeof result.estimativa_jev_nao_validada !== "number"
          || typeof result.probabilidade_base !== "number"
          || typeof result.diferenca_da_base !== "number"
          || !relation || relation.target_number !== result.numero
          || !Number.isInteger(relation.source_number)) {
        throw new Error("A API retornou um item inválido no ranking.");
      }
      seenNumbers.add(result.numero);
      const row = document.createElement("tr");
      appendCell(row, String(result.posicao));
      const numberCell = appendCell(row, String(result.numero));
      numberCell.classList.add("ranking-number");
      if (result.numero === 0) numberCell.classList.add("zero-number");
      appendCell(row, percent.format(result.estimativa_jev_nao_validada));
      appendCell(row, percent.format(result.probabilidade_base));
      const difference = percent.format(Math.abs(result.diferenca_da_base));
      appendCell(row, `${result.diferenca_da_base >= 0 ? "+" : "−"}${difference}`);
      appendCell(
        row,
        `${relation.source_number} → ${relation.target_number} · ${patternLabel(relation.classification)} · suporte ${relation.support}`,
      );
      rankingFragment.append(row);
    });
    if (seenNumbers.size !== 37 || !seenNumbers.has(0)) {
      throw new Error("O ranking não contém todos os números de 0 a 36.");
    }
    byId("ranking-results-body").replaceChildren(rankingFragment);

    const catalogFragment = document.createDocumentFragment();
    data.catalogo_padroes.forEach((pattern) => {
      if (!pattern || !Number.isInteger(pattern.source_number)
          || !Number.isInteger(pattern.target_number)
          || typeof pattern.estimativa_jev_relevancia !== "number") {
        throw new Error("A API retornou um padrão catalogado inválido.");
      }
      const row = document.createElement("tr");
      appendCell(row, `${pattern.source_number} → ${pattern.target_number}`);
      appendCell(row, patternLabel(pattern.classification));
      appendCell(row, String(pattern.support));
      appendCell(row, String(pattern.hits));
      appendCell(row, decimal.format(pattern.lift_vs_baseline));
      appendCell(row, percent.format(pattern.estimativa_jev_relevancia));
      catalogFragment.append(row);
    });
    byId("ranking-catalog-body").replaceChildren(catalogFragment);
    byId("ranking-catalog-empty").hidden = data.catalogo_padroes.length !== 0;
    byId("ranking-catalog-table").hidden = data.catalogo_padroes.length === 0;

    byId("ranking-result-count").textContent = String(data.quantidade_analisada);
    byId("ranking-result-source").textContent = String(data.ultimo_numero);
    byId("ranking-result-horizon").textContent = `${data.forecast_horizon_spins} rodadas`;
    byId("ranking-result-model").textContent = data.modelo_retornado || "Não informado";
    byId("ranking-result-at").textContent = formatDate(data.respondido_em);
    byId("ranking-result-latency").textContent = `${data.latencia_ms} ms`;
    byId("ranking-pattern-count").textContent = String(data.catalogo_padroes.length);

    const usage = data.resposta_jev && typeof data.resposta_jev === "object" ? data.resposta_jev.usage : null;
    const hasCost = usage && typeof usage === "object"
      && Object.prototype.hasOwnProperty.call(usage, "cost") && typeof usage.cost === "number";
    byId("ranking-result-cost-row").hidden = !hasCost;
    byId("ranking-result-cost").textContent = hasCost
      ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 6 }).format(usage.cost)
      : "—";

    const warnings = Array.isArray(data.avisos) ? data.avisos : [];
    const warningNodes = warnings.map((warning) => {
      const item = document.createElement("li");
      item.textContent = String(warning);
      return item;
    });
    byId("ranking-warnings").replaceChildren(...warningNodes);
    byId("ranking-warnings").hidden = warningNodes.length === 0;
    byId("ranking-jev-json").textContent = JSON.stringify(data.resposta_jev, null, 2);
    byId("ranking-result-stale").hidden = true;
    byId("ranking-results-section").hidden = false;
  }

  async function rankNumbers() {
    if (busy) return;
    const current = validateForm();
    if (!current.rankingValid) return;
    const captured = {
      history_order: "oldest_to_newest",
      historico_texto: historyInput.value,
    };
    markResultStale("ranking");
    setBusy(true, "ranking");
    setOperation("Gerando ranking 0–36 e catalogando relações A → B com o Jev...");
    try {
      const response = await fetch("/api/jev/ranking", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrfToken },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify(captured),
      });
      const data = await readResponse(response);
      renderRanking(data);
      setOperation("Ranking concluído. Relações A → B são evidências descritivas, não causalidade.");
    } catch (error) {
      setOperation("O ranking não foi concluído.", error instanceof Error ? error.message : "Falha inesperada no ranking.");
    } finally {
      setBusy(false);
    }
  }

  async function analyze(event) {
    event.preventDefault();
    if (busy) return;
    const current = validateForm();
    if (!current.valid) return;
    const captured = {
      history_order: "oldest_to_newest",
      historico_texto: historyInput.value,
      grupos: current.groups,
    };
    markResultStale("groups");
    setBusy(true, "analysis");
    setOperation("Analisando com Jev...");
    try {
      const response = await fetch("/api/jev/analisar", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrfToken },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify(captured),
      });
      const data = await readResponse(response);
      renderAnalysis(data);
      setOperation("Análise concluída. As estimativas abaixo não são validação preditiva.");
    } catch (error) {
      setOperation("A análise não foi concluída.", error instanceof Error ? error.message : "Falha inesperada na análise.");
    } finally {
      setBusy(false);
    }
  }

  byId("open-history-dialog").addEventListener("click", () => {
    if (busy) return;
    byId("quantity-error").hidden = true;
    dialog.showModal();
    quantityInput.focus();
  });
  byId("cancel-history-dialog").addEventListener("click", () => dialog.close());
  byId("history-dialog-form").addEventListener("submit", fetchHistory);
  rankingButton.addEventListener("click", rankNumbers);
  form.addEventListener("submit", analyze);
  historyInput.addEventListener("input", () => {
    historyEdited = true;
    byId("history-origin").textContent = "Histórico editado manualmente.";
    markResultStale();
    validateForm();
  });
  groupIds.forEach((groupId) => byId(groupId).addEventListener("input", () => {
    markResultStale("groups");
    validateForm();
  }));

  validateForm();
})();
