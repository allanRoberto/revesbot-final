import { analyzeOccurrences, CONFIG, neighborsOf, rankFollowing, signalActivation, signalMarkCounts, unmarkedBetNumbers } from "../core/contextual-similarity-model.js?v=20261108-signal-thermometer";

const $ = (selector) => document.querySelector(selector);
const status = $("#analysis-status");
const button = $("#run-analysis");
const occurrenceBody = $("#occurrence-rows");
const redNumbers = new Set([1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]);
const selectedOccurrenceNumbers = new Set();
const liveMarkedNumbers = new Set();
let activeController = null;
let currentOccurrenceView = null;
let liveSocket = null;
let liveReconnectTimer = null;
let liveReconnectDelay = 1000;
let liveConnectionGeneration = 0;
const SIGNAL_HISTORY_KEY = "revesbot-contextual-signal-history-v1";
const SIGNAL_ACTIVATION_WINDOW = 5;
const SIGNAL_ATTEMPT_LIMIT = 10;
const SIGNAL_HISTORY_LIMIT = 500;
let analysisSpinCount = 0;
let currentAnalysisId = null;
let signalStates = new Map();
let signalHistory = loadSignalHistory();

function loadSignalHistory() {
  try {
    const value = JSON.parse(localStorage.getItem(SIGNAL_HISTORY_KEY) || "[]");
    return Array.isArray(value) ? value.filter((item) => item && typeof item === "object").slice(0, SIGNAL_HISTORY_LIMIT) : [];
  } catch (_) {
    return [];
  }
}

function saveSignalHistory() {
  signalHistory = signalHistory.slice(0, SIGNAL_HISTORY_LIMIT);
  try { localStorage.setItem(SIGNAL_HISTORY_KEY, JSON.stringify(signalHistory)); } catch (_) { /* armazenamento local opcional */ }
}

function signalStateFor(row) {
  if (!signalStates.has(row.index)) signalStates.set(row.index, { status: "aguardando", counts: [0, 0, 0] });
  return signalStates.get(row.index);
}

function updateSignalHistory(recordId, update) {
  const index = signalHistory.findIndex((item) => item.id === recordId);
  if (index < 0) return;
  signalHistory[index] = { ...signalHistory[index], ...update };
  saveSignalHistory();
}

function appendSignalRecord(record) {
  signalHistory.unshift(record);
  saveSignalHistory();
}

function restoreActiveSignals() {
  return signalHistory.filter((entry) => entry.status === "em_andamento");
}

function restoreActiveSignalStates(analysis) {
  for (const record of restoreActiveSignals()) {
    const row = analysis.rows.find((item) => item.index === record.occurrenceIndex && item.id === record.occurrenceId);
    if (!row) continue;
    const state = signalStateFor(row);
    state.status = "em_andamento";
  }
}

function numberPill(value, matchLabel = "") {
  const pill = document.createElement("span");
  pill.className = `cs-number ${value === 0 ? "cs-number--green" : redNumbers.has(value) ? "cs-number--red" : "cs-number--black"}`;
  pill.textContent = String(value);
  if (matchLabel) {
    pill.classList.add("cs-number--matched");
    pill.title = `Coincide com ${matchLabel}`;
    pill.setAttribute("aria-label", `${value}, coincide com ${matchLabel}`);
  }
  return pill;
}

function numberList(values, matchingNumbers = null, matchLabel = "", selectable = false) {
  const list = document.createElement("span");
  list.className = "cs-number-list";
  if (Array.isArray(values)) values.forEach((value) => {
    const matched = matchingNumbers?.has(value) ? matchLabel : "";
    const pill = numberPill(value, matched);
    if (selectable) {
      pill.classList.add("cs-number--selectable");
      pill.dataset.occurrenceNumber = String(value);
      if (matched) pill.dataset.matchLabel = matched;
      pill.setAttribute("role", "button");
      pill.setAttribute("tabindex", "0");
      if (liveMarkedNumbers.has(value)) pill.classList.add("cs-number--live-hit");
      updateSelectablePill(pill);
    }
    list.append(pill);
  });
  else list.textContent = "—";
  return list;
}

