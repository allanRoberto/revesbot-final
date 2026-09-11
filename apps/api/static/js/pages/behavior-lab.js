const app = document.querySelector("#behavior-lab-app");

if (!app) throw new Error("Behavior Lab não encontrado");

const rouletteId = app.dataset.rouletteId;
const maxAttempts = Number(app.dataset.maxAttempts || 10);
const endpoints = {
  live: app.dataset.liveUrl,
  signals: app.dataset.signalsUrl,
  health: app.dataset.healthUrl,
  backtest: app.dataset.backtestUrl,
};

const elements = {
  socketStatus: document.querySelector("#socket-status"),
  socketStatusText: document.querySelector("#socket-status-text"),
  workerStatus: document.querySelector("#worker-status"),
  workerStatusText: document.querySelector("#worker-status-text"),
  updatedAt: document.querySelector("#live-updated-at"),
  lastResult: document.querySelector("#last-result"),
  lastResultTime: document.querySelector("#last-result-time"),
  decision: document.querySelector("#live-decision"),
  decisionTitle: document.querySelector("#decision-title"),
  decisionReason: document.querySelector("#decision-reason"),
  suggestedNumbers: document.querySelector("#suggested-numbers"),
  activeSignals: document.querySelector("#active-signals-list"),
  activeSignalsCount: document.querySelector("#active-signals-count"),
  recentResults: document.querySelector("#recent-results"),
  recentResultsCount: document.querySelector("#recent-results-count"),
  signalHistoryBody: document.querySelector("#signal-history-body"),
  signalHistoryCount: document.querySelector("#signal-history-count"),
  backtestForm: document.querySelector("#backtest-form"),
  backtestSubmit: document.querySelector("#backtest-submit"),
  backtestStatus: document.querySelector("#backtest-status"),
  backtestResults: document.querySelector("#backtest-results"),
};

let socket;
let socketConnected = false;
let socketGeneration = 0;
let reconnectTimer;
let reconnectDelay = 1000;
let liveRefreshTimer;
let loadingLive = false;
let liveRefreshPending = false;
let lastLiveRenderKey = "";
let expectedLiveEventKeys = [];
let liveCatchupDeadline = 0;

const ruleLabels = {
  exact_pair_continuation: "Continuação de par",
  repeated_same_double: "Repetição de número duplo",
  structural_21_terminal1_double: "Formação 21 · terminal 1 · duplo",
};

const reasonLabels = {
  signal_active: "Há sinais ativos para o próximo giro.",
  no_active_signal: "Nenhum gatilho válido está ativo agora.",
  worker_state_unavailable: "Aguardando o primeiro estado do worker.",
  worker_state_stale: "Estado vencido: aguardando um heartbeat novo do worker.",
  worker_not_ready: "Worker ainda não está pronto para publicar uma entrada.",
  worker_state_lagging: "Aguardando o snapshot alcançar o último giro confirmado.",
};

