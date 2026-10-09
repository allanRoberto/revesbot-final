(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const tabNames = ["suggestion", "ranking", "backtest"];
  const groupIds = ["grupo_1", "grupo_2", "grupo_3", "grupo_4", "grupo_5", "grupo_6"];
  const maxHistory = Number(document.querySelector('meta[name="jev-max-history"]').content);
  const maxBacktestCalls = Number(document.querySelector('meta[name="jev-backtest-max-calls"]').content);
  const jevInputPricePerMillion = Number(document.querySelector('meta[name="jev-input-price-per-million"]').content);
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const form = byId("jev-form");
  const rouletteSelect = byId("roulette-select");
  const historyEditor = byId("history-editor-dialog");
  const groupsDialog = byId("groups-dialog");
  const historyInput = byId("history-input");
  const reverseHistoryButton = byId("reverse-history");
  const analyzeButton = byId("analyze-button");
  const rankingButton = byId("ranking-button");
  const dialog = byId("history-dialog");
  const quantityInput = byId("history-quantity");
  const operationStatus = byId("operation-status");
  const operationError = byId("operation-error");
  let busy = false;
  let historyEdited = false;
  let latestRankingData = null;
  let activeBacktest = null;
  let backtestRunning = false;
  let backtestStopRequested = false;
  let restoreVersion = 0;
  let suggestionState = { ranking: null, anchorNumber: null, rouletteSlug: null, frozen: false };
  let suggestionSocket = null;
  let suggestionSocketVersion = 0;
  const suggestionSeenEvents = new Set();
  let suggestionCounters = { rounds: 0, inside: 0, outside: 0 };

  function rouletteName(slug = rouletteSelect.value) {
    return Array.from(rouletteSelect.options).find((option) => option.value === slug)?.textContent || slug;
  }

  function backtestStorageKey(slug = rouletteSelect.value) {
    return `jev-active-backtest-id:${slug}`;
  }

  function syncRouletteLock() {
    rouletteSelect.disabled = busy || backtestRunning;
  }

  function selectTab(name, focus = false) {
    tabNames.forEach((tab) => {
      const active = tab === name;
      byId(`${tab}-tab`).setAttribute("aria-selected", String(active));
      byId(`${tab}-tab`).tabIndex = active ? 0 : -1;
      byId(`${tab}-tab-panel`).hidden = !active;
    });
    if (focus) byId(`${name}-tab`).focus();
  }

  function updateRouletteLabels() {
    ["fetch-roulette-name", "editor-roulette-name", "backtest-roulette-name", "suggestion-roulette-name"].forEach((id) => {
      byId(id).textContent = rouletteName();
    });
  }

  function changeRoulette() {
    historyInput.value = "";
    historyEdited = false;
    latestRankingData = null;
    stopSuggestionMonitor(`Monitoramento parado: mesa alterada para ${rouletteName()}.`, true);
    suggestionState = { ranking: null, anchorNumber: null, rouletteSlug: null, frozen: false };
    activeBacktest = null;
    byId("results-section").hidden = true;
    byId("ranking-results-section").hidden = true;
    byId("ranking-empty").hidden = false;
    byId("suggestion-empty").hidden = false;
    byId("ranking-neighbor-section").hidden = true;
    byId("suggestion-monitor-controls").hidden = true;
    byId("suggestion-monitor-toggle").disabled = true;
    byId("suggestion-auto-update").checked = false;
    byId("suggestion-auto-update").disabled = true;
    byId("fetch-metadata").hidden = true;
    byId("fetch-note").hidden = true;
    byId("history-origin").textContent = "Nenhum histórico carregado para esta mesa.";
    byId("backtest-progress-region").hidden = true;
    byId("backtest-error").hidden = true;
    byId("backtest-confirm").checked = false;
    byId("backtest-tab-status").hidden = true;
    updateRouletteLabels();
    validateForm();
    setBacktestControls(false);
    setOperation(`Mesa selecionada: ${rouletteName()}. Busque ou cole o histórico desta mesa.`);
    restoreBacktest();
  }

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
    byId("history-brief").textContent = historyError
      ? "Nenhum histórico válido carregado"
      : `${parsedHistory.values.length} números · último: ${parsedHistory.values.at(-1)}`;

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
    reverseHistoryButton.disabled = busy || !rankingValid;
    rankingButton.disabled = busy || !rankingValid;
    analyzeButton.disabled = busy || !valid;
    return { valid, rankingValid, history: parsedHistory.values, groups };
  }

  function setBusy(nextBusy, label = "") {
    busy = nextBusy;
    document.querySelectorAll(".editable-control, [data-operation-control]").forEach((control) => {
      control.disabled = nextBusy;
    });
    syncRouletteLock();
    byId("analyze-label").textContent = nextBusy && label === "analysis" ? "Analisando grupos..." : "Analisar seis grupos";
    byId("ranking-label").textContent = nextBusy && label === "ranking" ? "Gerando ranking..." : "Gerar ranking 0–36";
    byId("ranking-evaluate-button").textContent = nextBusy && label === "evaluation" ? "Calculando..." : "Avaliar ranking";
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
      throw new Error(`A API retornou uma resposta que não é JSON válido (HTTP ${response.status}).`);
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
    const requestedRoulette = rouletteSelect.value;
    stopSuggestionMonitor("Busca iniciada; monitoramento parado.");
    setBusy(true, "history");
    setOperation("Buscando números...");
    try {
      const response = await fetch(`/api/jev/historico?quantidade=${encodeURIComponent(String(quantity))}&roulette_slug=${encodeURIComponent(requestedRoulette)}`, {
        method: "GET",
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
      });
      const data = await readResponse(response);
      if (!data || data.roulette_slug !== requestedRoulette
          || data.history_order !== "oldest_to_newest" || !Array.isArray(data.historico)
          || !data.historico.every((number) => Number.isInteger(number) && number >= 0 && number <= 36)) {
        throw new Error("A API retornou um histórico inválido.");
      }
      historyInput.value = data.historico.join(", ");
      historyEdited = false;
      byId("history-origin").textContent = data.historico.length
        ? `Histórico de ${rouletteName(requestedRoulette)} carregado do servidor; revise antes de analisar.`
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
      byId("ranking-empty").hidden = false;
      byId("ranking-result-stale").hidden = true;
      latestRankingData = null;
      suggestionState = { ranking: null, anchorNumber: null, rouletteSlug: null, frozen: false };
      stopSuggestionMonitor("Desligado", true);
      byId("suggestion-empty").hidden = false;
      byId("ranking-neighbor-section").hidden = true;
      byId("suggestion-monitor-controls").hidden = true;
      byId("suggestion-monitor-toggle").disabled = true;
      byId("suggestion-auto-update").checked = false;
      byId("suggestion-auto-update").disabled = true;
      setOperation(data.historico.length ? "Busca concluída. Você pode revisar e editar o histórico." : "Busca concluída sem resultados.");
    } catch (error) {
      historyInput.value = previousText;
      setOperation("A atualização do histórico falhou.", error instanceof Error ? error.message : "Falha inesperada na busca.");
    } finally {
      setBusy(false);
    }
  }

  function reverseHistory() {
    if (busy) return;
    const parsed = parseSequence(historyInput.value, "Histórico");
    if (parsed.error || parsed.values.length === 0 || parsed.values.length > maxHistory) {
      validateForm();
      historyInput.focus();
      return;
    }
    historyInput.value = parsed.values.reverse().join(", ");
    historyEdited = true;
    byId("history-origin").textContent = "A ordem do histórico foi invertida manualmente.";
    markResultStale();
    validateForm();
    setOperation("Ordem invertida. O primeiro número agora é o mais antigo e o último é o mais recente.");
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

  function regimeLabel(value) {
    const labels = {
      neutral: "neutro",
      frequency_concentration: "concentração de frequência",
      transition_driven: "orientado por transições",
      gap_driven: "orientado por atrasos",
      unstable: "instável",
    };
    return labels[value] || String(value || "não informado");
  }

  function validationLabel(value) {
    const labels = {
      validated: "validado",
      experimental: "experimental",
      degraded: "degradado",
      no_evidence: "sem evidência",
    };
    return labels[value] || String(value || "sem evidência");
  }

  function signalLabel(value) {
    const labels = {
      validated: "validado",
      experimental: "experimental",
      no_reliable_signal: "sem sinal confiável",
    };
    return labels[value] || String(value || "não informado");
  }

  function confidenceDecisionLabel(value) {
    const labels = { enter: "Entrar", observe: "Observar", no_entry: "Não entrar" };
    return labels[value] || "Não entrar";
  }

  function confidenceStatusLabel(value) {
    const labels = {
      validated: "validado", experimental: "experimental", degraded: "degradado",
      insufficient: "amostra insuficiente", unavailable: "indisponível",
    };
    return labels[value] || String(value || "indisponível");
  }

  function adaptiveStatusLabel(value) {
    return ({
      warming_up: "Aquecendo",
      shadow: "Modo sombra",
      promotion_eligible: "Elegível para promoção",
      degraded: "Abaixo do JEV",
      unavailable: "Indisponível",
    })[value] || value || "Indisponível";
  }

  function joinedNumbers(value) {
    return Array.isArray(value) && value.length ? value.join(", ") : "—";
  }

  function matchesPattern(result, filter) {
    if (filter === "all") return true;
    if (filter === "zero") return result.numero === 0;
    const classification = result.relacao_do_ultimo_numero.classification;
    if (filter === "stable") return classification === "stable_positive_pull" || classification === "stable_negative_relation";
    if (filter === "positive") return ["stable_positive_pull", "positive_pull", "recent_positive_pull"].includes(classification);
    if (filter === "negative") return ["stable_negative_relation", "recent_negative_relation"].includes(classification);
    return true;
  }

  function rankingSourceForView(data, view) {
    if (!data) return null;
    if (view === "next_one") return data.ranking_proxima_rodada;
    if (view === "next_three") return data.ranking;
    if (view === "meta_one") return data.ranking_meta_proxima_rodada;
    if (view === "meta_three") return data.ranking_meta;
    return null;
  }

  function calculateSuggestionWindow(ranking, anchorNumber) {
    if (!Array.isArray(ranking) || ranking.length !== 37 || !Number.isInteger(anchorNumber)) return null;
    const ordered = [...ranking].sort((left, right) => left.posicao - right.posicao);
    const anchorIndex = ordered.findIndex((item) => item.numero === anchorNumber);
    if (anchorIndex < 0) return null;
    const firstIndex = Math.max(0, Math.min(anchorIndex - 6, ordered.length - 13));
    const selected = ordered.slice(firstIndex, firstIndex + 13);
    if (selected.length !== 13 || !selected.some((item) => item.numero === anchorNumber)) return null;
    return { ordered, selected, anchorPosition: ordered[anchorIndex].posicao };
  }

  function renderSuggestionWindow() {
    const section = byId("ranking-neighbor-section");
    const list = byId("ranking-neighbor-numbers");
    const window = calculateSuggestionWindow(suggestionState.ranking, suggestionState.anchorNumber);
    if (!window) {
      section.hidden = true;
      list.replaceChildren();
      return;
    }

    const { selected, anchorPosition } = window;
    byId("ranking-neighbor-context").textContent =
      `Referência: ${suggestionState.anchorNumber} · posição ${anchorPosition} · janela nas posições ${selected[0].posicao}–${selected[selected.length - 1].posicao}`;

    const fragment = document.createDocumentFragment();
    selected
      .map((item) => item.numero)
      .sort((left, right) => left - right)
      .forEach((number) => {
        const item = document.createElement("li");
        const value = document.createElement("strong");
        value.textContent = String(number);
        if (number === suggestionState.anchorNumber) {
          item.classList.add("is-anchor");
          item.title = "Número de referência";
          item.setAttribute("aria-label", `${number}, número de referência`);
        } else {
          item.setAttribute("aria-label", String(number));
        }
        item.append(value);
        fragment.append(item);
      });
    list.replaceChildren(fragment);
    section.hidden = false;
  }

  function updateSuggestionCounters() {
    byId("suggestion-round-count").textContent = String(suggestionCounters.rounds);
    byId("suggestion-hit-miss").textContent = `${suggestionCounters.inside} / ${suggestionCounters.outside}`;
  }

  function stopSuggestionMonitor(status = "Monitoramento parado.", resetCounters = false) {
    const socket = suggestionSocket;
    suggestionSocket = null;
    suggestionSocketVersion += 1;
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
    byId("suggestion-monitor-toggle").textContent = "Iniciar monitoramento";
    byId("suggestion-monitor-toggle").disabled = !latestRankingData;
    byId("suggestion-auto-update").disabled = !latestRankingData;
    byId("ranking-view").disabled = false;
    byId("suggestion-monitor-status").textContent = status;
    if (resetCounters) {
      suggestionCounters = { rounds: 0, inside: 0, outside: 0 };
      suggestionSeenEvents.clear();
      byId("suggestion-last-result").textContent = "—";
      updateSuggestionCounters();
    }
  }

  function resultEventKey(event) {
    const fullResult = event.full_result && typeof event.full_result === "object" ? event.full_result : {};
    const id = fullResult.external_game_id || fullResult._id || fullResult.timestamp || fullResult.captured_at;
    return id ? `${event.slug}:${id}` : `${event.slug}:${event.result}:${JSON.stringify(fullResult)}`;
  }

  function receiveSuggestionResult(event, slug) {
    if (!event || event.slug !== slug || !Number.isInteger(event.result) || event.result < 0 || event.result > 36) return;
    const eventKey = resultEventKey(event);
    if (suggestionSeenEvents.has(eventKey)) return;
    suggestionSeenEvents.add(eventKey);
    if (suggestionSeenEvents.size > 2000) suggestionSeenEvents.delete(suggestionSeenEvents.values().next().value);

    const currentWindow = calculateSuggestionWindow(suggestionState.ranking, suggestionState.anchorNumber);
    if (!currentWindow) return;
    const selectedNumbers = new Set(currentWindow.selected.map((item) => item.numero));
    const inside = selectedNumbers.has(event.result);
    suggestionCounters.rounds += 1;
    if (inside) suggestionCounters.inside += 1;
    else suggestionCounters.outside += 1;
    byId("suggestion-last-result").textContent = `${event.result} · ${inside ? "dentro" : "fora"} da sugestão`;
    updateSuggestionCounters();

    if (!inside && byId("suggestion-auto-update").checked) {
      suggestionState.anchorNumber = event.result;
      renderSuggestionWindow();
    }
  }

  function startSuggestionMonitor() {
    if (!latestRankingData) return;
    const slug = rouletteSelect.value;
    if (!suggestionState.frozen || suggestionState.rouletteSlug !== slug || !suggestionState.ranking) {
      const ranking = rankingSourceForView(latestRankingData, byId("ranking-view").value);
      suggestionState = {
        ranking: Array.isArray(ranking) ? [...ranking] : null,
        anchorNumber: latestRankingData.ultimo_numero,
        rouletteSlug: slug,
        frozen: true,
      };
    }
    if (!calculateSuggestionWindow(suggestionState.ranking, suggestionState.anchorNumber)) {
      byId("suggestion-monitor-status").textContent = "Não foi possível criar a sugestão para este ranking.";
      return;
    }

    suggestionState.frozen = true;
    renderSuggestionWindow();
    byId("ranking-view").disabled = true;
    byId("suggestion-monitor-toggle").textContent = "Parar monitoramento";
    byId("suggestion-monitor-toggle").disabled = false;
    byId("suggestion-auto-update").disabled = false;
    byId("suggestion-monitor-status").textContent = "Conectando…";
    byId("suggestion-monitor-note").textContent =
      `Usando o mesmo ranking (${byId("ranking-view").selectedOptions[0].textContent}); apenas a referência pode mudar.`;

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${protocol}://api.revesbot.com.br/ws?slug=${encodeURIComponent(slug)}`;
    const version = ++suggestionSocketVersion;
    let socket;
    try {
      socket = new WebSocket(url);
    } catch (_error) {
      byId("suggestion-monitor-status").textContent = "Não foi possível abrir o websocket.";
      byId("suggestion-monitor-toggle").textContent = "Tentar novamente";
      byId("ranking-view").disabled = false;
      return;
    }
    suggestionSocket = socket;
    socket.addEventListener("open", () => {
      if (suggestionSocket !== socket || version !== suggestionSocketVersion) return;
      byId("suggestion-monitor-status").textContent = `Monitorando ${rouletteName(slug)}`;
    });
    socket.addEventListener("message", (message) => {
      if (suggestionSocket !== socket || version !== suggestionSocketVersion) return;
      try {
        receiveSuggestionResult(JSON.parse(message.data), slug);
      } catch (_error) {
        byId("suggestion-monitor-status").textContent = "Evento inválido recebido; monitoramento continua.";
      }
    });
    socket.addEventListener("error", () => {
      if (suggestionSocket === socket && version === suggestionSocketVersion) {
        byId("suggestion-monitor-status").textContent = "Erro na conexão do websocket.";
      }
    });
    socket.addEventListener("close", () => {
      if (suggestionSocket !== socket || version !== suggestionSocketVersion) return;
      suggestionSocket = null;
      byId("suggestion-monitor-toggle").textContent = "Retomar monitoramento";
      byId("ranking-view").disabled = false;
      byId("suggestion-monitor-status").textContent = "Conexão interrompida; resultados durante a queda podem não ter sido recebidos.";
      byId("suggestion-monitor-note").textContent = "Confira a conexão e retome o monitoramento para continuar acompanhando.";
    });
  }

  function renderRankingNeighborNumbers(ranking) {
    if (!suggestionState.frozen) {
      const canKeepReference = suggestionState.rouletteSlug === rouletteSelect.value
        && Number.isInteger(suggestionState.anchorNumber);
      suggestionState = {
        ranking: Array.isArray(ranking) ? [...ranking] : null,
        anchorNumber: canKeepReference ? suggestionState.anchorNumber : latestRankingData && latestRankingData.ultimo_numero,
        rouletteSlug: rouletteSelect.value,
        frozen: false,
      };
    }
    renderSuggestionWindow();
  }

  function renderRankingRows() {
    if (!latestRankingData) return;
    const percent = new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const view = byId("ranking-view").value;
    const patternFilter = byId("ranking-pattern-filter").value;
    const validationFilter = byId("ranking-validation-filter").value;
    const rawMinimum = Number(byId("ranking-min-support").value);
    const minimumSupport = Number.isFinite(rawMinimum) && rawMinimum >= 0 ? rawMinimum : 0;
    const mainByNumber = new Map(latestRankingData.ranking.map((item) => [item.numero, item]));
    const usesNextSpin = view === "next_one" || view === "meta_one";
    const usesMeta = view === "meta_one" || view === "meta_three";
    const metaSource = usesNextSpin
      ? latestRankingData.ranking_meta_proxima_rodada
      : latestRankingData.ranking_meta;
    const metaByNumber = new Map(metaSource.map((item) => [item.numero, item]));
    const source = rankingSourceForView(latestRankingData, view);
    renderRankingNeighborNumbers(source);
    const rows = source.filter((item) => {
      const main = mainByNumber.get(item.numero);
      const meta = metaByNumber.get(item.numero);
      const validationMatches = validationFilter === "all" || meta.status_validacao === validationFilter;
      return validationMatches && matchesPattern(main, patternFilter)
        && main.relacao_do_ultimo_numero.support >= minimumSupport;
    });
    const fragment = document.createDocumentFragment();
    rows.forEach((item) => {
      const main = mainByNumber.get(item.numero);
      const meta = metaByNumber.get(item.numero);
      const relation = main.relacao_do_ultimo_numero;
      const probability = usesMeta
        ? item.probabilidade_meta
        : (usesNextSpin ? item.probabilidade : item.estimativa_jev_nao_validada);
      const baseline = item.probabilidade_base;
      const differenceFromBase = item.diferenca_da_base;
      const row = document.createElement("tr");
      appendCell(row, String(item.posicao));
      const numberCell = appendCell(row, String(item.numero));
      numberCell.classList.add("ranking-number");
      if (item.numero === 0) numberCell.classList.add("zero-number");
      appendCell(row, percent.format(probability));
      appendCell(row, percent.format(baseline));
      appendCell(row, `${differenceFromBase >= 0 ? "+" : "−"}${percent.format(Math.abs(differenceFromBase))}`);
      const validationCell = appendCell(
        row,
        `${validationLabel(meta.status_validacao)} · ${meta.amostras_walk_forward} amostras · confiança ${percent.format(meta.confiabilidade_meta)}`,
      );
      validationCell.classList.add("meta-status", meta.status_validacao);
      appendCell(row, `${relation.source_number} → ${relation.target_number} · ${patternLabel(relation.classification)} · suporte ${relation.support}`);
      fragment.append(row);
    });
    byId("ranking-results-body").replaceChildren(fragment);
    const topItems = rows.slice(0, 6).map((item) => {
      const entry = document.createElement("li");
      const position = document.createElement("span");
      position.textContent = `${item.posicao}º`;
      const number = document.createElement("strong");
      number.textContent = String(item.numero);
      entry.append(position, number);
      return entry;
    });
    byId("ranking-top-numbers").replaceChildren(...topItems);
    byId("ranking-top-label").textContent = byId("ranking-view").selectedOptions[0].textContent;
    const headings = {
      meta_three: "Meta calibrado · próximas 3",
      meta_one: "Meta calibrado · próxima rodada",
      next_three: "Noul Jev · próximas 3",
      next_one: "Choice Jev · próxima rodada",
    };
    byId("ranking-estimate-heading").textContent = headings[view];
    byId("ranking-filter-count").textContent = `${rows.length} ${rows.length === 1 ? "número" : "números"}`;
  }

  function renderRanking(data) {
    if (!data || data.analysis_type !== "number_ranking"
        || !Array.isArray(data.ranking) || data.ranking.length !== 37
        || !Array.isArray(data.ranking_proxima_rodada) || data.ranking_proxima_rodada.length !== 37
        || !Array.isArray(data.ranking_meta) || data.ranking_meta.length !== 37
        || !Array.isArray(data.ranking_meta_proxima_rodada) || data.ranking_meta_proxima_rodada.length !== 37
        || !data.sinal_meta || typeof data.sinal_meta.status !== "string"
        || typeof data.sinal_meta.available !== "boolean"
        || !data.confianca_top_n || typeof data.confianca_top_n.decision !== "string"
        || !Array.isArray(data.confianca_top_n.selected_numbers)
        || !data.ranking_adaptativo || typeof data.ranking_adaptativo.status !== "string"
        || !Array.isArray(data.ranking_adaptativo.jev_selected_numbers)
        || !Array.isArray(data.ranking_adaptativo.adaptive_selected_numbers)
        || !data.validacao_walk_forward || typeof data.validacao_walk_forward.version !== "string"
        || !data.proxima_rodada || !Number.isInteger(data.proxima_rodada.numero_escolhido)
        || typeof data.proxima_rodada.confidence !== "number"
        || !data.proxima_rodada_meta || !Number.isInteger(data.proxima_rodada_meta.numero_escolhido)
        || typeof data.proxima_rodada_meta.probabilidade !== "number"
        || !data.regime_atual || typeof data.regime_atual.choice !== "string"
        || typeof data.regime_atual.confidence !== "number"
        || !Array.isArray(data.catalogo_padroes)) {
      throw new Error("A API retornou um ranking incompleto.");
    }
    const percent = new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const decimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const seenNumbers = new Set();
    data.ranking.forEach((result, index) => {
      const relation = result && result.relacao_do_ultimo_numero;
      if (!result || result.posicao !== index + 1 || !Number.isInteger(result.numero)
          || result.numero < 0 || result.numero > 36 || seenNumbers.has(result.numero)
          || typeof result.estimativa_jev_nao_validada !== "number"
          || typeof result.probabilidade_base !== "number"
          || typeof result.diferenca_da_base !== "number"
          || typeof result.probabilidade_proxima_rodada !== "number"
          || !Number.isInteger(result.posicao_proxima_rodada)
          || !relation || relation.target_number !== result.numero
          || !Number.isInteger(relation.source_number)) {
        throw new Error("A API retornou um item inválido no ranking.");
      }
      seenNumbers.add(result.numero);
    });
    if (seenNumbers.size !== 37 || !seenNumbers.has(0)) {
      throw new Error("O ranking não contém todos os números de 0 a 36.");
    }
    const immediateNumbers = new Set();
    data.ranking_proxima_rodada.forEach((result, index) => {
      if (!result || result.posicao !== index + 1 || !Number.isInteger(result.numero)
          || result.numero < 0 || result.numero > 36 || immediateNumbers.has(result.numero)
          || typeof result.probabilidade !== "number"
          || typeof result.probabilidade_base !== "number"
          || typeof result.diferenca_da_base !== "number") {
        throw new Error("A API retornou um ranking imediato inválido.");
      }
      immediateNumbers.add(result.numero);
    });
    if (immediateNumbers.size !== 37 || !immediateNumbers.has(0)) {
      throw new Error("O ranking imediato não contém todos os números de 0 a 36.");
    }
    [data.ranking_meta, data.ranking_meta_proxima_rodada].forEach((ranking) => {
      const metaNumbers = new Set();
      ranking.forEach((result, index) => {
        if (!result || result.posicao !== index + 1 || !Number.isInteger(result.numero)
            || result.numero < 0 || result.numero > 36 || metaNumbers.has(result.numero)
            || typeof result.probabilidade_meta !== "number"
            || typeof result.probabilidade_base !== "number"
            || typeof result.diferenca_da_base !== "number"
            || typeof result.confiabilidade_meta !== "number"
            || !Number.isInteger(result.amostras_walk_forward)
            || typeof result.status_validacao !== "string") {
          throw new Error("A API retornou um item inválido no meta-ranking.");
        }
        metaNumbers.add(result.numero);
      });
      if (metaNumbers.size !== 37 || !metaNumbers.has(0)) {
        throw new Error("O meta-ranking não contém todos os números de 0 a 36.");
      }
    });
    latestRankingData = data;
    suggestionState = { ranking: null, anchorNumber: null, rouletteSlug: null, frozen: false };
    suggestionCounters = { rounds: 0, inside: 0, outside: 0 };
    suggestionSeenEvents.clear();
    updateSuggestionCounters();
    byId("suggestion-empty").hidden = true;
    byId("suggestion-monitor-controls").hidden = false;
    byId("suggestion-monitor-toggle").disabled = false;
    byId("suggestion-auto-update").disabled = false;
    byId("suggestion-monitor-toggle").textContent = "Iniciar monitoramento";
    byId("suggestion-monitor-status").textContent = "Desligado";
    byId("suggestion-last-result").textContent = "—";
    byId("suggestion-monitor-note").textContent = "O monitor apenas atualiza e exibe a sugestão; ele não envia apostas.";

    byId("ranking-view").value = "next_one";
    byId("ranking-pattern-filter").value = "all";
    byId("ranking-validation-filter").value = "all";
    byId("ranking-min-support").value = "0";
    renderRankingRows();

    const catalogFragment = document.createDocumentFragment();
    data.catalogo_padroes.forEach((pattern) => {
      if (!pattern || !Number.isInteger(pattern.source_number)
          || !Number.isInteger(pattern.target_number)
          || !pattern.qualidade_jev
          || typeof pattern.qualidade_jev.score !== "number"
          || typeof pattern.qualidade_jev.confidence !== "number") {
        throw new Error("A API retornou um padrão catalogado inválido.");
      }
      const row = document.createElement("tr");
      appendCell(row, `${pattern.source_number} → ${pattern.target_number}`);
      appendCell(row, patternLabel(pattern.classification));
      appendCell(row, String(pattern.support));
      appendCell(row, String(pattern.hits));
      appendCell(row, decimal.format(pattern.lift_vs_baseline));
      appendCell(row, `${decimal.format(pattern.qualidade_jev.score)} / 3`);
      appendCell(row, percent.format(pattern.qualidade_jev.confidence));
      catalogFragment.append(row);
    });
    byId("ranking-catalog-body").replaceChildren(catalogFragment);
    byId("ranking-catalog-empty").hidden = data.catalogo_padroes.length !== 0;
    byId("ranking-catalog-table").hidden = data.catalogo_padroes.length === 0;

    byId("ranking-result-count").textContent = String(data.quantidade_analisada);
    byId("ranking-context-label").textContent = `${rouletteName(data.roulette_slug)} · ${data.quantidade_analisada} números · último: ${data.ultimo_numero}`;
    byId("ranking-result-source").textContent = String(data.ultimo_numero);
    byId("ranking-result-horizon").textContent = `${data.forecast_horizon_spins} rodadas`;
    byId("ranking-result-model").textContent = data.modelo_retornado || "Não informado";
    byId("ranking-result-at").textContent = formatDate(data.respondido_em);
    byId("ranking-result-latency").textContent = `${data.latencia_ms} ms`;
    byId("ranking-pattern-count").textContent = String(data.catalogo_padroes.length);
    byId("ranking-next-choice").textContent = `Meta ${data.proxima_rodada_meta.numero_escolhido} · ${percent.format(data.proxima_rodada_meta.probabilidade)} · Jev ${data.proxima_rodada.numero_escolhido}`;
    byId("ranking-regime").textContent = `${regimeLabel(data.regime_atual.choice)} · confiança ${percent.format(data.regime_atual.confidence)}`;
    byId("ranking-meta-signal").textContent = `${signalLabel(data.sinal_meta.status)} · cobertura ${percent.format(data.sinal_meta.coverage)}`;
    byId("ranking-walk-forward").textContent = `${data.validacao_walk_forward.version} · treino mín. ${data.validacao_walk_forward.minimum_training_support}`;
    const confidence = data.confianca_top_n;
    byId("ranking-confidence-numbers").textContent = confidence.selected_numbers.join(", ");
    byId("ranking-confidence-decision").textContent = `${confidenceDecisionLabel(confidence.decision)} · ${confidenceStatusLabel(confidence.status)}`;
    byId("ranking-confidence-probability").textContent = typeof confidence.calibrated_probability === "number"
      ? percent.format(confidence.calibrated_probability) : "Aguardando amostra";
    byId("ranking-confidence-bound").textContent = typeof confidence.conservative_lower_bound === "number"
      ? percent.format(confidence.conservative_lower_bound) : "—";
    byId("ranking-confidence-baseline").textContent = typeof confidence.fair_baseline === "number"
      ? percent.format(confidence.fair_baseline) : "—";
    byId("ranking-confidence-samples").textContent = String(confidence.sample_count || 0);
    byId("ranking-confidence-reason").textContent = confidence.reason || "Sem justificativa disponível.";
    const adaptive = data.ranking_adaptativo;
    const adaptiveMetrics = adaptive.training_metrics || {};
    const metricPair = (champion, challenger, formatter) => (
      typeof champion === "number" && typeof challenger === "number"
        ? `${formatter(champion)} / ${formatter(challenger)}` : "—"
    );
    byId("ranking-adaptive-status").textContent = adaptiveStatusLabel(adaptive.status);
    byId("ranking-adaptive-samples").textContent = String(adaptive.sample_count || 0);
    byId("ranking-adaptive-jev-numbers").textContent = joinedNumbers(adaptive.jev_selected_numbers);
    byId("ranking-adaptive-numbers").textContent = joinedNumbers(adaptive.adaptive_selected_numbers);
    byId("ranking-adaptive-maintained").textContent = joinedNumbers(adaptive.maintained_numbers);
    byId("ranking-adaptive-added").textContent = joinedNumbers(adaptive.added_numbers);
    byId("ranking-adaptive-removed").textContent = joinedNumbers(adaptive.removed_numbers);
    byId("ranking-adaptive-accuracy").textContent = metricPair(
      adaptiveMetrics.jev_top_k_accuracy, adaptiveMetrics.adaptive_top_k_accuracy, (value) => percent.format(value),
    );
    byId("ranking-adaptive-brier").textContent = metricPair(
      adaptiveMetrics.jev_brier, adaptiveMetrics.adaptive_brier, (value) => value.toFixed(4),
    );
    byId("ranking-adaptive-logloss").textContent = metricPair(
      adaptiveMetrics.jev_log_loss, adaptiveMetrics.adaptive_log_loss, (value) => value.toFixed(4),
    );
    byId("ranking-adaptive-reason").textContent = adaptive.reason || "Sem justificativa disponível.";

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
    byId("ranking-actual-results").value = "";
    byId("ranking-evaluation-error").hidden = true;
    byId("ranking-evaluation-results").hidden = true;
    byId("ranking-result-stale").hidden = true;
    byId("ranking-results-section").hidden = false;
    byId("ranking-empty").hidden = true;
    byId("ranking-details").open = false;
    selectTab("ranking");
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  async function evaluateRanking(event) {
    event.preventDefault();
    if (busy || !latestRankingData) return;
    const parsed = parseSequence(byId("ranking-actual-results").value, "Resultados reais");
    const error = parsed.error || (parsed.values.length !== 3 ? "Informe exatamente os três resultados seguintes, na ordem." : "");
    byId("ranking-evaluation-error").textContent = error;
    byId("ranking-evaluation-error").hidden = !error;
    if (error) return;
    setBusy(true, "evaluation");
    setOperation("Calculando métricas do ranking salvo...");
    try {
      const response = await fetch("/api/jev/avaliar", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrfToken },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify({
          analysis_id: latestRankingData.analysis_id,
          resultados_reais_texto: byId("ranking-actual-results").value,
        }),
      });
      const data = await readResponse(response);
      const metrics = data && data.metricas_tres_rodadas;
      const immediate = data && data.metrica_proxima_rodada;
      if (!metrics || !immediate || typeof metrics.brier_medio_37_numeros !== "number"
          || typeof metrics.log_loss_binario_medio_37_numeros !== "number") {
        throw new Error("A API retornou uma avaliação incompleta.");
      }
      const decimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 4, maximumFractionDigits: 6 });
      byId("evaluation-brier").textContent = decimal.format(metrics.brier_medio_37_numeros);
      byId("evaluation-log-loss").textContent = decimal.format(metrics.log_loss_binario_medio_37_numeros);
      byId("evaluation-top-hits").textContent = [1, 3, 5, 10]
        .map((size) => `Top ${size}: ${metrics.acertos_por_corte[`top_${size}`] ? "sim" : "não"}`)
        .join(" · ");
      byId("evaluation-next-hit").textContent = immediate.acertou_escolha
        ? `Acertou o ${immediate.numero_real}`
        : `Não acertou · real ${immediate.numero_real} na posição ${immediate.posicao_do_numero_real}`;
      const metaMetrics = data.metricas_meta_tres_rodadas;
      const comparison = data.comparacao_meta_vs_jev;
      if (metaMetrics && comparison) {
        byId("evaluation-meta-brier").textContent = decimal.format(metaMetrics.brier_medio_37_numeros);
        byId("evaluation-meta-log-loss").textContent = decimal.format(metaMetrics.log_loss_binario_medio_37_numeros);
        byId("evaluation-meta-top-hits").textContent = [1, 3, 5, 10]
          .map((size) => `Top ${size}: ${metaMetrics.acertos_por_corte[`top_${size}`] ? "sim" : "não"}`)
          .join(" · ");
        byId("evaluation-meta-comparison").textContent = `Brier ${comparison.ganho_brier >= 0 ? "+" : ""}${decimal.format(comparison.ganho_brier)} · log loss ${comparison.ganho_log_loss >= 0 ? "+" : ""}${decimal.format(comparison.ganho_log_loss)}`;
      } else {
        byId("evaluation-meta-brier").textContent = "Não disponível";
        byId("evaluation-meta-log-loss").textContent = "Não disponível";
        byId("evaluation-meta-top-hits").textContent = "Não disponível";
        byId("evaluation-meta-comparison").textContent = "Não disponível";
      }
      byId("ranking-evaluation-results").hidden = false;
      setOperation("Avaliação concluída sem nova chamada ao Jev.");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Falha inesperada na avaliação.";
      byId("ranking-evaluation-error").textContent = message;
      byId("ranking-evaluation-error").hidden = false;
      setOperation("A avaliação não foi concluída.", message);
    } finally {
      setBusy(false);
    }
  }

  async function rankNumbers() {
    if (busy) return;
    const current = validateForm();
    if (!current.rankingValid) return;
    const captured = {
      roulette_slug: rouletteSelect.value,
      history_order: "oldest_to_newest",
      historico_texto: historyInput.value,
      confidence_top_k: Number(byId("ranking-confidence-top-k").value),
      confidence_attempts: Number(byId("ranking-confidence-attempts").value),
    };
    if (!Number.isInteger(captured.confidence_top_k) || captured.confidence_top_k < 1 || captured.confidence_top_k > 36
        || !Number.isInteger(captured.confidence_attempts) || captured.confidence_attempts < 1 || captured.confidence_attempts > 10) {
      setOperation("O ranking não foi iniciado.", "Informe entre 1 e 36 números e entre 1 e 10 tentativas para a confiança.");
      return;
    }
    stopSuggestionMonitor("Novo ranking em processamento.");
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
      setOperation(data.sinal_meta.available
        ? "Ranking concluído com candidatos validados no walk-forward."
        : `Ranking concluído: ${data.sinal_meta.reason}`);
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
      roulette_slug: rouletteSelect.value,
      history_order: "oldest_to_newest",
      historico_texto: historyInput.value,
      grupos: current.groups,
    };
    groupsDialog.close();
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

  function backtestInteger(id, minimum, maximum, label) {
    const value = Number(byId(id).value);
    if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
      throw new Error(`${label} deve estar entre ${minimum} e ${maximum}.`);
    }
    return value;
  }

  function updateBacktestEstimate() {
    const calls = Number(byId("backtest-history-points").value);
    const context = Number(byId("backtest-context").value);
    const attempts = Number(byId("backtest-attempts").value);
    const signalMode = byId("backtest-signal-mode").value;
    const required = Number.isFinite(calls + context + attempts)
      ? calls + context + Math.max(attempts, 10) - 1 : 0;
    const rate = new Intl.NumberFormat("en-US", {
      style: "currency", currency: "USD", minimumFractionDigits: 3, maximumFractionDigits: 3,
    }).format(jevInputPricePerMillion);
    const callEstimate = signalMode === "sequential"
      ? `No modo sequencial, ${calls || "—"} pontos históricos geram no máximo ${calls || "—"} chamadas e normalmente menos.`
      : `${calls || "—"} pontos históricos podem gerar ${calls || "—"} chamadas.`;
    byId("backtest-estimate").textContent = `Histórico necessário: ${required || "—"} números. ${callEstimate} Preço de referência: ${rate} por 1 milhão de tokens de entrada; saída sem custo. Em 1.000 chamadas: 5 mil tokens/chamada ≈ US$ 0,21; 10 mil ≈ US$ 0,42; 32 mil ≈ US$ 1,344. O painel acumula o custo real informado pela API.`;
  }

  function setBacktestControls(running) {
    backtestRunning = running;
    syncRouletteLock();
    document.querySelectorAll("#backtest-form input, #backtest-form select, #backtest-start").forEach((control) => {
      control.disabled = running;
    });
    const pause = byId("backtest-pause");
    pause.disabled = !running && (!activeBacktest
      || activeBacktest.progress.next_step >= activeBacktest.progress.total_calls);
    pause.textContent = running ? "Pausar após a chamada atual" : "Retomar backtest";
    byId("backtest-start").textContent = running ? "Executando..." : "Iniciar novo backtest";
  }

  function backtestStatusLabel(data) {
    if (data.status === "completed") return "Concluído";
    if (data.status === "completed_with_errors") return "Concluído com falhas";
    if (data.status === "paused_error") return "Pausado por falha";
    if (!backtestRunning && data.progress.next_step < data.progress.total_calls) return "Pausado";
    return "Executando";
  }

  function renderBacktest(data) {
    if (!data || data.analysis_type !== "jev_historical_backtest" || !data.progress
        || !data.metrics || !data.usage || !data.configuration) {
      throw new Error("A API retornou um backtest inválido.");
    }
    activeBacktest = data;
    byId("backtest-roulette-name").textContent = rouletteName(data.roulette_slug || "pragmatic-auto-roulette");
    byId("backtest-tab-status").hidden = false;
    byId("backtest-tab-status").textContent = backtestStatusLabel(data);
    const { progress, metrics, usage } = data;
    const attempted = progress.attempted_calls;
    const total = progress.total_calls;
    const timelinePoint = Math.min(progress.next_step, total);
    byId("backtest-progress-region").hidden = false;
    byId("backtest-progress").max = Math.max(1, total);
    byId("backtest-progress").value = timelinePoint;
    byId("backtest-progress-label").textContent = `${attempted} chamadas · ponto ${timelinePoint} / ${total}`;
    byId("backtest-status").textContent = backtestStatusLabel(data);
    const percent = new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const decimal = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
    const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 6, maximumFractionDigits: 6 });
    byId("backtest-mode-result").textContent = data.configuration.signal_mode === "sequential"
      ? "Sequencial" : "Sobreposto";
    byId("backtest-accuracy").textContent = typeof metrics.accuracy === "number" ? percent.format(metrics.accuracy) : "—";
    byId("backtest-hit-loss").textContent = `${metrics.hits} / ${metrics.misses}`;
    byId("backtest-average-attempt").textContent = typeof metrics.average_attempt_on_hit === "number"
      ? decimal.format(metrics.average_attempt_on_hit) : "—";
    byId("backtest-failures").textContent = String(progress.failed_calls);
    byId("backtest-input-tokens").textContent = usage.input_tokens_reported_calls
      ? `${new Intl.NumberFormat("pt-BR").format(usage.input_tokens)} (${usage.input_tokens_reported_calls} chamadas)` : "Não informado";
    byId("backtest-cost").textContent = usage.cost_reported_calls ? usd.format(usage.cost_usd) : "Não informado";
    byId("backtest-projected-cost").textContent = typeof usage.projected_cost_per_1000_calls_usd === "number"
      ? usd.format(usage.projected_cost_per_1000_calls_usd) : "Aguardando custo real";
    byId("backtest-id").textContent = data.backtest_id;
    const confidence = data.confidence && typeof data.confidence === "object" ? data.confidence : null;
    const latestConfidence = confidence && confidence.latest_assessment;
    byId("backtest-confidence-decision").textContent = latestConfidence
      ? `${confidenceDecisionLabel(latestConfidence.decision)} · ${confidenceStatusLabel(latestConfidence.status)}` : "Aguardando primeiro sinal";
    byId("backtest-confidence-probability").textContent = latestConfidence
      && typeof latestConfidence.calibrated_probability === "number"
      ? percent.format(latestConfidence.calibrated_probability) : "Aguardando amostra";
    byId("backtest-confidence-bound").textContent = latestConfidence
      && typeof latestConfidence.conservative_lower_bound === "number"
      ? `${percent.format(latestConfidence.conservative_lower_bound)} / ${percent.format(latestConfidence.fair_baseline)}`
      : (latestConfidence && typeof latestConfidence.fair_baseline === "number" ? `— / ${percent.format(latestConfidence.fair_baseline)}` : "—");
    byId("backtest-confidence-samples").textContent = latestConfidence
      ? `${latestConfidence.sample_count} anteriores · ${confidence.samples_collected} coletadas` : "0";
    const decisionMetrics = confidence && confidence.decision_metrics ? confidence.decision_metrics : {};
    const confidenceBars = ["enter", "observe", "no_entry"].map((decision) => {
      const bucket = decisionMetrics[decision] || { signals: 0, hits: 0, accuracy: null };
      const item = document.createElement("div");
      item.className = "attempt-bar";
      const label = document.createElement("span");
      label.textContent = confidenceDecisionLabel(decision);
      const value = document.createElement("strong");
      value.textContent = typeof bucket.accuracy === "number"
        ? `${bucket.hits}/${bucket.signals} · ${percent.format(bucket.accuracy)}` : `${bucket.signals} sinais`;
      item.append(label, value);
      return item;
    });
    byId("backtest-confidence-bars").replaceChildren(...confidenceBars);
    const adaptive = data.adaptive && typeof data.adaptive === "object" ? data.adaptive : null;
    const champion = adaptive && adaptive.jev ? adaptive.jev : {};
    const challenger = adaptive && adaptive.challenger ? adaptive.challenger : {};
    const latestAdaptive = adaptive && adaptive.latest_prediction ? adaptive.latest_prediction : null;
    const paired = (first, second, formatter) => (
      typeof first === "number" && typeof second === "number"
        ? `${formatter(first)} / ${formatter(second)}` : "—"
    );
    byId("backtest-adaptive-status").textContent = adaptiveStatusLabel(adaptive && adaptive.status);
    byId("backtest-adaptive-samples").textContent = String(adaptive ? adaptive.sample_count || 0 : 0);
    byId("backtest-adaptive-accuracy").textContent = paired(champion.accuracy, challenger.accuracy, (value) => percent.format(value));
    byId("backtest-adaptive-brier").textContent = paired(champion.brier, challenger.brier, (value) => value.toFixed(4));
    byId("backtest-adaptive-logloss").textContent = paired(champion.log_loss, challenger.log_loss, (value) => value.toFixed(4));
    byId("backtest-adaptive-rank").textContent = paired(champion.average_winner_rank, challenger.average_winner_rank, (value) => decimal.format(value));
    byId("backtest-adaptive-jev-numbers").textContent = joinedNumbers(latestAdaptive && latestAdaptive.jev_selected_numbers);
    byId("backtest-adaptive-numbers").textContent = joinedNumbers(latestAdaptive && latestAdaptive.adaptive_selected_numbers);
    byId("backtest-adaptive-reason").textContent = adaptive && adaptive.reason ? adaptive.reason : "Aguardando primeiro sinal.";
    const bars = Object.entries(metrics.hits_by_attempt).map(([attempt, count]) => {
      const item = document.createElement("div");
      item.className = "attempt-bar";
      const label = document.createElement("span");
      label.textContent = `Tentativa ${attempt}`;
      const value = document.createElement("strong");
      value.textContent = String(count);
      item.append(label, value);
      return item;
    });
    byId("backtest-attempt-bars").replaceChildren(...bars);
    const observation = metrics.observation && typeof metrics.observation === "object"
      ? metrics.observation : null;
    const early = observation && observation.early_win_within_3
      ? observation.early_win_within_3 : null;
    byId("backtest-observation-signals").textContent = observation
      ? String(observation.signals) : "Não disponível nesta execução";
    byId("backtest-observation-any-hit").textContent = observation
      && typeof observation.signals_with_any_hit_rate === "number"
      ? `${observation.signals_with_any_hit} · ${percent.format(observation.signals_with_any_hit_rate)}` : "—";
    byId("backtest-observation-hit-average").textContent = observation
      && typeof observation.average_hits_per_signal === "number"
      ? `${observation.total_hits} · média ${decimal.format(observation.average_hits_per_signal)}` : "—";
    byId("backtest-observation-multiple").textContent = observation
      && typeof observation.signals_with_multiple_hits_rate === "number"
      ? `${observation.signals_with_multiple_hits} · ${percent.format(observation.signals_with_multiple_hits_rate)}` : "—";
    byId("backtest-observation-early-repeat").textContent = early
      && typeof early.hit_after_attempt_3_rate === "number"
      ? `${early.signals_with_hit_after_attempt_3}/${early.eligible_signals} · ${percent.format(early.hit_after_attempt_3_rate)}` : "Sem amostra";
    byId("backtest-observation-initial-multiple").textContent = early
      && typeof early.multiple_hits_within_3_rate === "number"
      ? `${early.signals_with_multiple_hits_within_3}/${early.eligible_signals} · ${percent.format(early.multiple_hits_within_3_rate)}` : "Sem amostra";
    byId("backtest-observation-later-average").textContent = early
      && typeof early.average_hits_after_attempt_3_per_eligible_signal === "number"
      ? `${early.hits_after_attempt_3_total} · média ${decimal.format(early.average_hits_after_attempt_3_per_eligible_signal)}` : "Sem amostra";
    const observationBars = observation
      ? Object.entries(observation.hit_occurrences_by_attempt).map(([attempt, count]) => {
        const item = document.createElement("div");
        item.className = "attempt-bar";
        const label = document.createElement("span");
        label.textContent = `Tentativa ${attempt}`;
        const value = document.createElement("strong");
        value.textContent = String(count);
        item.append(label, value);
        return item;
      }) : [];
    byId("backtest-observation-bars").replaceChildren(...observationBars);
    const laterOccurrenceCounts = early && early.hit_occurrences_after_attempt_3_by_attempt
      ? early.hit_occurrences_after_attempt_3_by_attempt : {};
    const laterOccurrenceRates = early && early.hit_rate_after_attempt_3_by_attempt
      ? early.hit_rate_after_attempt_3_by_attempt : {};
    const laterBars = Object.entries(laterOccurrenceCounts).map(([attempt, count]) => {
      const item = document.createElement("div");
      item.className = "attempt-bar";
      const label = document.createElement("span");
      label.textContent = `Tentativa ${attempt}`;
      const value = document.createElement("strong");
      const rate = laterOccurrenceRates[attempt];
      value.textContent = typeof rate === "number"
        ? `${count} · ${percent.format(rate)}` : String(count);
      item.append(label, value);
      return item;
    });
    byId("backtest-early-later-bars").replaceChildren(...laterBars);
    const initialCountDistribution = early && early.initial_hit_count_distribution
      ? early.initial_hit_count_distribution : {};
    const initialCountBars = Object.entries(initialCountDistribution).map(([hitCount, count]) => {
      const item = document.createElement("div");
      item.className = "attempt-bar";
      const label = document.createElement("span");
      label.textContent = `${hitCount} ${hitCount === "1" ? "acerto" : "acertos"} nas tentativas 1–3`;
      const value = document.createElement("strong");
      const rate = early.eligible_signals ? count / early.eligible_signals : null;
      value.textContent = typeof rate === "number"
        ? `${count} · ${percent.format(rate)}` : String(count);
      item.append(label, value);
      return item;
    });
    byId("backtest-early-initial-count-bars").replaceChildren(...initialCountBars);
    const countBars = observation
      ? Object.entries(observation.hit_count_distribution).map(([hitCount, count]) => {
        const item = document.createElement("div");
        item.className = "attempt-bar";
        const label = document.createElement("span");
        label.textContent = `${hitCount} ${hitCount === "1" ? "acerto" : "acertos"}`;
        const value = document.createElement("strong");
        value.textContent = String(count);
        item.append(label, value);
        return item;
      }) : [];
    byId("backtest-hit-count-bars").replaceChildren(...countBars);
    const last = data.last_step;
    if (last && last.status === "success") {
      const observationSummary = last.observation
        ? ` Em ${last.observation.horizon} giros: ${last.observation.hit_count} acerto(s) nas tentativas ${last.observation.hit_attempts.join(", ") || "nenhuma"}.`
        : "";
      byId("backtest-last-step").textContent = (last.hit
        ? `Último ponto: acerto principal do número ${last.hit_number} na tentativa ${last.first_hit_attempt}; fichas ${last.selected_numbers.join(", ")}.`
        : `Último ponto: sem acerto principal; fichas ${last.selected_numbers.join(", ")}.`) + observationSummary;
    } else if (last && last.status === "failed") {
      byId("backtest-last-step").textContent = `Último ponto falhou: ${last.error.message}`;
    } else {
      byId("backtest-last-step").textContent = "Nenhuma chamada executada ainda.";
    }
    localStorage.setItem(backtestStorageKey(data.roulette_slug || "pragmatic-auto-roulette"), data.backtest_id);
  }

  async function runBacktest() {
    if (backtestRunning || !activeBacktest) return;
    backtestStopRequested = false;
    setBacktestControls(true);
    byId("backtest-error").hidden = true;
    try {
      while (!backtestStopRequested
          && activeBacktest.progress.next_step < activeBacktest.progress.total_calls) {
        const response = await fetch("/api/jev/backtest/proximo", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrfToken },
          credentials: "same-origin",
          cache: "no-store",
          body: JSON.stringify({
            backtest_id: activeBacktest.backtest_id,
            expected_step: activeBacktest.progress.next_step,
          }),
        });
        const data = await readResponse(response);
        renderBacktest(data);
        if (data.status === "paused_error") {
          throw new Error(data.last_error ? data.last_error.message : "Uma chamada do backtest falhou.");
        }
      }
    } catch (error) {
      byId("backtest-error").textContent = error instanceof Error ? error.message : "Falha inesperada no backtest.";
      byId("backtest-error").hidden = false;
    } finally {
      setBacktestControls(false);
      if (activeBacktest) renderBacktest(activeBacktest);
    }
  }

  async function startBacktest(event) {
    event.preventDefault();
    if (backtestRunning) return;
    restoreVersion += 1;
    byId("backtest-error").hidden = true;
    try {
      const historyPoints = backtestInteger("backtest-history-points", 1, maxBacktestCalls, "Pontos históricos");
      const contextNumbers = backtestInteger("backtest-context", 50, maxHistory, "Contexto");
      const chipCount = backtestInteger("backtest-chips", 1, 36, "Fichas");
      const attempts = backtestInteger("backtest-attempts", 1, 100, "Tentativas");
      const signalMode = byId("backtest-signal-mode").value;
      if (!["overlapping", "sequential"].includes(signalMode)) {
        throw new Error("Selecione uma modalidade de sinais válida.");
      }
      const requiredHistory = contextNumbers + historyPoints + Math.max(attempts, 10) - 1;
      if (requiredHistory > maxHistory) {
        throw new Error(`A configuração exige ${requiredHistory} números, acima do limite de ${maxHistory}.`);
      }
      if (!byId("backtest-confirm").checked) {
        throw new Error("Confirme que o backtest fará chamadas pagas.");
      }
      setBacktestControls(true);
      const response = await fetch("/api/jev/backtest/iniciar", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrfToken },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify({
          roulette_slug: rouletteSelect.value,
          history_points: historyPoints,
          context_numbers: contextNumbers,
          chip_count: chipCount,
          attempts,
          signal_mode: signalMode,
          confirm_paid_run: true,
        }),
      });
      const data = await readResponse(response);
      renderBacktest(data);
    } catch (error) {
      byId("backtest-error").textContent = error instanceof Error ? error.message : "Falha ao iniciar o backtest.";
      byId("backtest-error").hidden = false;
      setBacktestControls(false);
      return;
    }
    setBacktestControls(false);
    await runBacktest();
  }

  async function restoreBacktest() {
    const version = ++restoreVersion;
    const slug = rouletteSelect.value;
    const key = backtestStorageKey(slug);
    const legacyId = slug === "pragmatic-auto-roulette" ? localStorage.getItem("jev-active-backtest-id") : null;
    const backtestId = localStorage.getItem(key) || legacyId;
    if (!backtestId) return;
    try {
      const response = await fetch(`/api/jev/backtest/${encodeURIComponent(backtestId)}`, {
        headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store",
      });
      const data = await readResponse(response);
      if (version !== restoreVersion || rouletteSelect.value !== slug) return;
      if ((data.roulette_slug || "pragmatic-auto-roulette") !== slug) {
        localStorage.removeItem(key);
        return;
      }
      renderBacktest(data);
      if (legacyId) localStorage.removeItem("jev-active-backtest-id");
      setBacktestControls(false);
    } catch (_error) {
      if (version !== restoreVersion) return;
      localStorage.removeItem(key);
      if (legacyId) localStorage.removeItem("jev-active-backtest-id");
    }
  }

  function openHistoryFetch() {
    if (busy) return;
    historyEditor.close();
    byId("quantity-error").hidden = true;
    dialog.showModal();
    quantityInput.focus();
  }

  rouletteSelect.addEventListener("change", changeRoulette);
  tabNames.forEach((name) => {
    byId(`${name}-tab`).addEventListener("click", () => selectTab(name));
    byId(`${name}-tab`).addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const currentIndex = tabNames.indexOf(name);
      const nextIndex = event.key === "Home" ? 0
        : event.key === "End" ? tabNames.length - 1
          : (currentIndex + (event.key === "ArrowRight" ? 1 : tabNames.length - 1)) % tabNames.length;
      selectTab(tabNames[nextIndex], true);
    });
  });
  byId("suggestion-monitor-toggle").addEventListener("click", () => {
    if (suggestionSocket && suggestionSocket.readyState < WebSocket.CLOSING) {
      stopSuggestionMonitor("Monitoramento parado.");
    } else {
      startSuggestionMonitor();
    }
  });
  byId("open-history-dialog").addEventListener("click", openHistoryFetch);
  byId("editor-fetch-history").addEventListener("click", openHistoryFetch);
  byId("open-history-editor").addEventListener("click", () => {
    historyEditor.showModal();
    historyInput.focus();
  });
  byId("close-history-editor").addEventListener("click", () => historyEditor.close());
  byId("open-groups-dialog").addEventListener("click", () => groupsDialog.showModal());
  byId("close-groups-dialog").addEventListener("click", () => groupsDialog.close());
  reverseHistoryButton.addEventListener("click", reverseHistory);
  byId("cancel-history-dialog").addEventListener("click", () => dialog.close());
  byId("history-dialog-form").addEventListener("submit", fetchHistory);
  rankingButton.addEventListener("click", rankNumbers);
  byId("ranking-evaluation-form").addEventListener("submit", evaluateRanking);
  byId("ranking-view").addEventListener("change", () => {
    suggestionState.frozen = false;
    renderRankingRows();
  });
  byId("ranking-pattern-filter").addEventListener("change", renderRankingRows);
  byId("ranking-validation-filter").addEventListener("change", renderRankingRows);
  byId("ranking-min-support").addEventListener("input", renderRankingRows);
  byId("backtest-form").addEventListener("submit", startBacktest);
  byId("backtest-pause").addEventListener("click", () => {
    if (backtestRunning) {
      backtestStopRequested = true;
      byId("backtest-pause").disabled = true;
      byId("backtest-pause").textContent = "Pausando...";
    } else {
      runBacktest();
    }
  });
  ["backtest-history-points", "backtest-context", "backtest-attempts", "backtest-signal-mode"].forEach((id) => {
    byId(id).addEventListener("input", updateBacktestEstimate);
  });
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

  updateRouletteLabels();
  validateForm();
  updateBacktestEstimate();
  restoreBacktest();
})();