function updateSelectablePill(pill) {
  const number = Number(pill.dataset.occurrenceNumber);
  const selected = selectedOccurrenceNumbers.has(number);
  pill.classList.toggle("cs-number--selected", selected);
  pill.classList.toggle("cs-number--live-hit", liveMarkedNumbers.has(number));
  pill.setAttribute("aria-pressed", String(selected));
  const matchDescription = pill.dataset.matchLabel ? `; coincide com ${pill.dataset.matchLabel}` : "";
  const liveDescription = liveMarkedNumbers.has(number) ? "; resultado observado ao vivo" : "";
  pill.setAttribute("aria-label", `Número ${number}${matchDescription}${liveDescription}; ${selected ? "selecionado, clique para desmarcar" : "não selecionado, clique para selecionar"}`);
}

function toggleOccurrenceNumber(number) {
  if (selectedOccurrenceNumbers.has(number)) selectedOccurrenceNumbers.delete(number);
  else selectedOccurrenceNumbers.add(number);
  if (currentOccurrenceView) renderOccurrences(...currentOccurrenceView);
}

function handleOccurrenceNumberInput(event) {
  const pill = event.target instanceof Element ? event.target.closest(".cs-number--selectable") : null;
  if (!pill) return;
  if (event.type === "keydown") {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
  }
  const number = Number(pill.dataset.occurrenceNumber);
  if (Number.isInteger(number) && number >= 0 && number <= 36) toggleOccurrenceNumber(number);
}

function setNumbers(target, values) {
  target.replaceChildren(numberList(values));
}