function firstDefined(...values) {
  return values.find((value) => value !== undefined && value !== null);
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function formatInteger(value) {
  if (value === undefined || value === null || value === "") return "—";
  return asNumber(value).toLocaleString("pt-BR", { maximumFractionDigits: 0 });
}

function formatPercent(value) {
  if (value === undefined || value === null || value === "") return "—";
  const numeric = asNumber(value);
  const percentage = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${percentage.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
}

function formatDate(value) {
  if (!value) return "Horário indisponível";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Horário indisponível";
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function statusMessage(message, modifier = "") {
  const element = document.createElement("div");
  element.className = `state-message${modifier ? ` state-message--${modifier}` : ""}`;
  element.textContent = message;
  return element;
}

function setServiceStatus(container, text, state, label) {
  if (container.dataset.state === state && text.textContent === label) return;
  container.dataset.state = state;
  text.textContent = label;
}

function blockLiveDecision(reason) {
  lastLiveRenderKey = "";
  elements.decision.dataset.decision = "waiting";
  elements.decisionTitle.textContent = "AGUARDANDO";
  elements.decisionReason.textContent = reason;
  elements.suggestedNumbers.replaceChildren(
    statusMessage("Nenhuma entrada é liberada sem confirmação ao vivo.", "loading"),
  );
  elements.activeSignals.replaceChildren(
    statusMessage("Aguardando reconexão e sincronização.", "loading"),
  );
  elements.activeSignalsCount.textContent = "—";
}

function eventIdentityKeys(item) {
  if (!item || typeof item !== "object") return [];
  const fullResult = item.full_result && typeof item.full_result === "object"
    ? item.full_result
    : {};
  const externalId = firstDefined(fullResult.external_game_id, item.external_game_id);
  const eventId = firstDefined(fullResult._id, item._id, item.event_id);
  return [
    externalId === undefined || externalId === null ? null : `external:${externalId}`,
    eventId === undefined || eventId === null ? null : `id:${eventId}`,
  ].filter(Boolean);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { Accept: "application/json", ...(options.headers || {}) },
    ...options,
  });
  let payload;
  try { payload = await response.json(); }
  catch (_) { payload = null; }
  if (!response.ok) {
    const detail = payload?.detail || "Serviço indisponível";
    throw new Error(detail);
  }
  return payload || {};
}

function normalizeLive(payload) {
  const snapshot = payload.snapshot || payload.state || payload;
  const decisionObject = typeof snapshot.decision === "object" ? snapshot.decision : {};
  const suggestion = asArray(firstDefined(
    decisionObject.numbers,
    decisionObject.suggested_numbers,
    snapshot.suggestion,
    snapshot.suggested_numbers,
    payload.suggestion,
  )).map(Number).filter(Number.isFinite);
  const rawDecision = String(firstDefined(
    decisionObject.status,
    decisionObject.action,
    snapshot.decision,
    suggestion.length ? "BET" : "NO_BET",
  )).toUpperCase();
  const enter = suggestion.length > 0 && ["BET", "ENTER", "ENTRAR", "ACTIVE"].includes(rawDecision);

  return {
    snapshot,
    lastResult: snapshot.last_result || payload.last_result || null,
    suggestion,
    enter,
    reason: firstDefined(decisionObject.reason, snapshot.reason, payload.reason),
    activeSignals: asArray(firstDefined(snapshot.active_signals, payload.active_signals)),
    recentResults: asArray(firstDefined(payload.recent_results, snapshot.recent_results)),
    metrics: payload.metrics || snapshot.metrics || {},
    generatedAt: firstDefined(payload.generated_at, snapshot.generated_at, payload.updated_at, snapshot.updated_at),
    worker: snapshot.worker || payload.worker || null,
  };
}

function liveRenderKey(live) {
  return JSON.stringify({
    lastResult: live.lastResult,
    suggestion: live.suggestion,
    reason: live.reason,
    activeSignals: live.activeSignals.map((signal) => ({
      id: signal.signal_id,
      status: signal.status,
      attempts: signal.attempts,
      numbers: signal.suggested_numbers,
    })),
    metrics: live.metrics,
    workerStatus: live.worker?.status,
    workerFresh: live.worker?.fresh,
  });
}

function createNumberChip(value, className = "number-chip") {
  const chip = document.createElement("span");
  chip.className = className;
  chip.textContent = String(value);
  return chip;
}

function signalAttempt(signal) {
  const status = String(signal.status || "active").toLowerCase();
  const consumed = asNumber(firstDefined(signal.attempts, signal.attempt, signal.attempt_count), 0);
  const current = firstDefined(signal.current_attempt, signal.next_attempt);
  if (current !== undefined && current !== null) return Math.max(1, Math.min(maxAttempts, asNumber(current, 1)));
  return Math.max(1, Math.min(maxAttempts, status === "active" ? consumed + 1 : consumed));
}

function signalTargets(signal) {
  return asArray(firstDefined(signal.suggested_numbers, signal.numbers, signal.targets))
    .map(Number)
    .filter(Number.isFinite);
}

function signalRuleLabel(signal) {
  const raw = String(firstDefined(signal.rule_label, signal.rule, ""));
  return signal.rule_label || ruleLabels[raw] || raw.replaceAll("_", " ") || "Regra sem nome";
}

function exactSignalTargets(signal) {
  return asArray(firstDefined(signal.targets, signal.suggested_numbers, signal.numbers))
    .map(Number)
    .filter(Number.isFinite);
}

function renderActiveSignals(signals) {
  elements.activeSignals.replaceChildren();
  elements.activeSignalsCount.textContent = String(signals.length);
  if (!signals.length) {
    elements.activeSignals.append(statusMessage("Nenhum sinal ativo neste giro.", "empty"));
    return;
  }

  signals.forEach((signal) => {
    const attempt = signalAttempt(signal);
    const card = document.createElement("article");
    card.className = "signal-card";

    const top = document.createElement("div");
    top.className = "signal-card__top";
    const name = document.createElement("span");
    name.className = "signal-card__name";
    name.textContent = signalRuleLabel(signal);
    const attemptLabel = document.createElement("span");
    attemptLabel.className = "signal-card__attempt";
    attemptLabel.textContent = `Tentativa ${attempt}/${maxAttempts}`;
    top.append(name, attemptLabel);

    const targets = document.createElement("div");
    targets.className = "signal-card__targets";
    signalTargets(signal).forEach((value) => targets.append(createNumberChip(value)));
    if (!targets.children.length) targets.append(statusMessage("Sem números", "empty"));

    const track = document.createElement("div");
    track.className = "attempt-track";
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-valuemin", "1");
    track.setAttribute("aria-valuemax", String(maxAttempts));
    track.setAttribute("aria-valuenow", String(attempt));
    track.setAttribute("aria-label", `Tentativa ${attempt} de ${maxAttempts}`);
    const fill = document.createElement("span");
    fill.style.width = `${(attempt / maxAttempts) * 100}%`;
    track.append(fill);

    card.append(top, targets, track);
    elements.activeSignals.append(card);
  });
}

function renderDecision(live) {
  elements.lastResult.classList.toggle("roulette-number--empty", live.lastResult?.value === undefined);
  elements.lastResult.textContent = live.lastResult?.value ?? "—";
  elements.lastResultTime.textContent = formatDate(firstDefined(live.lastResult?.timestamp, live.lastResult?.captured_at));

  const workerReady = !live.worker || (
    live.worker.fresh !== false && String(live.worker.status).toLowerCase() === "healthy"
  );
  elements.decision.dataset.decision = workerReady
    ? (live.enter ? "enter" : "no-entry")
    : "waiting";
  elements.decisionTitle.textContent = workerReady
    ? (live.enter ? "ENTRAR" : "SEM ENTRADA")
    : "AGUARDANDO";
  const defaultReason = live.enter
    ? "Há sinais ativos para o próximo giro."
    : "Nenhum gatilho válido está ativo agora.";
  elements.decisionReason.textContent = live.reason
    ? reasonLabels[live.reason] || String(live.reason).replaceAll("_", " ")
    : defaultReason;
  elements.suggestedNumbers.replaceChildren();
  live.suggestion.forEach((value) => elements.suggestedNumbers.append(createNumberChip(value)));
  if (!live.suggestion.length) elements.suggestedNumbers.append(statusMessage("Aguardando uma formação válida.", "empty"));

  renderActiveSignals(live.activeSignals);
  elements.updatedAt.textContent = live.generatedAt
    ? `Estado atualizado em ${formatDate(live.generatedAt)}`
    : "Aguardando atualização do worker";
}

function metricValue(metrics, ...keys) {
  return firstDefined(...keys.map((key) => metrics[key]));
}

function renderMetrics(metrics) {
  const signalMetrics = metrics.signals || metrics;
  const decisionMetrics = metrics.decisions || metrics;
  const paymentTypes = signalMetrics.payment_types || metrics.payment_types || {};
  const won = asNumber(metricValue(signalMetrics, "won", "wins"));
  const lost = asNumber(metricValue(signalMetrics, "lost", "losses"));
  const resolved = firstDefined(metricValue(signalMetrics, "resolved", "resolved_signals"), won + lost);
  document.querySelector("#metric-resolved").textContent = formatInteger(resolved);
  document.querySelector("#metric-hit-rate").textContent = formatPercent(firstDefined(
    metricValue(signalMetrics, "win_rate", "hit_rate", "assertiveness", "accuracy"),
    asNumber(resolved) ? won / asNumber(resolved) : null,
  ));
  document.querySelector("#metric-decision-hit-rate").textContent = formatPercent(
    metricValue(decisionMetrics, "hit_rate"),
  );
  document.querySelector("#metric-exact").textContent = formatInteger(firstDefined(paymentTypes.exact, metricValue(signalMetrics, "exact", "exact_hits", "paid_exact")));
  document.querySelector("#metric-neighbor").textContent = formatInteger(firstDefined(paymentTypes.neighbor, metricValue(signalMetrics, "neighbor", "neighbor_hits", "paid_neighbor")));
  document.querySelector("#metric-mirror").textContent = formatInteger(firstDefined(paymentTypes.mirror, metricValue(signalMetrics, "mirror", "mirror_hits", "paid_mirror")));
  document.querySelector("#metric-abstention").textContent = formatPercent(metricValue(decisionMetrics, "abstention_rate", "abstention"));
}

function normalizeResultValue(item) {
  if (typeof item === "number") return item;
  return firstDefined(item?.value, item?.result, item?.number);
}

function renderRecentResults(results) {
  elements.recentResults.replaceChildren();
  elements.recentResultsCount.textContent = `${results.length.toLocaleString("pt-BR")} giros`;
  if (!results.length) {
    elements.recentResults.append(statusMessage("O worker ainda não publicou resultados recentes.", "empty"));
    return;
  }
  results.slice(0, 100).forEach((item) => {
    const value = normalizeResultValue(item);
    if (value !== undefined && value !== null) elements.recentResults.append(createNumberChip(value, "result-chip"));
  });
}

const statusLabels = {
  active: "Ativo",
  won: "Ganho",
  lost: "Perdido",
  censored: "Inconclusivo",
};

function renderSignalHistory(payload) {
  const signals = asArray(payload.signals);
  const total = firstDefined(payload.count, payload.total, signals.length);
  elements.signalHistoryCount.textContent = `${formatInteger(total)} sinais`;
  elements.signalHistoryBody.replaceChildren();
  if (!signals.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.append(statusMessage("Nenhum sinal registrado até agora.", "empty"));
    row.append(cell);
    elements.signalHistoryBody.append(row);
    return;
  }

  signals.forEach((signal) => {
    const row = document.createElement("tr");
    const ruleCell = document.createElement("td");
    ruleCell.textContent = signalRuleLabel(signal);

    const targetCell = document.createElement("td");
    const targets = document.createElement("div");
    targets.className = "table-targets";
    exactSignalTargets(signal).slice(0, 12).forEach((value, index) => {
      const target = document.createElement("span");
      target.className = "table-target";
      target.textContent = `${index ? "· " : ""}${value}`;
      targets.append(target);
    });
    if (!targets.children.length) targets.textContent = "—";
    targetCell.append(targets);

    const attemptCell = document.createElement("td");
    attemptCell.textContent = `${signalAttempt(signal)}/${maxAttempts}`;

    const statusCell = document.createElement("td");
    const rawStatus = String(signal.status || "active").toLowerCase();
    const badge = document.createElement("span");
    badge.className = `signal-status signal-status--${statusLabels[rawStatus] ? rawStatus : "censored"}`;
    badge.textContent = statusLabels[rawStatus] || rawStatus;
    statusCell.append(badge);

    row.append(ruleCell, targetCell, attemptCell, statusCell);
    elements.signalHistoryBody.append(row);
  });
}

async function loadLive() {
  if (loadingLive) {
    liveRefreshPending = true;
    return;
  }
  loadingLive = true;
  const requestSocketGeneration = (
    socketConnected && socket?.readyState === WebSocket.OPEN
  ) ? socketGeneration : null;
  try {
    const payload = await requestJson(endpoints.live);
    const live = normalizeLive(payload);
    const observedKeys = [live.lastResult, ...live.recentResults]
      .flatMap(eventIdentityKeys);
    const caughtUp = !expectedLiveEventKeys.length || observedKeys
      .some((key) => expectedLiveEventKeys.includes(key));
    if (!caughtUp) return live;
    expectedLiveEventKeys = [];
    if (
      requestSocketGeneration === null
      || requestSocketGeneration !== socketGeneration
      || !socketConnected
      || socket?.readyState !== WebSocket.OPEN
    ) {
      blockLiveDecision("Conexão ao vivo interrompida; aguardando sincronização.");
      return live;
    }
    const renderKey = liveRenderKey(live);
    if (renderKey !== lastLiveRenderKey) {
      lastLiveRenderKey = renderKey;
      renderDecision(live);
      renderMetrics(live.metrics);
      renderRecentResults(live.recentResults);
    }
    return live;
  } catch (error) {
    elements.decision.dataset.decision = "error";
    elements.decisionTitle.textContent = "INDISPONÍVEL";
    elements.decisionReason.textContent = error.message;
    elements.suggestedNumbers.replaceChildren(statusMessage("Não foi possível consultar a decisão atual.", "error"));
    elements.activeSignals.replaceChildren(statusMessage("Sinais ativos indisponíveis.", "error"));
    elements.activeSignalsCount.textContent = "—";
    elements.recentResults.replaceChildren(statusMessage("Resultados recentes indisponíveis.", "error"));
    elements.recentResultsCount.textContent = "Falha na consulta";
    elements.updatedAt.textContent = "Falha na atualização";
  } finally {
    loadingLive = false;
    if (liveRefreshPending) {
      liveRefreshPending = false;
      window.setTimeout(loadLive, 200);
    }
  }
}

async function loadSignals() {
  try {
    renderSignalHistory(await requestJson(`${endpoints.signals}?limit=50`));
  } catch (error) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.append(statusMessage(error.message, "error"));
    row.append(cell);
    elements.signalHistoryBody.replaceChildren(row);
    elements.signalHistoryCount.textContent = "Falha na consulta";
  }
}

