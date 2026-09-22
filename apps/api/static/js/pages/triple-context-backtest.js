(() => {
  "use strict";

  const CHIP_STEP_CENTS = 50;
  const MAX_PROFIT_CENTS = 100000000;

  function ceilToStep(value, step = CHIP_STEP_CENTS) {
    return Math.ceil(value / step) * step;
  }

  function buildFinancialPlan(topK, attempts, minimumProfitCents) {
    if (!Number.isSafeInteger(topK) || topK < 1 || topK > 35) {
      throw new Error("A progressão com lucro positivo exige um top K entre 1 e 35 números.");
    }
    if (!Number.isSafeInteger(attempts) || attempts < 1 || attempts > 100) {
      throw new Error("O limite de tentativas deve estar entre 1 e 100.");
    }
    if (!Number.isSafeInteger(minimumProfitCents) || minimumProfitCents < 1 || minimumProfitCents > MAX_PROFIT_CENTS) {
      throw new Error("O lucro mínimo deve ficar entre R$ 0,01 e R$ 1.000.000,00.");
    }
    const rows = [];
    let previousExposureCents = 0;
    const currentAttemptMargin = 36 - topK;
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      const requiredStake = (minimumProfitCents + previousExposureCents) / currentAttemptMargin;
      const stakePerNumberCents = Math.max(CHIP_STEP_CENTS, ceilToStep(requiredStake));
      const attemptStakeCents = stakePerNumberCents * topK;
      const cumulativeStakeCents = previousExposureCents + attemptStakeCents;
      const profitIfHitCents = 36 * stakePerNumberCents - cumulativeStakeCents;
      if (![stakePerNumberCents, attemptStakeCents, cumulativeStakeCents, profitIfHitCents].every(Number.isSafeInteger)) {
        throw new Error(`A progressão ultrapassa o limite de cálculo na ${attempt}ª tentativa. Reduza o top K, o lucro ou as tentativas.`);
      }
      rows.push({ attempt, stakePerNumberCents, attemptStakeCents, cumulativeStakeCents, profitIfHitCents });
      previousExposureCents = cumulativeStakeCents;
    }
    return { topK, attempts, minimumProfitCents, rows, maxExposureCents: previousExposureCents };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { buildFinancialPlan };
    return;
  }

  const $ = (id) => document.getElementById(id);
  const form = $("backtest-form");
  const parameterFields = [
    { name: "history_limit", element: $("history-limit"), min: 6, max: 50000, label: "O histórico" },
    { name: "top_k", element: $("top-k"), min: 1, max: 37, label: "O top K" },
    { name: "attempts", element: $("attempts"), min: 1, max: 100, label: "O limite de tentativas" },
  ];
  const integer = new Intl.NumberFormat("pt-BR");
  const percentage = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const decimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  const currency = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const datetime = new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo",
  });
  const PAGE_SIZE = 50;
  const REQUEST_TIMEOUT_MS = 60000;
  const statusLabels = { win: "Vitória", loss: "Derrota", incomplete: "Incompleto", repeated_trio: "Números repetidos", no_evidence: "Sem evidência", overlap_skipped: "Ignorado por sobreposição" };
  const qualityDimensions = {
    support: {
      field: "occurrences",
      description: "Quantidade de vezes que o trio apareceu na base do catálogo.",
      bins: [
        { label: "1–2 ocorrências", test: (value) => value >= 1 && value <= 2 },
        { label: "3–5 ocorrências", test: (value) => value >= 3 && value <= 5 },
        { label: "6–10 ocorrências", test: (value) => value >= 6 && value <= 10 },
        { label: "11–20 ocorrências", test: (value) => value >= 11 && value <= 20 },
        { label: "21 ou mais", test: (value) => value >= 21 },
        { label: "Sem ocorrências", test: (value) => value === 0 },
      ],
    },
    complete_coverage: {
      field: "complete_coverage",
      description: "Proporção das ocorrências que possuíam toda a profundidade de contexto escolhida.",
      bins: [
        { label: "Abaixo de 50%", test: (value) => value < 0.5 },
        { label: "50% a 74,99%", test: (value) => value >= 0.5 && value < 0.75 },
        { label: "75% a 89,99%", test: (value) => value >= 0.75 && value < 0.9 },
        { label: "90% a 100%", test: (value) => value >= 0.9 },
      ],
    },
    direct_lift: {
      field: "direct_lift",
      description: "Taxa de acertos exatos do top K dividida pela cobertura aleatória K/37. Valor acima de 1 indica concentração superior à base uniforme.",
      bins: [
        { label: "Abaixo de 1,00×", test: (value) => value < 1 },
        { label: "1,00× a 1,09×", test: (value) => value >= 1 && value < 1.1 },
        { label: "1,10× a 1,24×", test: (value) => value >= 1.1 && value < 1.25 },
        { label: "1,25× a 1,49×", test: (value) => value >= 1.25 && value < 1.5 },
        { label: "1,50× ou mais", test: (value) => value >= 1.5 },
      ],
    },
    score_concentration_lift: {
      field: "score_concentration_lift",
      description: "Parcela do score no top K comparada à participação uniforme K/37.",
      bins: [
        { label: "Abaixo de 1,00×", test: (value) => value < 1 },
        { label: "1,00× a 1,09×", test: (value) => value >= 1 && value < 1.1 },
        { label: "1,10× a 1,24×", test: (value) => value >= 1.1 && value < 1.25 },
        { label: "1,25× a 1,49×", test: (value) => value >= 1.25 && value < 1.5 },
        { label: "1,50× ou mais", test: (value) => value >= 1.5 },
      ],
    },
    cutoff_margin_per_event: {
      field: "cutoff_margin_per_event",
      description: "Diferença normalizada entre o score do último selecionado e o primeiro excluído. Top 37 não possui corte.",
      bins: [
        { label: "Empatado", test: (value) => value === 0 },
        { label: "Acima de 0 até 0,10", test: (value) => value > 0 && value <= 0.1 },
        { label: "Acima de 0,10 até 0,25", test: (value) => value > 0.1 && value <= 0.25 },
        { label: "Acima de 0,25 até 0,50", test: (value) => value > 0.25 && value <= 0.5 },
        { label: "Acima de 0,50", test: (value) => value > 0.5 },
      ],
    },
    order_dominance: {
      field: "order_dominance",
      description: "No modo sem ordem, mostra quanto das ocorrências veio da permutação mais frequente. Não se aplica à ordem exata.",
      bins: [
        { label: "Até 25%", test: (value) => value <= 0.25 },
        { label: "Acima de 25% até 40%", test: (value) => value > 0.25 && value <= 0.4 },
        { label: "Acima de 40% até 60%", test: (value) => value > 0.4 && value <= 0.6 },
        { label: "Acima de 60%", test: (value) => value > 0.6 },
      ],
    },
  };
  let requestId = 0;
  let activeController = null;
  let currentReport = null;
  let currentRankingUpdates = new Map();
  let currentPage = 1;
  let currentFinancialPlan = null;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function parseMoneyToCents(raw) {
    const normalized = raw.trim().replace(/\s+/g, "").replace(/^R\$/i, "");
    if (!/^\d{1,7}(?:[,.]\d{1,2})?$/.test(normalized)) return null;
    const value = Number(normalized.replace(",", "."));
    const cents = Math.round(value * 100);
    return Number.isSafeInteger(cents) && cents >= 1 && cents <= MAX_PROFIT_CENTS ? cents : null;
  }

  function money(cents, signed = false) {
    const value = cents / 100;
    if (signed && value > 0) return `+${currency.format(value)}`;
    return currency.format(value);
  }

  function showFinancialError(message) {
    currentFinancialPlan = null;
    $("financial-error").textContent = message;
    $("financial-error").hidden = false;
    $("minimum-profit").setAttribute("aria-invalid", "true");
    $("financial-projection").hidden = true;
    if (currentReport) {
      renderFinancialReport(currentReport);
      renderQualityReport(currentReport);
      renderPage(currentPage);
    }
  }

  function clearFinancialError() {
    $("financial-error").textContent = "";
    $("financial-error").hidden = true;
    $("minimum-profit").removeAttribute("aria-invalid");
  }

  function renderFinancialProjection(plan) {
    const fragment = document.createDocumentFragment();
    plan.rows.forEach((row) => {
      const tr = element("tr");
      tr.append(
        element("td", "", `${integer.format(row.attempt)}ª`),
        element("td", "", money(row.stakePerNumberCents)),
        element("td", "", money(row.attemptStakeCents)),
        element("td", "", money(row.cumulativeStakeCents)),
        element("td", "financial-profit-cell", money(row.profitIfHitCents, true)),
      );
      fragment.append(tr);
    });
    $("financial-projection-body").replaceChildren(fragment);
    $("financial-projection-recap").textContent = `Top ${integer.format(plan.topK)} · ${integer.format(plan.attempts)} tentativas · lucro mínimo ${money(plan.minimumProfitCents)}`;
    $("financial-max-exposure").textContent = `Exposição máxima ${money(plan.maxExposureCents)}`;
    $("financial-projection").hidden = false;
  }

  function calculateFinancialPlan({ focusOnError = true } = {}) {
    clearFinancialError();
    const topKRaw = $("top-k").value.trim();
    const attemptsRaw = $("attempts").value.trim();
    const topK = Number(topKRaw);
    const attempts = Number(attemptsRaw);
    const minimumProfitCents = parseMoneyToCents($("minimum-profit").value);
    try {
      if (!/^\d+$/.test(topKRaw) || !Number.isSafeInteger(topK) || topK < 1 || topK > 37) {
        throw new Error("Informe um top K válido antes de calcular as fichas.");
      }
      if (!/^\d+$/.test(attemptsRaw) || !Number.isSafeInteger(attempts) || attempts < 1 || attempts > 100) {
        throw new Error("Informe um limite de tentativas válido antes de calcular as fichas.");
      }
      if (minimumProfitCents === null) {
        throw new Error("O lucro mínimo deve ficar entre R$ 0,01 e R$ 1.000.000,00, com no máximo duas casas decimais.");
      }
      currentFinancialPlan = buildFinancialPlan(topK, attempts, minimumProfitCents);
      renderFinancialProjection(currentFinancialPlan);
      if (currentReport) {
        renderFinancialReport(currentReport);
        renderQualityReport(currentReport);
        renderPage(currentPage);
      }
      return currentFinancialPlan;
    } catch (error) {
      showFinancialError(error.message);
      if (focusOnError) $("minimum-profit").focus();
      return null;
    }
  }

  function financialOutcome(signal, plan) {
    if (signal.status === "win") {
      const row = plan.rows[signal.first_hit_attempt - 1];
      return row ? { pnlCents: row.profitIfHitCents, stakedCents: row.cumulativeStakeCents } : null;
    }
    if (signal.status === "loss") {
      return { pnlCents: -plan.maxExposureCents, stakedCents: plan.maxExposureCents };
    }
    return null;
  }

  function renderFinancialChart(balances) {
    const container = $("financial-chart");
    if (!balances.length) {
      container.replaceChildren(element("p", "distribution-empty", "Nenhum sinal encerrado para formar a evolução financeira."));
      container.setAttribute("aria-label", "Nenhum sinal encerrado para formar a evolução financeira");
      return;
    }
    const values = [0, ...balances];
    const width = 900;
    const height = 250;
    const padding = 22;
    const minimum = Math.min(0, ...values);
    const maximum = Math.max(0, ...values);
    const range = Math.max(1, maximum - minimum);
    const x = (index) => padding + index / Math.max(1, values.length - 1) * (width - padding * 2);
    const y = (value) => padding + (maximum - value) / range * (height - padding * 2);
    const namespace = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(namespace, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const zero = document.createElementNS(namespace, "line");
    zero.setAttribute("x1", String(padding));
    zero.setAttribute("x2", String(width - padding));
    zero.setAttribute("y1", String(y(0)));
    zero.setAttribute("y2", String(y(0)));
    zero.setAttribute("class", "financial-zero-line");
    const polyline = document.createElementNS(namespace, "polyline");
    polyline.setAttribute("points", values.map((value, index) => `${x(index).toFixed(2)},${y(value).toFixed(2)}`).join(" "));
    polyline.setAttribute("class", balances[balances.length - 1] >= 0 ? "financial-balance-line positive" : "financial-balance-line negative");
    svg.append(zero, polyline);
    const labels = element("div", "financial-chart-labels");
    labels.append(element("span", "", `Mín. ${money(minimum)}`), element("span", "", `Máx. ${money(maximum)}`));
    container.replaceChildren(svg, labels);
    container.setAttribute("aria-label", `Evolução do saldo em ${integer.format(balances.length)} sinais encerrados; saldo final ${money(balances[balances.length - 1], true)}; mínimo ${money(minimum)}; máximo ${money(maximum)}.`);
  }

  function renderFinancialReport(data) {
    const error = $("financial-report-error");
    const content = $("financial-report-content");
    if (!currentFinancialPlan || currentFinancialPlan.topK !== data.config.top_k || currentFinancialPlan.attempts !== data.config.attempts) {
      error.textContent = "Calcule uma progressão válida para este top K e limite de tentativas.";
      error.hidden = false;
      content.hidden = true;
      return;
    }
    error.hidden = true;
    content.hidden = false;
    let balanceCents = 0;
    let totalStakedCents = 0;
    let peakCents = 0;
    let maxDrawdownCents = 0;
    const balances = [];
    let closedSignals = 0;
    data.signals.forEach((signal) => {
      const outcome = financialOutcome(signal, currentFinancialPlan);
      if (!outcome) return;
      closedSignals += 1;
      totalStakedCents += outcome.stakedCents;
      balanceCents += outcome.pnlCents;
      peakCents = Math.max(peakCents, balanceCents);
      maxDrawdownCents = Math.max(maxDrawdownCents, peakCents - balanceCents);
      balances.push(balanceCents);
    });
    $("financial-report-recap").textContent = `${integer.format(closedSignals)} sinais encerrados · top ${integer.format(currentFinancialPlan.topK)} · lucro mínimo ${money(currentFinancialPlan.minimumProfitCents)} por sinal vencedor.`;
    $("financial-net-result").textContent = money(balanceCents, true);
    $("financial-net-result").className = balanceCents >= 0 ? "financial-positive" : "financial-negative";
    $("financial-total-staked").textContent = money(totalStakedCents);
    $("financial-report-exposure").textContent = money(currentFinancialPlan.maxExposureCents);
    $("financial-max-drawdown").textContent = money(maxDrawdownCents);
    renderFinancialChart(balances);
  }

  function median(values) {
    if (!values.length) return null;
    const ordered = values.slice().sort((left, right) => left - right);
    const middle = Math.floor(ordered.length / 2);
    return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
  }

  function qualityValue(value, suffix = "") {
    return value === null ? "—" : `${decimal.format(value)}${suffix}`;
  }

  function longestLossSequence(signals) {
    let longest = 0;
    let current = 0;
    signals.forEach((signal) => {
      if (signal.status === "loss") {
        current += 1;
        longest = Math.max(longest, current);
      } else if (signal.status === "win") current = 0;
    });
    return longest;
  }

  function renderQualityBuckets(data) {
    const dimension = qualityDimensions[$("quality-dimension").value] || qualityDimensions.support;
    $("quality-dimension-description").textContent = dimension.description;
    const bins = [...dimension.bins.map((bin) => ({ ...bin, signals: [] })),
      { label: "Sem dados para esta métrica", test: (value) => value === null, signals: [] }];
    data.signals.forEach((signal) => {
      if (!signal.quality) return;
      const value = signal.quality[dimension.field];
      const bin = bins.find((candidate) => candidate.test(value));
      if (bin) bin.signals.push(signal);
    });
    const fragment = document.createDocumentFragment();
    bins.forEach((bin) => {
      const closed = bin.signals.filter((signal) => signal.status === "win" || signal.status === "loss");
      const wins = closed.filter((signal) => signal.status === "win").length;
      const losses = closed.length - wins;
      const blocked = bin.signals.filter((signal) => signal.status === "overlap_skipped").length;
      let pnlCents = 0;
      let hasFinancial = Boolean(currentFinancialPlan
        && currentFinancialPlan.topK === data.config.top_k
        && currentFinancialPlan.attempts === data.config.attempts);
      if (hasFinancial) {
        closed.forEach((signal) => { pnlCents += financialOutcome(signal, currentFinancialPlan).pnlCents; });
      }
      const row = element("tr");
      row.append(
        element("td", "", bin.label),
        element("td", "", integer.format(bin.signals.length)),
        element("td", "", integer.format(closed.length)),
        element("td", "", integer.format(blocked)),
        element("td", "", integer.format(wins)),
        element("td", "", integer.format(losses)),
        element("td", "", closed.length ? `${percentage.format(wins * 100 / closed.length)}%` : "—"),
        element("td", hasFinancial ? (pnlCents >= 0 ? "financial-positive" : "financial-negative") : "", hasFinancial ? money(pnlCents, true) : "—"),
        element("td", "", integer.format(longestLossSequence(closed))),
      );
      fragment.append(row);
    });
    $("quality-buckets-body").replaceChildren(fragment);
  }

  function renderQualityReport(data) {
    const qualitySignals = data.signals.filter((signal) => signal.quality);
    const directLifts = qualitySignals.map((signal) => signal.quality.direct_lift).filter((value) => value !== null);
    const concentrationLifts = qualitySignals.map((signal) => signal.quality.score_concentration_lift).filter((value) => value !== null);
    $("quality-signals").textContent = integer.format(qualitySignals.length);
    $("quality-median-occurrences").textContent = qualityValue(median(qualitySignals.map((signal) => signal.quality.occurrences)));
    $("quality-median-direct-lift").textContent = qualityValue(median(directLifts), "×");
    $("quality-median-concentration").textContent = qualityValue(median(concentrationLifts), "×");
    renderQualityBuckets(data);
  }

  function setBusy(busy) {
    $("backtest-results-region").setAttribute("aria-busy", String(busy));
    $("run-button").disabled = busy;
    $("run-label").textContent = busy ? "Executando backtest…" : "Executar backtest";
    $("cancel-button").hidden = !busy;
  }

  function clearValidation() {
    $("backtest-form-error").textContent = "";
    $("backtest-form-error").hidden = true;
    parameterFields.forEach(({ element: input }) => input.removeAttribute("aria-invalid"));
  }

  function clearPageError() {
    $("page-error").textContent = "";
    $("page-error").hidden = true;
    $("page-number").removeAttribute("aria-invalid");
  }

  function invalidate(message = "Configuração alterada. Execute novamente para atualizar o resultado.") {
    requestId += 1;
    if (activeController) activeController.abort();
    activeController = null;
    currentReport = null;
    currentRankingUpdates = new Map();
    currentPage = 1;
    clearValidation();
    clearPageError();
    setBusy(false);
    $("backtest-report").hidden = true;
    $("backtest-error").hidden = true;
    $("backtest-empty").hidden = false;
    $("backtest-status").textContent = message;
  }

  function readConfig() {
    const config = {};
    let firstInvalid = null;
    const errors = [];
    parameterFields.forEach(({ name, element: input, min, max, label }) => {
      const raw = input.value.trim();
      const number = Number(raw);
      if (!/^\d+$/.test(raw) || !Number.isSafeInteger(number) || number < min || number > max) {
        input.setAttribute("aria-invalid", "true");
        firstInvalid = firstInvalid || input;
        errors.push(`${label} deve ser um inteiro entre ${integer.format(min)} e ${integer.format(max)}.`);
      } else {
        config[name] = number;
      }
    });
    if (errors.length) {
      $("backtest-form-error").textContent = errors.join(" ");
      $("backtest-form-error").hidden = false;
      firstInvalid.focus();
      return null;
    }
    config.direction = form.elements.direction.value;
    config.ordered = form.elements.ordered.value === "true";
    config.prevent_overlapping_bets = form.elements.prevent_overlapping_bets.checked;
    config.recalculate_ranking_after_loss = form.elements.recalculate_ranking_after_loss.checked;
    return config;
  }

  function validateResponse(data, request) {
    const count = (value) => Number.isSafeInteger(value) && value >= 0;
    const number = (value) => count(value) && value <= 36;
    const optionalCount = (value) => value === null || count(value);
    const finite = (value) => Number.isFinite(value) && value >= 0;
    const optionalFinite = (value) => value === null || finite(value);
    const validDate = (value) => typeof value === "string" && Number.isFinite(Date.parse(value));
    const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
    const fail = () => { throw new Error("A API retornou um resultado incompleto ou inconsistente. Tente novamente."); };
    const validQuality = (quality) => {
      const qualityCounts = ["occurrences", "depth", "context_events", "complete_occurrences", "top_k_direct_hits"];
      const qualityNumbers = ["context_coverage", "complete_coverage", "direct_hit_rate", "direct_lift",
        "top_k_score", "total_score", "score_concentration", "score_concentration_lift", "cutoff_score",
        "next_score", "cutoff_margin_per_event", "leader_margin_per_event", "order_dominance"];
      return object(quality) && qualityCounts.every((key) => count(quality[key]))
        && qualityNumbers.every((key) => optionalFinite(quality[key]))
        && quality.depth === (request.direction === "forward" ? 20 : 10)
        && quality.complete_occurrences <= quality.occurrences
        && quality.top_k_direct_hits <= quality.context_events
        && ![quality.context_coverage, quality.complete_coverage, quality.direct_hit_rate,
          quality.score_concentration, quality.order_dominance]
          .some((value) => value !== null && value > 1)
        && (request.top_k === 37) === (quality.next_score === null)
        && (!request.ordered || quality.order_dominance === null);
    };
    if (!object(data) || !object(data.config) || !Object.entries(request).every(([key, value]) => data.config[key] === value)
        || !object(data.source) || !count(data.source.records) || data.source.records > request.history_limit
        || data.source.requested_records !== request.history_limit || !count(data.source.gaps_over_300_seconds)
        || ![data.source.first_timestamp, data.source.last_timestamp, data.source.read_at].every(validDate)
        || !object(data.catalog) || typeof data.catalog.build_id !== "string" || !data.catalog.build_id
        || !object(data.catalog.source) || !count(data.catalog.source.records)
        || ![data.catalog.source.first_timestamp, data.catalog.source.last_timestamp].every(validDate)
        || !object(data.methodology) || typeof data.methodology.description !== "string" || !data.methodology.description
        || !(data.methodology.warning === null || typeof data.methodology.warning === "string")
        || !object(data.summary) || !Array.isArray(data.signals)
        || !Array.isArray(data.ranking_updates)) fail();
    const summary = data.summary;
    const fields = ["total_signals", "evaluated", "wins", "losses", "incomplete", "repeated_trio", "no_evidence", "overlap_skipped", "recovered_losses", "unresolved_losses", "ranking_recalculations", "ranking_reuses"];
    if (!fields.every((key) => count(summary[key]))
        || !(summary.accuracy_pct === null || (Number.isFinite(summary.accuracy_pct) && summary.accuracy_pct >= 0 && summary.accuracy_pct <= 100))
        || !optionalCount(summary.max_recovery_attempt)
        || summary.total_signals !== data.signals.length
        || summary.total_signals !== summary.wins + summary.losses + summary.incomplete + summary.repeated_trio + summary.no_evidence + summary.overlap_skipped
        || summary.recovered_losses + summary.unresolved_losses !== summary.losses
        || !Array.isArray(summary.win_attempts) || !Array.isArray(summary.recovery_attempts)) fail();
    if (!summary.win_attempts.every((row) => object(row) && count(row.attempt) && row.attempt >= 1
          && row.attempt <= request.attempts && count(row.count))
        || !summary.recovery_attempts.every((row) => object(row) && count(row.attempt) && row.attempt > request.attempts
          && row.extra_attempts === row.attempt - request.attempts && count(row.count))
        || summary.win_attempts.reduce((sum, row) => sum + row.count, 0) !== summary.wins
        || summary.recovery_attempts.reduce((sum, row) => sum + row.count, 0) !== summary.recovered_losses) fail();
    const observedStatuses = { win: 0, loss: 0, incomplete: 0, repeated_trio: 0, no_evidence: 0, overlap_skipped: 0 };
    let observedRecalculations = 0;
    let observedReuses = 0;
    const rankingUpdates = new Map();
    for (const ranking of data.ranking_updates) {
      if (!object(ranking) || !count(ranking.target_index) || ranking.target_index < 3
          || ranking.target_index >= data.source.records || rankingUpdates.has(ranking.target_index)
          || !["recalculated", "reused"].includes(ranking.source)
          || !(ranking.reuse_reason === null || ["repeated_trio", "no_evidence"].includes(ranking.reuse_reason))
          || !Array.isArray(ranking.trio) || ranking.trio.length !== 3 || !ranking.trio.every(number)
          || !Array.isArray(ranking.ranking_trio) || ranking.ranking_trio.length !== 3
          || !ranking.ranking_trio.every(number)
          || !Array.isArray(ranking.selected_numbers) || ranking.selected_numbers.length !== request.top_k
          || !ranking.selected_numbers.every(number) || new Set(ranking.selected_numbers).size !== request.top_k
          || !validQuality(ranking.quality)) fail();
      rankingUpdates.set(ranking.target_index, ranking);
    }
    if (!request.recalculate_ranking_after_loss && rankingUpdates.size) fail();
    for (const signal of data.signals) {
      if (!object(signal) || !Object.hasOwn(statusLabels, signal.status)
          || !(count(signal.signal_id) || (typeof signal.signal_id === "string" && signal.signal_id.length > 0))
          || !count(signal.end_index) || signal.end_index < 2 || signal.end_index >= data.source.records
          || !validDate(signal.trigger_timestamp)
          || !Array.isArray(signal.trio) || signal.trio.length !== 3 || !signal.trio.every(number)
          || !Array.isArray(signal.selected_numbers) || !signal.selected_numbers.every(number)
          || new Set(signal.selected_numbers).size !== signal.selected_numbers.length
          || !count(signal.available_attempts) || signal.available_attempts > request.attempts
          || !Array.isArray(signal.checked_numbers) || !signal.checked_numbers.every(number)
          || !optionalCount(signal.first_hit_attempt) || !optionalCount(signal.hit_rank)
          || !(signal.hit_number === null || number(signal.hit_number))
          || !optionalCount(signal.recovery_extra_attempts) || !optionalCount(signal.followup_observed)
          || !count(signal.attempt_ranking_count) || !count(signal.ranking_recalculations)
          || !count(signal.ranking_reuses)
          || !optionalCount(signal.blocked_until_position)
          || !(signal.blocked_by_signal_id === null || count(signal.blocked_by_signal_id))) fail();
      const noRanking = signal.status === "repeated_trio" || signal.status === "no_evidence";
      if (signal.selected_numbers.length !== (noRanking ? 0 : request.top_k)) fail();
      if (signal.status === "repeated_trio") {
        if (signal.quality !== null) fail();
      } else if (!validQuality(signal.quality)) fail();
      const expectedRankings = request.recalculate_ranking_after_loss && !noRanking
        && signal.status !== "overlap_skipped"
        ? (signal.status === "win" ? signal.first_hit_attempt : signal.available_attempts) : 0;
      if (signal.attempt_ranking_count !== expectedRankings) fail();
      const signalUpdates = [];
      for (let attempt = 1; attempt <= signal.attempt_ranking_count; attempt += 1) {
        const ranking = rankingUpdates.get(signal.end_index + attempt);
        if (!ranking) fail();
        signalUpdates.push({ ...ranking, source: attempt === 1 ? "initial" : ranking.source });
      }
      if (signal.ranking_recalculations !== signalUpdates.filter((row) => row.source === "recalculated").length
          || signal.ranking_reuses !== signalUpdates.filter((row) => row.source === "reused").length) fail();
      observedRecalculations += signal.ranking_recalculations;
      observedReuses += signal.ranking_reuses;
      if (signal.status === "overlap_skipped" && (signal.available_attempts !== 0
          || signal.checked_numbers.length !== 0 || signal.blocked_by_signal_id === null
          || signal.blocked_until_position === null || signal.first_hit_attempt !== null)) fail();
      if (signal.status !== "overlap_skipped"
          && (signal.blocked_by_signal_id !== null || signal.blocked_until_position !== null)) fail();
      if (signal.status === "loss" && signal.followup_observed === null) fail();
      if (signal.recovery_extra_attempts !== null && (signal.status !== "loss" || signal.recovery_extra_attempts < 1
          || signal.first_hit_attempt !== request.attempts + signal.recovery_extra_attempts)) fail();
      observedStatuses[signal.status] += 1;
    }
    if (observedStatuses.win !== summary.wins || observedStatuses.loss !== summary.losses
        || observedStatuses.incomplete !== summary.incomplete || observedStatuses.repeated_trio !== summary.repeated_trio
        || observedStatuses.no_evidence !== summary.no_evidence
        || observedStatuses.overlap_skipped !== summary.overlap_skipped
        || observedRecalculations !== summary.ranking_recalculations
        || observedReuses !== summary.ranking_reuses) fail();
    if (request.recalculate_ranking_after_loss && data.ranking_updates.length !== rankingUpdates.size) fail();
    return data;
  }

  function renderDistribution(containerId, rows, label, emptyMessage) {
    const container = $(containerId);
    const fragment = document.createDocumentFragment();
    const visibleRows = rows.slice().sort((a, b) => a.attempt - b.attempt);
    if (!visibleRows.length || !visibleRows.some((row) => row.count > 0)) {
      fragment.append(element("p", "distribution-empty", emptyMessage));
      container.removeAttribute("tabindex");
      container.removeAttribute("role");
      container.removeAttribute("aria-label");
    } else {
      const largest = Math.max(...visibleRows.map((row) => row.count));
      container.setAttribute("tabindex", "0");
      container.setAttribute("role", "region");
      container.setAttribute("aria-label", containerId === "win-distribution" ? "Distribuição das vitórias por tentativa" : "Distribuição dos primeiros acertos após as derrotas");
      visibleRows.forEach((row) => {
        const item = element("div", "distribution-row");
        item.append(element("span", "", label(row)));
        const track = element("div", "distribution-track");
        track.setAttribute("aria-hidden", "true");
        const fill = element("div", "distribution-fill");
        fill.style.width = `${row.count / largest * 100}%`;
        track.append(fill);
        const total = element("strong", "", integer.format(row.count));
        total.setAttribute("aria-label", `${integer.format(row.count)} sinais`);
        item.append(track, total);
        fragment.append(item);
      });
    }
    container.replaceChildren(fragment);
  }

  function signalDetails(signal, attempts) {
    if (signal.status === "win") {
      return `${integer.format(signal.first_hit_attempt)}ª tentativa · nº ${signal.hit_number}`;
    }
    if (signal.status === "loss") return `Sem acerto nas ${integer.format(attempts)} tentativas`;
    if (signal.status === "incomplete") return `${integer.format(signal.available_attempts)} de ${integer.format(attempts)} giros disponíveis`;
    if (signal.status === "repeated_trio") return "Trio fora do catálogo de três números distintos";
    if (signal.status === "overlap_skipped") return `Bloqueado pelo sinal #${signal.blocked_by_signal_id} até a posição ${integer.format(signal.blocked_until_position)}`;
    return "Sem evidência no ranking escolhido";
  }

  function renderPage(page) {
    if (!currentReport) return;
    const signals = currentReport.signals;
    const totalPages = Math.max(1, Math.ceil(signals.length / PAGE_SIZE));
    currentPage = Math.max(1, Math.min(page, totalPages));
    const offset = (currentPage - 1) * PAGE_SIZE;
    const fragment = document.createDocumentFragment();
    signals.slice(offset, offset + PAGE_SIZE).forEach((signal) => {
      const attemptRankings = [];
      for (let attempt = 1; attempt <= signal.attempt_ranking_count; attempt += 1) {
        const ranking = currentRankingUpdates.get(signal.end_index + attempt);
        if (ranking) attemptRankings.push({ ...ranking, attempt,
          source: attempt === 1 ? "initial" : ranking.source });
      }
      const row = element("tr");
      const idCell = element("td");
      idCell.append(element("strong", "", `#${signal.signal_id}`));
      const time = element("time", "", datetime.format(new Date(signal.trigger_timestamp)));
      time.dateTime = signal.trigger_timestamp;
      idCell.append(time);
      const trioCell = element("td");
      const trio = element("div", "signal-trio");
      signal.trio.forEach((number, index) => {
        if (index) {
          const arrow = element("span", "trio-arrow", "→");
          arrow.setAttribute("aria-hidden", "true");
          trio.append(arrow);
        }
        trio.append(element("span", "", String(number)));
      });
      trio.setAttribute("aria-label", `Trio cronológico: ${signal.trio.join(", ")}; ${signal.trio[2]} é o mais recente`);
      trioCell.append(trio, element("span", "cell-secondary", `Posições ${integer.format(signal.end_index - 1)}–${integer.format(signal.end_index + 1)}`));
      const picksCell = element("td");
      if (currentReport.config.recalculate_ranking_after_loss && attemptRankings.length) {
        const disclosure = element("details", "signal-details");
        disclosure.append(element("summary", "", `${integer.format(attemptRankings.length)} rankings por tentativa`));
        const rankingList = element("div", "attempt-ranking-list");
        attemptRankings.forEach((ranking) => {
          const item = element("div", "attempt-ranking");
          const source = ranking.source === "initial" ? "ranking inicial"
            : ranking.source === "recalculated" ? "recalculado" : "ranking anterior reutilizado";
          item.append(element("strong", "", `${integer.format(ranking.attempt)}ª tentativa · ${source}`));
          const numbers = element("div", "selected-numbers");
          ranking.selected_numbers.forEach((number) => numbers.append(element("span", "selected-number", String(number))));
          item.append(numbers);
          if (ranking.source === "reused") {
            const reason = ranking.reuse_reason === "repeated_trio" ? "o novo trio contém repetição"
              : "o novo trio não possui evidência";
            item.append(element("small", "", `Mantido o ranking de ${ranking.ranking_trio.join(" → ")} porque ${reason}.`));
          } else {
            item.append(element("small", "", `Trio usado: ${ranking.ranking_trio.join(" → ")}.`));
          }
          rankingList.append(item);
        });
        disclosure.append(rankingList);
        picksCell.append(disclosure);
      } else if (signal.selected_numbers.length) {
        const disclosure = element("details", "signal-details");
        disclosure.append(element("summary", "", `${integer.format(signal.selected_numbers.length)} números fixos`));
        const numbers = element("div", "selected-numbers");
        signal.selected_numbers.forEach((number) => numbers.append(element("span", "selected-number", String(number))));
        disclosure.append(numbers);
        picksCell.append(disclosure);
      } else picksCell.textContent = "Sem ranking";
      if (signal.quality) {
        const quality = signal.quality;
        const qualityDisclosure = element("details", "signal-details quality-details");
        qualityDisclosure.append(element("summary", "", currentReport.config.recalculate_ranking_after_loss ? "Ver qualidade inicial" : "Ver qualidade"));
        const facts = element("div", "quality-facts");
        const factRows = [
          ["Ocorrências", integer.format(quality.occurrences)],
          ["Cobertura completa", quality.complete_coverage === null ? "—" : `${percentage.format(quality.complete_coverage * 100)}%`],
          ["Cobertura do contexto", quality.context_coverage === null ? "—" : `${percentage.format(quality.context_coverage * 100)}%`],
          ["Lift direto", qualityValue(quality.direct_lift, "×")],
          ["Concentração relativa", qualityValue(quality.score_concentration_lift, "×")],
          ["Margem do corte", qualityValue(quality.cutoff_margin_per_event)],
        ];
        if (quality.order_dominance !== null) {
          factRows.push(["Dominância da ordem", `${percentage.format(quality.order_dominance * 100)}%`]);
        }
        factRows.forEach(([label, value]) => {
          const fact = element("span");
          fact.append(element("small", "", label), element("strong", "", value));
          facts.append(fact);
        });
        qualityDisclosure.append(facts);
        picksCell.append(qualityDisclosure);
      }
      const stateCell = element("td");
      stateCell.append(element("span", `status-chip status-${signal.status}`, statusLabels[signal.status]));
      if (currentFinancialPlan && currentFinancialPlan.topK === currentReport.config.top_k
          && currentFinancialPlan.attempts === currentReport.config.attempts) {
        const outcome = financialOutcome(signal, currentFinancialPlan);
        if (outcome) stateCell.append(element("span", `cell-secondary ${outcome.pnlCents >= 0 ? "financial-positive" : "financial-negative"}`, money(outcome.pnlCents, true)));
      }
      const detailCell = element("td", "", signalDetails(signal, currentReport.config.attempts));
      if (signal.status === "win" && signal.hit_rank !== null) {
        detailCell.append(element("span", "cell-secondary", `Posição ${signal.hit_rank} do ranking${currentReport.config.recalculate_ranking_after_loss ? ` da ${signal.first_hit_attempt}ª tentativa` : ""}`));
      }
      if (signal.checked_numbers.length) {
        const checked = element("details", "signal-details");
        checked.append(element("summary", "", `Ver ${integer.format(signal.checked_numbers.length)} giros conferidos`),
          element("p", "", signal.checked_numbers.join(" → ")));
        detailCell.append(checked);
      }
      const recoveryCell = element("td");
      if (signal.status !== "loss") recoveryCell.textContent = "—";
      else if (signal.recovery_extra_attempts !== null) {
        const total = currentReport.config.attempts + signal.recovery_extra_attempts;
        recoveryCell.textContent = `${integer.format(total)}ª tentativa · +${integer.format(signal.recovery_extra_attempts)} após o limite`;
        recoveryCell.append(element("span", "cell-secondary", currentReport.config.recalculate_ranking_after_loss
          ? "Acerto posterior com ranking recalculado; a derrota permanece."
          : "Acerto posterior; a derrota permanece."));
        if (signal.hit_number !== null) recoveryCell.append(element("span", "cell-secondary", `Número ${signal.hit_number}`));
      } else {
        recoveryCell.textContent = `Sem acerto em ${integer.format(signal.followup_observed)} giros adicionais observados`;
        recoveryCell.append(element("span", "cell-secondary", "Acompanhamento encerrado no fim do histórico."));
      }
      row.append(idCell, trioCell, picksCell, stateCell, detailCell, recoveryCell);
      fragment.append(row);
    });
    if (!signals.length) {
      const row = element("tr");
      const cell = element("td", "", "Nenhum sinal foi formado neste histórico.");
      cell.colSpan = 6;
      row.append(cell);
      fragment.append(row);
    }
    $("signals-body").replaceChildren(fragment);
    $("page-range").textContent = signals.length
      ? `Sinais ${integer.format(offset + 1)}–${integer.format(Math.min(offset + PAGE_SIZE, signals.length))} de ${integer.format(signals.length)}`
      : "Nenhum sinal";
    $("page-number").value = String(currentPage);
    $("page-total").textContent = `de ${integer.format(totalPages)}`;
    $("page-first").disabled = $("page-previous").disabled = currentPage === 1;
    $("page-last").disabled = $("page-next").disabled = currentPage === totalPages;
    $("page-number").disabled = $("page-go").disabled = signals.length === 0;
    clearPageError();
  }

  function renderReport(data) {
    currentReport = data;
    currentRankingUpdates = new Map(data.ranking_updates.map((ranking) => [ranking.target_index, ranking]));
    currentPage = 1;
    const summary = data.summary;
    const config = data.config;
    $("backtest-recap").textContent = `${integer.format(data.source.records)} resultados · top ${config.top_k} ${config.recalculate_ranking_after_loss ? "recalculado após falhas" : "fixo"} · ${config.attempts} tentativas · ${config.ordered ? "ordem exata" : "qualquer ordem"} · ranking ${config.direction === "forward" ? "à frente" : "de trás"} · ${config.prevent_overlapping_bets ? "sem apostas sobrepostas" : "apostas sobrepostas permitidas"}`;
    $("methodology-description").textContent = data.methodology.description;
    $("methodology-warning").textContent = data.methodology.warning || "";
    $("methodology-warning").hidden = !data.methodology.warning;
    $("summary-accuracy").textContent = summary.accuracy_pct === null ? "—" : `${percentage.format(summary.accuracy_pct)}%`;
    ["wins", "losses", "incomplete"].forEach((key) => { $(`summary-${key}`).textContent = integer.format(summary[key]); });
    const closed = summary.wins + summary.losses;
    $("summary-denominator").textContent = closed
      ? `Assertividade: ${integer.format(summary.wins)} vitórias em ${integer.format(closed)} sinais encerrados. Incompletos, sinais sem ranking e entradas bloqueadas ficam fora desse denominador.`
      : "Ainda não há vitórias ou derrotas para calcular a assertividade. Incompletos, sinais sem ranking e entradas bloqueadas ficam fora do denominador.";
    $("summary-total").textContent = `${integer.format(summary.total_signals)} sinais formados`;
    $("summary-skipped").textContent = `${integer.format(summary.repeated_trio + summary.no_evidence)} sem ranking`;
    $("summary-overlap").textContent = `Ignorados por sobreposição: ${integer.format(summary.overlap_skipped)}`;
    $("summary-repeated").textContent = `Com número repetido no trio: ${integer.format(summary.repeated_trio)}`;
    $("summary-no-evidence").textContent = `Sem evidência: ${integer.format(summary.no_evidence)}`;
    $("summary-recalculations").textContent = config.recalculate_ranking_after_loss
      ? `Rankings recalculados: ${integer.format(summary.ranking_recalculations)}` : "";
    $("summary-reuses").textContent = config.recalculate_ranking_after_loss
      ? `Rankings reutilizados: ${integer.format(summary.ranking_reuses)}` : "";
    $("quality-note").textContent = config.recalculate_ranking_after_loss
      ? "Os agrupamentos usam a qualidade do ranking inicial de cada sinal. Os rankings das tentativas seguintes aparecem nos detalhes do sinal e não excluem entradas."
      : "O saldo usa a progressão financeira configurada. Incompletos e sinais sem ranking não entram em vitórias, derrotas ou saldo. Rankings bloqueados por sobreposição permanecem catalogados, mas não simulam apostas.";
    $("recovery-mode-label").textContent = config.recalculate_ranking_after_loss
      ? "Rankings atualizados após cada falha" : "Mesmo conjunto de números";
    $("recovery-description").textContent = config.recalculate_ranking_after_loss
      ? "O acompanhamento continua recalculando os candidatos para identificar o primeiro acerto posterior. A derrota permanece no resultado do teste."
      : "O acompanhamento continua só para identificar o primeiro acerto posterior. A derrota permanece no resultado do teste.";
    $("overlap-legend").textContent = config.prevent_overlapping_bets
      ? "Apostas não se sobrepõem: sinais formados durante uma entrada ativa aparecem como ignorados e não entram nas estatísticas ou no financeiro."
      : "Quando o limite é maior que três tentativas, sinais diferentes podem compartilhar giros na conferência.";
    renderDistribution("win-distribution", summary.win_attempts, (row) => `${integer.format(row.attempt)}ª tentativa`, "Nenhuma vitória dentro do limite escolhido.");
    $("recovered-losses").textContent = integer.format(summary.recovered_losses);
    $("unresolved-losses").textContent = integer.format(summary.unresolved_losses);
    $("max-recovery").textContent = summary.max_recovery_attempt === null ? "—" : `${integer.format(summary.max_recovery_attempt)}ª`;
    renderDistribution("recovery-distribution", summary.recovery_attempts,
      (row) => `${integer.format(row.attempt)}ª · +${integer.format(row.extra_attempts)} após limite`,
      summary.losses ? "Nenhum acerto posterior observado nas derrotas." : "Não houve derrotas para acompanhar.");
    $("history-records").textContent = `${integer.format(data.source.records)} utilizados · ${integer.format(data.source.requested_records)} solicitados`;
    $("history-period").textContent = `${datetime.format(new Date(data.source.first_timestamp))} — ${datetime.format(new Date(data.source.last_timestamp))}`;
    $("history-read-at").textContent = datetime.format(new Date(data.source.read_at));
    $("history-gaps").textContent = integer.format(data.source.gaps_over_300_seconds);
    $("catalog-records").textContent = integer.format(data.catalog.source.records);
    $("catalog-period").textContent = `${datetime.format(new Date(data.catalog.source.first_timestamp))} — ${datetime.format(new Date(data.catalog.source.last_timestamp))}`;
    $("catalog-build").textContent = data.catalog.build_id;
    renderFinancialReport(data);
    renderQualityReport(data);
    renderPage(1);
    $("backtest-empty").hidden = true;
    $("backtest-error").hidden = true;
    $("backtest-report").hidden = false;
    $("backtest-status").textContent = `Backtest concluído: ${integer.format(summary.wins)} vitórias, ${integer.format(summary.losses)} derrotas, ${integer.format(summary.incomplete)} incompletos e ${integer.format(summary.overlap_skipped)} ignorados por sobreposição. Análise retrospectiva.`;
  }

  async function run(event) {
    if (event) event.preventDefault();
    clearValidation();
    const config = readConfig();
    if (!config) return;
    calculateFinancialPlan({ focusOnError: false });
    if (activeController) activeController.abort();
    const thisRequest = ++requestId;
    const controller = new AbortController();
    activeController = controller;
    currentReport = null;
    let timedOut = false;
    const timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, REQUEST_TIMEOUT_MS);
    $("backtest-report").hidden = true;
    $("backtest-empty").hidden = true;
    $("backtest-error").hidden = true;
    $("backtest-status").textContent = `Conferindo até ${integer.format(config.history_limit)} resultados. O catálogo ficará fixo nesta execução…`;
    setBusy(true);
    try {
      const response = await fetch("/api/triple-context-backtest", {
        method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(config), signal: controller.signal,
      });
      if (!response.ok) {
        const messages = {
          404: "Não há catálogo disponível ou histórico suficiente para formar os trios desta roleta. Tente novamente mais tarde.",
          422: "Não foi possível validar o pedido. Confira o histórico, o top K e as tentativas.",
          429: "Há outra execução em andamento ou muitas solicitações. Aguarde um instante e tente novamente.",
          503: "O serviço está temporariamente indisponível. Tente novamente em instantes.",
          504: "O backtest ultrapassou o tempo de execução. Tente novamente ou reduza o histórico.",
        };
        throw new Error(messages[response.status] || "Não foi possível concluir o backtest. Tente novamente.");
      }
      const data = await response.json();
      if (thisRequest !== requestId) return;
      renderReport(validateResponse(data, config));
    } catch (error) {
      if (thisRequest !== requestId) return;
      currentReport = null;
      $("backtest-report").hidden = true;
      $("backtest-error-message").textContent = timedOut
        ? "A consulta demorou mais que o esperado. Tente novamente ou escolha um histórico menor."
        : error instanceof TypeError ? "Não foi possível conectar à API. Verifique a conexão e tente novamente."
          : error instanceof SyntaxError ? "A API retornou uma resposta inválida. Tente novamente."
            : error.message;
      $("backtest-error").hidden = false;
      $("backtest-status").textContent = "O backtest não foi concluído.";
    } finally {
      window.clearTimeout(timer);
      if (thisRequest === requestId) {
        activeController = null;
        setBusy(false);
      }
    }
  }

  function goToPage() {
    if (!currentReport) return;
    const raw = $("page-number").value.trim();
    const value = Number(raw);
    const lastPage = Math.max(1, Math.ceil(currentReport.signals.length / PAGE_SIZE));
    if (!/^\d+$/.test(raw) || !Number.isSafeInteger(value) || value < 1 || value > lastPage) {
      $("page-error").textContent = `Escolha uma página entre 1 e ${integer.format(lastPage)}.`;
      $("page-error").hidden = false;
      $("page-number").setAttribute("aria-invalid", "true");
      $("page-number").focus();
      return;
    }
    renderPage(value);
  }

  form.addEventListener("submit", run);
  form.addEventListener("input", (event) => {
    if (event.target === $("minimum-profit")) {
      currentFinancialPlan = null;
      clearFinancialError();
      $("financial-projection").hidden = true;
      if (currentReport) {
        renderFinancialReport(currentReport);
        renderQualityReport(currentReport);
        renderPage(currentPage);
      }
      return;
    }
    if (event.target === $("top-k") || event.target === $("attempts")) {
      currentFinancialPlan = null;
      $("financial-projection").hidden = true;
    }
    invalidate();
  });
  $("calculate-financial").addEventListener("click", () => calculateFinancialPlan());
  $("cancel-button").addEventListener("click", () => invalidate("Execução cancelada. Nenhum resultado foi mantido."));
  $("backtest-retry").addEventListener("click", () => form.requestSubmit());
  $("page-first").addEventListener("click", () => renderPage(1));
  $("page-previous").addEventListener("click", () => renderPage(currentPage - 1));
  $("page-next").addEventListener("click", () => renderPage(currentPage + 1));
  $("page-last").addEventListener("click", () => { if (currentReport) renderPage(Math.ceil(currentReport.signals.length / PAGE_SIZE)); });
  $("page-go").addEventListener("click", goToPage);
  $("page-number").addEventListener("input", clearPageError);
  $("page-number").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); goToPage(); } });
  $("quality-dimension").addEventListener("change", () => { if (currentReport) renderQualityBuckets(currentReport); });
  calculateFinancialPlan({ focusOnError: false });
})();