function formatPercent(value) {
  return `${Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

function cell(row, value, className = "") {
  const td = document.createElement("td");
  td.className = className;
  if (value instanceof Node) td.append(value);
  else td.textContent = value == null ? "—" : String(value);
  row.append(td);
  return td;
}

function matchCounts(current, historical) {
  if (!Array.isArray(current) || !Array.isArray(historical)) return { exact: 0, neighbor: 0 };
  let best = { exact: 0, neighbor: 0 };
  const used = new Set();
  function visit(index, exact, neighbor) {
    if (index === historical.length) {
      if (exact > best.exact || (exact === best.exact && neighbor > best.neighbor)) best = { exact, neighbor };
      return;
    }
    visit(index + 1, exact, neighbor);
    for (let targetIndex = 0; targetIndex < current.length; targetIndex += 1) {
      if (used.has(targetIndex)) continue;
      const target = current[targetIndex];
      const type = historical[index] === target ? "exact"
        : neighborsOf(target).includes(historical[index]) ? "neighbor" : null;
      if (!type) continue;
      used.add(targetIndex);
      visit(index + 1, exact + Number(type === "exact"), neighbor + Number(type === "neighbor"));
      used.delete(targetIndex);
    }
  }
  visit(0, 0, 0);
  return best;
}

function compareDistribution(left, right) {
  const leftSorted = [...left].sort((a, b) => b - a);
  const rightSorted = [...right].sort((a, b) => b - a);
  const leftGroups = left.filter((value) => value > 0).length;
  const rightGroups = right.filter((value) => value > 0).length;
  if (leftGroups !== rightGroups) return rightGroups - leftGroups;
  for (let index = 0; index < Math.max(leftSorted.length, rightSorted.length); index += 1) {
    const difference = (rightSorted[index] || 0) - (leftSorted[index] || 0);
    if (difference) return difference;
  }
  return 0;
}

function duplicateCount(values) {
  return Array.isArray(values) ? values.length - new Set(values).size : 0;
}

function liveHitDistribution(row) {
  return [
    row.precedingValid ? row.preceding : null,
    row.contextValid ? row.context : null,
    row.followingValid ? row.following : null,
  ].map((values) => Array.isArray(values)
    ? values.filter((number) => liveMarkedNumbers.has(number)).length : 0);
}

function occurrenceOrder(left, right, searchSequence) {
  const leftSequence = matchCounts(searchSequence, left.context);
  const rightSequence = matchCounts(searchSequence, right.context);
  const leftLiveHits = liveHitDistribution(left);
  const rightLiveHits = liveHitDistribution(right);
  // Acertos ao vivo em Posterior entram no mesmo nível distributivo das exatas.
  const leftExact = [left.score?.exact || 0, leftSequence.exact, leftLiveHits[2]];
  const rightExact = [right.score?.exact || 0, rightSequence.exact, rightLiveHits[2]];
  let difference = compareDistribution(leftExact, rightExact);
  if (difference) return difference;

  difference = duplicateCount(left.contextValid ? left.context : null) - duplicateCount(right.contextValid ? right.context : null);
  if (difference) return difference;

  difference = compareDistribution(leftLiveHits.slice(0, 2), rightLiveHits.slice(0, 2));
  if (difference) return difference;

  const selectedCounts = (row) => [row.preceding, row.context, row.following]
    .map((values) => Array.isArray(values) ? values.filter((number) => selectedOccurrenceNumbers.has(number)).length : 0);
  difference = compareDistribution(selectedCounts(left), selectedCounts(right));
  if (difference) return difference;

  const leftNeighbors = [left.score?.neighbor || 0, leftSequence.neighbor];
  const rightNeighbors = [right.score?.neighbor || 0, rightSequence.neighbor];
  difference = compareDistribution(leftNeighbors, rightNeighbors);
  if (difference) return difference;

  if (!left.score) return right.score ? 1 : left.index - right.index;
  if (!right.score) return -1;
  return right.score.score - left.score.score || right.score.exact - left.score.exact || left.index - right.index;
}

function renderOccurrences(analysis, currentContext, searchSequence) {
  const body = $("#occurrence-rows");
  currentOccurrenceView = [analysis, currentContext, searchSequence];
  const selectedIds = new Set(analysis.selected.map((row) => row.id));
  const currentContextNumbers = new Set(currentContext);
  const searchSequenceNumbers = new Set(searchSequence);
  const sorted = [...analysis.rows].sort((left, right) => occurrenceOrder(left, right, searchSequence));
  body.replaceChildren();
  if (!sorted.length) {
    const row = body.insertRow();
    cell(row, "A API não retornou ocorrências.", "cs-empty").colSpan = 9;
    return;
  }
  sorted.forEach((occurrence, index) => {
    const selected = selectedIds.has(occurrence.id);
    const row = body.insertRow();
    row.className = selected ? "cs-selected-row" : "";
    cell(row, index + 1);
    cell(row, numberList(occurrence.precedingValid ? occurrence.preceding : null,
      currentContextNumbers, "o contexto anterior atual", true));
    cell(row, numberList(occurrence.contextValid ? occurrence.context : null,
      searchSequenceNumbers, "a sequência da busca", true));
    cell(row, numberList(occurrence.followingValid ? occurrence.following : null,
      null, "", true));
    const frozenSignal = signalHistory.find((entry) => entry.analysisId === currentAnalysisId &&
      entry.occurrenceIndex === occurrence.index && entry.occurrenceId === occurrence.id &&
      ["em_andamento", "acerto", "erro"].includes(entry.status)) || signalHistory.find((entry) =>
      entry.status === "em_andamento" && entry.occurrenceIndex === occurrence.index && entry.occurrenceId === occurrence.id);
    const betNumbers = frozenSignal?.betNumbers || unmarkedBetNumbers(occurrence, liveMarkedNumbers, currentContext, searchSequence);
    cell(row, betNumbers.length ? numberList(betNumbers, null, "", true) : "—", "cs-bet-cell");
    cell(row, occurrence.score?.exact ?? "—");
    cell(row, occurrence.score?.neighbor ?? "—");
    cell(row, occurrence.score ? formatPercent(occurrence.score.similarity) : "—");
    const state = selected ? "Selecionada" : occurrence.approved ? "Aprovada" :
      !occurrence.precedingValid ? `Anterior ${occurrence.preceding_complete ? "inválido" : occurrence.preceding_lookup_status}` :
        !occurrence.contextValid ? "Contexto inválido" : "Abaixo do corte";
    const signal = signalStateFor(occurrence);
    signal.counts = signalMarkCounts(occurrence, liveMarkedNumbers, currentContext, searchSequence);
    cell(row, signalIndicator(signal, state), selected ? "cs-status-cell cs-status-cell--selected" : "cs-status-cell");
  });
}

function signalStatusLabel(status) {
  return ({
    em_andamento: "Em andamento",
    acerto: "Acertou",
    erro: "Não acertou em 10 tentativas",
    cancelado: "Cancelado sem ativação",
    descartado: "Descartado por desempate",
  })[status] || status || "—";
}

function signalIndicator(signal, fallback) {
  const counts = signal.counts || [0, 0, 0];
  const total = counts.reduce((sum, count) => sum + count, 0);
  const displayedTotal = signal.status === "em_andamento" ? Math.max(6, total) : total;
  const container = document.createElement("span");
  container.className = "cs-signal-indicator";
  const meter = document.createElement("span");
  meter.className = "cs-signal-meter";
  meter.setAttribute("role", "progressbar");
  meter.setAttribute("aria-valuemin", "0");
  meter.setAttribute("aria-valuemax", "6");
  meter.setAttribute("aria-valuenow", String(Math.min(displayedTotal, 6)));
  meter.setAttribute("aria-label", `Marcas do sinal: ${displayedTotal} de 6; anterior ${counts[0]}, sequência ${counts[1]}, posterior ${counts[2]}`);
  const fill = document.createElement("span");
  fill.className = "cs-signal-meter__fill";
  fill.style.width = `${Math.min(100, displayedTotal / 6 * 100)}%`;
  meter.append(fill);
  const label = document.createElement("small");
  label.textContent = signal.status === "aguardando"
    ? `${total}/6 · A${counts[0]} S${counts[1]} P${counts[2]} · ${fallback}`
    : signal.status === "em_andamento" ? "Aposta ativa" : signal.label || fallback;
  container.append(meter, label);
  return container;
}

function renderSignalThermometer() {
  const body = $("#signal-history-rows");
  if (!body) return;
  const progress = $("#signal-progress");
  const activated = signalHistory.filter((entry) => entry.status === "em_andamento").length;
  progress.textContent = currentOccurrenceView
    ? `${analysisSpinCount >= SIGNAL_ACTIVATION_WINDOW ? "Janela de ativação encerrada" : `${SIGNAL_ACTIVATION_WINDOW - analysisSpinCount} jogada(s) para ativação`} · ${activated} aposta(s) em andamento · limite de ${SIGNAL_ATTEMPT_LIMIT} tentativas`
    : "Execute uma análise para iniciar o termômetro.";
  body.replaceChildren();
  if (!signalHistory.length) {
    const row = body.insertRow();
    cell(row, "Nenhum sinal registrado ainda.", "cs-empty").colSpan = 7;
    return;
  }
  signalHistory.slice(0, 100).forEach((entry) => {
    const row = body.insertRow();
    row.className = entry.status === "acerto" ? "cs-signal-win" : entry.status === "erro" ? "cs-signal-loss" : "";
    cell(row, new Date(entry.createdAt).toLocaleString("pt-BR"));
    cell(row, entry.occurrenceId || `Ocorrência ${entry.occurrenceIndex + 1}`);
    cell(row, entry.activationSpin ? `${entry.activationSpin}ª jogada` : "—");
    cell(row, entry.betNumbers?.length ? numberList(entry.betNumbers) : "—");
    cell(row, `${entry.attempts || 0}/${SIGNAL_ATTEMPT_LIMIT}`);
    cell(row, Number.isInteger(entry.result) ? numberPill(entry.result) : "—");
    cell(row, signalStatusLabel(entry.status));
  });
}

function advanceSignalThermometer(result) {
  for (const record of restoreActiveSignals()) {
    const attempts = (record.attempts || 0) + 1;
    const won = record.betNumbers?.includes(result);
    const status = won ? "acerto" : attempts >= SIGNAL_ATTEMPT_LIMIT ? "erro" : "em_andamento";
    updateSignalHistory(record.id, {
      attempts,
      status,
      resolvedAt: status === "em_andamento" ? null : new Date().toISOString(),
      result,
    });
    const state = signalStates.get(record.occurrenceIndex);
    const currentRow = currentOccurrenceView?.[0].rows.find((row) => row.index === record.occurrenceIndex);
    if (state && currentRow?.id === record.occurrenceId) {
      state.status = status;
      state.label = signalStatusLabel(status);
    }
  }

  if (!currentOccurrenceView) {
    renderSignalThermometer();
    return;
  }
  const [analysis, currentContext, searchSequence] = currentOccurrenceView;
  const orderedRows = [...analysis.rows].sort((left, right) => occurrenceOrder(left, right, searchSequence));
  const eligible = [];
  for (const row of orderedRows) {
    const state = signalStateFor(row);
    const activation = signalActivation(row, liveMarkedNumbers, currentContext, searchSequence);
    state.counts = activation.counts;
    if (state.status === "aguardando" && activation.active && analysisSpinCount <= SIGNAL_ACTIVATION_WINDOW) {
      eligible.push({ row, state });
    }
  }

  if (eligible.length) {
    const { row, state } = eligible[0];
    const recordId = `${Date.now()}-${row.index}-${Math.random().toString(36).slice(2, 8)}`;
    const record = {
      id: recordId,
      analysisId: currentAnalysisId,
      createdAt: new Date().toISOString(),
      occurrenceId: row.id,
      occurrenceIndex: row.index,
      activationSpin: analysisSpinCount,
      attempts: 0,
      betNumbers: unmarkedBetNumbers(row, liveMarkedNumbers, currentContext, searchSequence),
      status: "em_andamento",
    };
    appendSignalRecord(record);
    state.status = "em_andamento";
    state.recordId = recordId;
    for (const discarded of eligible.slice(1)) {
      discarded.state.status = "descartado";
      discarded.state.label = "Descartada por ativação simultânea";
      appendSignalRecord({
        id: `${Date.now()}-${discarded.row.index}-${Math.random().toString(36).slice(2, 8)}`,
        analysisId: currentAnalysisId,
        createdAt: new Date().toISOString(),
        occurrenceId: discarded.row.id,
        occurrenceIndex: discarded.row.index,
        activationSpin: analysisSpinCount,
        attempts: 0,
        betNumbers: [],
        status: "descartado",
      });
    }
  }

  if (analysisSpinCount >= SIGNAL_ACTIVATION_WINDOW) {
    for (const row of analysis.rows) {
      const state = signalStateFor(row);
      if (state.status === "aguardando") {
        state.status = "cancelado";
        state.label = "Cancelada: não ativou em 5 jogadas";
      }
    }
  }
  renderOccurrences(analysis, currentContext, searchSequence);
  renderSignalThermometer();
}

function renderMatchDetails(matches) {
  const details = document.createElement("details");
  details.className = "cs-match-details";
  const summary = document.createElement("summary");
  summary.textContent = "Ver correspondências e pontuação";
  details.append(summary);
  const list = document.createElement("ol");
  list.className = "cs-match-list";
  matches.forEach((match) => {
    const item = document.createElement("li");
    const kind = match.type === "exact" ? "exata" : "vizinho";
    item.textContent = `${match.current} ↔ ${match.historical}: ${kind}, ${match.points} pontos (posição ${match.currentIndex + 1} com posição ${match.historicalIndex + 1})`;
    list.append(item);
  });
  if (!matches.length) {
    const item = document.createElement("li");
    item.textContent = "Nenhuma correspondência; 0 pontos.";
    list.append(item);
  }
  details.append(list);
  return details;
}

function renderFollowingDetails(following) {
  const details = document.createElement("details");
  details.className = "cs-match-details";
  const summary = document.createElement("summary");
  summary.textContent = "Ver contribuição de cada resultado posterior";
  details.append(summary);
  const list = document.createElement("ol");
  list.className = "cs-match-list";
  if (Array.isArray(following) && following.length === CONFIG.followingLength &&
      following.every((number) => Number.isInteger(number) && number >= 0 && number <= 36)) {
    following.forEach((number, index) => {
      const item = document.createElement("li");
      const [left, right] = neighborsOf(number);
      item.textContent = `Posterior ${index + 1}: ${number} → ${number} +10; ${left} +8; ${right} +8`;
      list.append(item);
    });
  } else {
    const item = document.createElement("li");
    item.textContent = "Array posterior inválido: nenhum ponto foi incluído no ranking.";
    list.append(item);
  }
  details.append(list);
  return details;
}

function renderSelected(analysis) {
  const container = $("#selected-details");
  container.replaceChildren();
  if (!analysis.selected.length) {
    const empty = document.createElement("p");
    empty.className = "cs-empty";
    empty.textContent = "Nenhuma ocorrência atingiu o corte com dados válidos.";
    container.append(empty);
    return;
  }
  analysis.selected.forEach((occurrence, index) => {
    const card = document.createElement("article");
    card.className = "cs-selected-card";
    const heading = document.createElement("h3");
    heading.textContent = `#${index + 1} · ${occurrence.id || "ID ausente"}`;
    card.append(heading);
    const facts = document.createElement("div");
    facts.className = "cs-selected-facts";
    for (const [label, values] of [["Anterior", occurrence.preceding], ["Sequência", occurrence.context], ["Posterior", occurrence.following]]) {
      const block = document.createElement("div");
      const title = document.createElement("span");
      title.textContent = label;
      block.append(title, numberList(values));
      facts.append(block);
    }
    const score = document.createElement("p");
    score.className = "cs-selected-score";
    score.textContent = `${occurrence.score.score}/50 pontos · ${formatPercent(occurrence.score.similarity)} · ${occurrence.score.exact} exatas · ${occurrence.score.neighbor} vizinhas`;
    card.append(facts, score, renderMatchDetails(occurrence.score.matches), renderFollowingDetails(occurrence.following));
    container.append(card);
  });
}