function inferWorkerStatus(payload) {
  const worker = payload.worker || {};
  const raw = String(firstDefined(worker.status, payload.worker_status, payload.status, "unknown")).toLowerCase();
  const fresh = firstDefined(worker.fresh, payload.fresh);
  if (fresh === false || raw === "stale") {
    return { state: "error", label: "Worker sem heartbeat" };
  }
  if (["ok", "healthy", "online", "running", "ready"].includes(raw)) {
    return { state: "online", label: "Worker online" };
  }
  if (raw === "starting") return { state: "loading", label: "Worker iniciando" };
  if (raw === "degraded") return { state: "error", label: "Worker degradado" };
  if (["stopped", "unavailable", "offline"].includes(raw)) {
    return { state: "offline", label: "Worker offline" };
  }
  return { state: "loading", label: "Worker sem estado" };
}

async function loadHealth() {
  try {
    const status = inferWorkerStatus(await requestJson(endpoints.health));
    setServiceStatus(elements.workerStatus, elements.workerStatusText, status.state, status.label);
  } catch (_) {
    setServiceStatus(elements.workerStatus, elements.workerStatusText, "error", "Worker indisponível");
  }
}

function scheduleLiveRefresh(event) {
  let eventPayload = null;
  if (event?.data) {
    try { eventPayload = JSON.parse(event.data); }
    catch (_) { eventPayload = null; }
  }
  const receivedKeys = eventIdentityKeys(eventPayload);
  if (receivedKeys.length) {
    expectedLiveEventKeys = receivedKeys;
    liveCatchupDeadline = Date.now() + 5000;
    elements.decision.dataset.decision = "waiting";
    elements.decisionTitle.textContent = "ATUALIZANDO";
    elements.decisionReason.textContent = "Validando o novo giro antes de liberar a próxima leitura.";
    elements.suggestedNumbers.replaceChildren(
      statusMessage("Aguardando o estado confirmado do worker.", "loading"),
    );
  }
  window.clearTimeout(liveRefreshTimer);
  const refresh = async () => {
    await Promise.allSettled([loadLive(), loadSignals(), loadHealth()]);
    if (expectedLiveEventKeys.length && Date.now() < liveCatchupDeadline) {
      liveRefreshTimer = window.setTimeout(refresh, 400);
    } else if (expectedLiveEventKeys.length) {
      elements.decisionTitle.textContent = "AGUARDANDO";
      elements.decisionReason.textContent = "O novo giro ainda não foi confirmado pelo worker.";
    }
  };
  liveRefreshTimer = window.setTimeout(refresh, receivedKeys.length ? 150 : 0);
}

function connectSocket() {
  window.clearTimeout(reconnectTimer);
  socketGeneration += 1;
  socketConnected = false;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${window.location.host}/ws?slug=${encodeURIComponent(rouletteId)}`;
  setServiceStatus(elements.socketStatus, elements.socketStatusText, "loading", "WebSocket conectando");
  socket = new WebSocket(url);

  socket.addEventListener("open", () => {
    socketConnected = true;
    reconnectDelay = 1000;
    expectedLiveEventKeys = [];
    setServiceStatus(elements.socketStatus, elements.socketStatusText, "online", "WebSocket conectado");
    scheduleLiveRefresh();
  });
  socket.addEventListener("message", scheduleLiveRefresh);
  socket.addEventListener("error", () => socket.close());
  socket.addEventListener("close", () => {
    socketConnected = false;
    setServiceStatus(elements.socketStatus, elements.socketStatusText, "offline", "WebSocket reconectando");
    blockLiveDecision("Conexão ao vivo interrompida; aguardando sincronização.");
    reconnectTimer = window.setTimeout(connectSocket, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 15_000);
  });
}

function backtestMetrics(payload) {
  return payload.metrics || payload.summary || payload;
}

function showBacktest(payload) {
  const metrics = backtestMetrics(payload);
  const signalMetrics = metrics.signals || metrics;
  const decisionMetrics = metrics.decisions || metrics;
  const financialMetrics = metrics.flat_stake || metrics;
  const spinMetrics = metrics.spins || metrics;
  const won = asNumber(firstDefined(signalMetrics.won, signalMetrics.wins));
  const lost = asNumber(firstDefined(signalMetrics.lost, signalMetrics.losses));
  const resolved = firstDefined(signalMetrics.resolved, signalMetrics.resolved_signals, won + lost);
  document.querySelector("#backtest-used").textContent = formatInteger(firstDefined(payload.results_used, spinMetrics.accepted, metrics.results_used));
  document.querySelector("#backtest-resolved").textContent = formatInteger(resolved);
  document.querySelector("#backtest-hit-rate").textContent = formatPercent(firstDefined(
    signalMetrics.win_rate,
    signalMetrics.hit_rate,
    signalMetrics.assertiveness,
    asNumber(resolved) ? won / asNumber(resolved) : null,
  ));
  document.querySelector("#backtest-baseline").textContent = formatPercent(firstDefined(
    signalMetrics.random_expected_win_rate_same_coverage_horizon,
    signalMetrics.random_baseline_same_coverage_horizon,
  ));
  document.querySelector("#backtest-decision-hit-rate").textContent = formatPercent(
    decisionMetrics.hit_rate,
  );
  document.querySelector("#backtest-roi").textContent = formatPercent(firstDefined(financialMetrics.roi, financialMetrics.roi_on_wagered, financialMetrics.theoretical_roi));
  document.querySelector("#backtest-loss-streak").textContent = formatInteger(firstDefined(financialMetrics.max_loss_streak, metrics.max_loss_streak, metrics.longest_loss_streak));
  elements.backtestResults.hidden = false;
}

elements.backtestForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.querySelector("#backtest-limit");
  const limit = Number(input.value);
  elements.backtestSubmit.disabled = true;
  elements.backtestStatus.className = "backtest-status state-message state-message--loading";
  elements.backtestStatus.textContent = "Executando o replay cronológico…";
  elements.backtestResults.hidden = true;
  try {
    const payload = await requestJson(endpoints.backtest, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit }),
    });
    showBacktest(payload);
    elements.backtestStatus.className = "backtest-status state-message";
    elements.backtestStatus.textContent = "Backtest concluído com a mesma configuração do worker.";
  } catch (error) {
    elements.backtestStatus.className = "backtest-status state-message state-message--error";
    elements.backtestStatus.textContent = error.message;
  } finally {
    elements.backtestSubmit.disabled = false;
  }
});

connectSocket();
await Promise.allSettled([loadLive(), loadSignals(), loadHealth()]);

window.setInterval(() => {
  if (document.visibilityState === "visible") Promise.allSettled([loadLive(), loadHealth()]);
}, 10_000);