function renderRanking(result) {
  const body = $("#ranking-rows");
  body.replaceChildren();
  $("#ranking-denominator").textContent = `Máximo individual: ${result.maximum} pontos (${result.analyzedResults} resultados × 10)`;
  result.ranking.forEach((entry, index) => {
    const row = body.insertRow();
    if (entry.score > 0 && index < 6) row.className = "cs-top-number";
    cell(row, index + 1);
    cell(row, numberPill(entry.number));
    cell(row, entry.score);
    cell(row, entry.exact);
    cell(row, entry.neighbor);
    cell(row, formatPercent(entry.percentage));
  });
}

function setBusy(busy, message = "") {
  button.disabled = busy;
  button.textContent = busy ? "Buscando…" : "↻ Atualizar análise";
  status.textContent = message;
  status.dataset.state = busy ? "loading" : "idle";
}

function setLiveStatus(message, state = "idle") {
  const liveStatus = $("#live-status");
  if (!liveStatus) return;
  liveStatus.textContent = message;
  liveStatus.dataset.state = state;
}

function stopLiveResults(message = "Ao vivo: aguardando análise") {
  liveConnectionGeneration += 1;
  clearTimeout(liveReconnectTimer);
  liveReconnectTimer = null;
  const socket = liveSocket;
  liveSocket = null;
  if (socket) {
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    if (socket.readyState < WebSocket.CLOSING) socket.close();
  }
  setLiveStatus(message, "idle");
}

function startLiveResults() {
  stopLiveResults("Ao vivo: conectando…");
  const generation = liveConnectionGeneration;
  let observedResults = 0;

  function scheduleReconnect() {
    if (generation !== liveConnectionGeneration || liveReconnectTimer) return;
    setLiveStatus("Ao vivo: reconectando…", "reconnecting");
    const delay = liveReconnectDelay;
    liveReconnectDelay = Math.min(liveReconnectDelay * 2, 30000);
    liveReconnectTimer = setTimeout(() => {
      liveReconnectTimer = null;
      connect();
    }, delay);
  }

  function connect() {
    if (generation !== liveConnectionGeneration) return;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${window.location.host}/ws?slug=${encodeURIComponent(CONFIG.rouletteId)}`;
    let socket;
    try {
      socket = new WebSocket(url);
      liveSocket = socket;
      setLiveStatus("Ao vivo: conectando…", "connecting");
    } catch (_) {
      scheduleReconnect();
      return;
    }

    socket.onopen = () => {
      if (generation !== liveConnectionGeneration || socket !== liveSocket) return;
      liveReconnectDelay = 1000;
      setLiveStatus(`Ao vivo: conectado · ${observedResults} resultado(s) recebido(s)`, "connected");
    };
    socket.onmessage = (message) => {
      if (generation !== liveConnectionGeneration || socket !== liveSocket) return;
      let event;
      try { event = JSON.parse(message.data); } catch (_) { return; }
      if (event?.slug !== CONFIG.rouletteId || !Number.isInteger(event.result) || event.result < 0 || event.result > 36) return;
      observedResults += 1;
      setLiveStatus(`Ao vivo: conectado · ${observedResults} resultado(s) recebido(s)`, "connected");
      liveMarkedNumbers.add(event.result);
      analysisSpinCount += 1;
      if (currentOccurrenceView) renderOccurrences(...currentOccurrenceView);
      advanceSignalThermometer(event.result);
    };
    socket.onerror = () => {
      if (generation === liveConnectionGeneration && socket === liveSocket) socket.close();
    };
    socket.onclose = () => {
      if (generation !== liveConnectionGeneration || socket !== liveSocket) return;
      liveSocket = null;
      scheduleReconnect();
    };
  }

  connect();
}

async function runAnalysis() {
  activeController?.abort();
  stopLiveResults();
  liveMarkedNumbers.clear();
  currentAnalysisId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  analysisSpinCount = 0;
  signalStates = new Map();
  if (currentOccurrenceView) renderOccurrences(...currentOccurrenceView);
  activeController = new AbortController();
  const signal = activeController.signal;
  setBusy(true, "Carregando os últimos 9 resultados…");
  $("#returned-count").textContent = "—";
  $("#comparable-count").textContent = "—";
  $("#approved-count").textContent = "—";
  try {
    const historyResponse = await fetch(`/history/${CONFIG.rouletteId}?limit=9`, {
      headers: { Accept: "application/json" }, cache: "no-store", signal,
    });
    if (!historyResponse.ok) throw new Error(`Não foi possível carregar os resultados atuais (HTTP ${historyResponse.status}).`);
    const history = await historyResponse.json();
    const latestFirst = Array.isArray(history.items) ? history.items : [];
    const chronological = latestFirst.slice(0, 9).reverse();
    const values = chronological.map((item) => item?.value);
    $("#history-count").textContent = `${values.length}/9`;
    if (values.length !== 9 || values.some((value) => !Number.isInteger(value) || value < 0 || value > 36)) {
      throw new Error("São necessários 9 resultados válidos para separar o contexto e a sequência.");
    }
    const currentContext = values.slice(0, 5);
    const sequence = values.slice(5);
    setNumbers($("#current-context"), currentContext);
    setNumbers($("#current-sequence"), sequence);
    $("#updated-at").textContent = `Atualizado ${new Date().toLocaleTimeString("pt-BR")}`;
    setBusy(true, "Consultando o acervo vetorial…");
    const response = await fetch("/busca-vetorial/api/search", {
      method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" },
      cache: "no-store", signal,
      body: JSON.stringify({
        sequence, roulette_id: CONFIG.rouletteId, mode: "vector", exact: false,
        radius: 1, enable_digit_sum: false, enable_inverse: true, enable_custom_inverse: true,
        enable_terminal: false, strict_order: true, min_similarity: 0.85,
        k: 100, limit: 100, cutoff: null,
      }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = typeof payload?.detail === "string" ? payload.detail : `Falha HTTP ${response.status}.`;
      throw new Error(detail);
    }
    if (!payload || !Array.isArray(payload.occurrences)) throw new Error("A API vetorial retornou uma resposta sem ocorrências válidas.");
    const analysis = analyzeOccurrences(currentContext, payload.occurrences);
    const ranked = rankFollowing(analysis.selected);
    restoreActiveSignalStates(analysis);
    $("#returned-count").textContent = String(payload.occurrences.length);
    $("#comparable-count").textContent = String(analysis.comparableCount);
    $("#approved-count").textContent = String(analysis.rows.filter((row) => row.approved).length);
    renderOccurrences(analysis, currentContext, sequence);
    renderRanking(ranked);
    renderSelected(analysis);
    renderSignalThermometer();
    startLiveResults();
    setBusy(false, `${analysis.selected.length} ocorrência(s) selecionada(s); ${ranked.analyzedResults} resultado(s) posterior(es) analisado(s).`);
  } catch (error) {
    if (error.name === "AbortError") return;
    setBusy(false, error.message || "A análise não pôde ser concluída.");
    status.dataset.state = "error";
  }
}

occurrenceBody.addEventListener("click", handleOccurrenceNumberInput);
occurrenceBody.addEventListener("keydown", handleOccurrenceNumberInput);
button.addEventListener("click", runAnalysis);
window.addEventListener("pagehide", () => stopLiveResults("Ao vivo: página encerrada"));
window.addEventListener("pageshow", (event) => {
  if (event.persisted && currentOccurrenceView) startLiveResults();
});
const root = document.documentElement;
try {
  const savedTheme = localStorage.getItem("revesbot-theme");
  if (savedTheme) root.dataset.theme = savedTheme;
} catch (_) { /* tema salvo é opcional */ }
renderSignalThermometer();
runAnalysis();
