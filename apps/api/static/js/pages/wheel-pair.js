import { fetchHistory, fetchRoulettes } from "../core/api-client.js?v=3";
import { ResultsSocket } from "../core/results-socket.js?v=3";
import { rouletteColor } from "../core/roulette-colors.js?v=3";
import { copyResults } from "../components/copy-results.js?v=3";
import { setLiveStatus } from "../components/live-status.js?v=3";
import { renderResults } from "../components/result-grid.js?v=6";
import { bindRoulettePicker, fillRouletteCounts } from "../components/roulette-selector.js?v=4";

const app = document.querySelector("#history-app");
// Version the calculation with the page; existing shared modules keep their own versions.
const { analyzeSelection, summarizeBets, analyzeHeatmap } = await import(`../core/wheel-pair-model.js?v=${app.dataset.assetVersion}`);
const $ = (selector) => document.querySelector(selector);
const grid = $("#result-grid");
const panel = $("#wheel-pair-panel");
const list = $("#wheel-pair-list");
const summary = $("#wheel-pair-summary");
const selected = new Map();
const LIMIT = 1000;
let slug = app.dataset.slug;
let items = [];
let socket = null;
let paused = false;
let loading = false;
let requestGeneration = 0;
let localId = 0;
let lastSelectionKey = null;
let heatmapRace = null;
let heatmapSnapshot = null;
let inspectedHeatNumber = null;
let decayPercent = 100;
const heatWeightFormat = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });

function formattedWeight(weight) {
  return weight > 0 && weight < 0.001 ? "<0,001" : heatWeightFormat.format(weight);
}

// Absolute stops: reducing all bets also cools the colors instead of rescaling them.
const heatStops = [
  [0, [36, 87, 154]], [1, [104, 184, 245]], [2, [250, 204, 85]],
  [3, [251, 146, 60]], [5, [248, 113, 113]], [10, [220, 38, 38]],
];
function heatColor(weight) {
  if (weight <= 0) return "var(--wp-heat-zero)";
  const upper = heatStops.findIndex(([stop]) => stop >= weight);
  const [end, to] = heatStops[upper === -1 ? heatStops.length - 1 : upper];
  const [start, from] = heatStops[Math.max(0, upper - 1)];
  const ratio = end === start ? 1 : Math.min(1, (weight - start) / (end - start));
  return `rgb(${to.map((channel, index) => Math.round(from[index] + (channel - from[index]) * ratio)).join(", ")})`;
}

function heatInk(color) {
  const linear = color.match(/\d+/g).map((channel) => {
    const value = Number(channel) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  const luminance = linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
  return luminance > 0.179 ? "#000" : "#fff";
}

function namespaceRace(race) {
  const prefix = `wp-race-${++localId}-`;
  race.svg.querySelectorAll("[id]").forEach((node) => { node.id = prefix + node.id; });
  race.svg.querySelectorAll("[fill]").forEach((node) => {
    const fill = node.getAttribute("fill");
    if (fill.startsWith("url(#")) node.setAttribute("fill", fill.replace("url(#", `url(#${prefix}`));
  });
}

function inspectHeatNumber(number) {
  inspectedHeatNumber = number;
  const score = heatmapSnapshot?.scores[number];
  if (!score) return;
  $("#heatmap-pocket-info").textContent = `${number} · peso ${formattedWeight(score.weight)} · ${score.rawCount} apostas antes da redução · ${score.activeCount} com peso ativo`;
}

function ensureHeatmapRace() {
  if (heatmapRace) return;
  heatmapRace = new window.RouletteRacetrack($("#heatmap-race"), {
    responsive: false,
    onNumberHover: ({ number }) => inspectHeatNumber(number),
    onNumberClick: ({ number }) => inspectHeatNumber(number),
  });
  namespaceRace(heatmapRace);
  heatmapRace.svg.setAttribute("viewBox", "0 38 680 204");
  heatmapRace.svg.setAttribute("role", "img");
  heatmapRace.sectionsGroup.replaceChildren();
  for (const [y, text] of [[133, "Últimas 10 ocorrências"], [158, "Peso das apostas por número"]]) {
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", 340);
    label.setAttribute("y", y);
    label.setAttribute("class", "wheel-heatmap__annotation");
    label.textContent = text;
    heatmapRace.sectionsGroup.append(label);
  }
  heatmapRace.svg.querySelectorAll(".number-cell").forEach((cell) => {
    cell.append(document.createElementNS("http://www.w3.org/2000/svg", "title"));
  });
}

function renderHeatmap() {
  const container = $("#wheel-heatmap");
  container.hidden = !items.length;
  container.setAttribute("aria-busy", String(loading));
  heatmapSnapshot = analyzeHeatmap(items, decayPercent);
  $("#heatmap-decay").value = decayPercent;
  $("#heatmap-decay").setAttribute("aria-valuetext", `${decayPercent}% de redução por acerto`);
  $("#heatmap-decay-value").textContent = `${decayPercent}%`;
  container.querySelectorAll("[data-decay-preset]").forEach((button) => {
    button.setAttribute("aria-pressed", String(Number(button.dataset.decayPreset) === decayPercent));
  });
  if (!items.length) return;
  const model = heatmapSnapshot;
  ensureHeatmapRace();
  $("#heatmap-window").textContent = `Últimas ${model.sourceCount} ocorrências`;
  heatmapRace.sectionsGroup.firstElementChild.textContent = `Últimas ${model.sourceCount} ocorrências`;
  heatmapRace.svg.setAttribute("aria-label", `Mapa de calor das últimas ${model.sourceCount} ocorrências. Redução de ${decayPercent}% por acerto posterior. Peso máximo: ${formattedWeight(model.maxScore)}. Passe ou toque nos números para consultar os pesos.`);
  heatmapRace.svg.querySelectorAll(".number-cell").forEach((cell) => {
    const score = model.scores[Number(cell.dataset.n)];
    cell.dataset.heatNumber = score.number;
    cell.dataset.heatWeight = score.weight;
    cell.dataset.heatRawCount = score.rawCount;
    cell.dataset.heatActive = String(score.weight > 0);
    const color = heatColor(score.weight);
    cell.style.setProperty("--wp-heat-color", color);
    cell.style.setProperty("--wp-heat-ink", score.weight === 0 ? "var(--wp-heat-text)" : heatInk(color));
    cell.querySelector("title").textContent = `${score.number}: peso ${formattedWeight(score.weight)}; ${score.rawCount} apostas antes da redução; ${score.activeCount} com peso ativo.`;
  });
  $("#heatmap-status").textContent = `${model.readyCount} apostas analisadas · ${model.unpaidCount} ainda não atingidas · ${model.paidCount} já atingidas${model.skippedCount ? ` · ${model.skippedCount} sem análise válida` : ""}`;
  const ranking = $("#heatmap-ranking");
  ranking.replaceChildren();
  const leaders = model.scores.filter((score) => score.weight > 0)
    .sort((left, right) => right.weight - left.weight || left.number - right.number).slice(0, 8);
  for (const score of leaders) {
    const chip = element("span", "wheel-heatmap__rank");
    chip.dataset.heatRankedNumber = score.number;
    chip.dataset.heatWeight = score.weight;
    chip.append(numberChip(score.number), element("small", "", formattedWeight(score.weight)));
    chip.setAttribute("aria-label", `${score.number}: peso ${formattedWeight(score.weight)}`);
    ranking.append(chip);
  }
  if (!leaders.length) ranking.append(element("span", "wheel-pair-note", model.readyCount ? "Todas as apostas foram zeradas pela redução escolhida." : "Nenhuma aposta válida nesta janela."));
  const tbody = $("#heatmap-table-body");
  tbody.replaceChildren();
  for (const slot of model.slots) {
    const a = slot.analysis;
    const row = element("tr", slot.status !== "ready" ? "wheel-heatmap__skipped" : slot.hitCount ? "wheel-heatmap__paid" : "");
    row.dataset.heatSourceIndex = slot.index;
    row.dataset.heatSourceId = a.selectedId ?? items[slot.index]._wheelPairKey;
    row.dataset.heatSourceWeight = slot.weight ?? "";
    row.dataset.heatHitCount = slot.hitCount ?? "";
    const position = element("th", "", `${slot.index + 1}ª · base ${a.base ?? "—"}`);
    position.scope = "row";
    position.title = formattedTime(items[slot.index]);
    row.append(position);
    const ready = slot.status === "ready";
    const hitText = !ready ? slot.status === "no_previous" ? "Sem ocorrência anterior" : "Dados inválidos ou acompanhamento incompleto"
      : slot.hitCount ? `${slot.hitCount} · ${slot.hits.map((hit) => `${hit.value} (${hit.index + 1}ª)`).join(", ")}` : "Nenhum";
    [a.status === "ready" ? `[${a.offset}, ${a.base}]` : "—", a.status === "ready" ? `${a.leftCenter} / ${a.rightCenter}` : "—",
      a.bet.length ? a.bet.join(", ") : "—", hitText, ready ? formattedWeight(slot.weight) : "—"].forEach((text) => row.append(element("td", "", text)));
    tbody.append(row);
  }
  $("#heatmap-details summary").textContent = `Ver as ${model.sourceCount} ocorrências e seus acertos`;
  if (inspectedHeatNumber !== null) inspectHeatNumber(inspectedHeatNumber);
}

function changeDecay(value) {
  if (!Number.isInteger(value) || value < 0 || value > 100) return;
  decayPercent = value;
  renderHeatmap();
  try { localStorage.setItem("revesbot-wheel-heatmap-decay", String(value)); } catch (_) { /* Optional preference. */ }
}
try {
  const saved = localStorage.getItem("revesbot-wheel-heatmap-decay");
  if (saved !== null && /^\d{1,3}$/.test(saved) && Number(saved) <= 100) decayPercent = Number(saved);
} catch (_) { /* Keep the default when preferences are unavailable. */ }
$("#heatmap-decay").addEventListener("input", (event) => changeDecay(Number(event.target.value)));
$("#wheel-heatmap").querySelectorAll("[data-decay-preset]").forEach((button) => {
  button.addEventListener("click", () => changeDecay(Number(button.dataset.decayPreset)));
});

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function normalizeItem(item) {
  return { ...item, _wheelPairKey: item._id != null ? `id:${item._id}` : `local:${++localId}` };
}

function formattedTime(item) {
  const raw = item?.timestamp || item?.captured_at;
  if (!raw) return "Horário indisponível";
  const utc = typeof raw === "string" && !/(Z|[+-]\d\d:\d\d)$/i.test(raw) ? `${raw}Z` : raw;
  const date = new Date(utc);
  return Number.isNaN(date.getTime()) ? "Horário indisponível" : date.toLocaleString("pt-BR");
}

function numberChip(number, attribute) {
  const node = element("span", `wheel-pair-number wheel-pair-number--${rouletteColor(number)}`, number);
  if (attribute) node.setAttribute(attribute, number);
  return node;
}

function numberList(numbers, attribute) {
  const row = element("div", "wheel-pair-numbers");
  numbers.forEach((number) => row.append(numberChip(number, attribute)));
  return row;
}

function setPanelOpen(open) {
  panel.hidden = !open;
  panel.classList.toggle("number-context-panel--open", open);
  document.body.classList.toggle("number-context-panel-open", open);
  $("#selection-toggle").setAttribute("aria-expanded", String(open));
}

function paintGridSelection() {
  $("#wheel-heatmap").setAttribute("aria-busy", String(loading));
  [...grid.children].forEach((card, index) => {
    const item = items[index];
    const active = selected.has(item._wheelPairKey);
    card.dataset.resultIndex = index;
    card.dataset.resultId = item._id ?? item._wheelPairKey;
    card.setAttribute("aria-pressed", String(active));
    card.setAttribute("aria-label", `${active ? "Retirar" : "Selecionar"} resultado ${item.value}, ocorrência ${index + 1}, ${formattedTime(item)}`);
    card.disabled = loading;
  });
}

function updateHistoryView() {
  renderResults(grid, items);
  paintGridSelection();
  renderHeatmap();
  $("#results-summary").textContent = `${items.length.toLocaleString("pt-BR")} resultados`;
  $("#empty-state").hidden = items.length > 0;
  // Selected analyses are snapshots anchored to their result ID, never to a shifted live index.
  list.querySelectorAll("[data-selection-key]").forEach((card) => {
    card.dataset.selectionIndex = items.findIndex((item) => item._wheelPairKey === card.dataset.selectionKey);
  });
}

function addRace(container, analysis) {
  const race = new window.RouletteRacetrack(container, { responsive: false });
  race.svg.setAttribute("viewBox", "0 38 680 204");
  race.svg.setAttribute("role", "img");
  race.svg.setAttribute("aria-label", `Base ${analysis.base}. ${analysis.offset} casas em cada direção. Esquerda: ${analysis.left.join(", ")}. Direita: ${analysis.right.join(", ")}.`);
  // The shared plugin is unchanged. Namespace its SVG definitions for multiple races.
  namespaceRace(race);
  race.svg.querySelectorAll(".number-cell").forEach((cell) => {
    const number = Number(cell.dataset.n);
    cell.classList.toggle("wp-left", analysis.left.includes(number));
    cell.classList.toggle("wp-right", analysis.right.includes(number));
    cell.classList.toggle("wp-base", number === analysis.base);
    cell.classList.toggle("wp-center", number === analysis.leftCenter || number === analysis.rightCenter);
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    const leftStep = analysis.leftPath.indexOf(number);
    const rightStep = analysis.rightPath.indexOf(number);
    title.textContent = `${number}${number === analysis.base ? ": base" : ""}${leftStep > 0 ? `; esquerda: casa ${leftStep}` : ""}${rightStep > 0 ? `; direita: casa ${rightStep}` : ""}`;
    cell.append(title);
  });
  race.sectionsGroup.replaceChildren();
  [[190, "wp-annotation--left", `← ${analysis.offset} casas`], [340, "", `Base ${analysis.base}`], [490, "wp-annotation--right", `${analysis.offset} casas →`]].forEach(([x, css, label]) => {
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", x);
    text.setAttribute("y", 145);
    text.setAttribute("class", `wp-annotation ${css}`);
    text.textContent = label;
    race.sectionsGroup.append(text);
  });
}

function removeSelection(key) {
  selected.delete(key);
  paintGridSelection();
  renderSelections();
  if (!selected.size) setPanelOpen(false);
}

function selectionCard(key, entry) {
  const a = entry.analysis;
  const card = element("article", "wheel-pair-card");
  card.dataset.selectionKey = key;
  card.dataset.selectionIndex = items.findIndex((item) => item._wheelPairKey === key);
  const header = element("header", "wheel-pair-card__header");
  header.append(element("h3", "", `Base ${a.base ?? "—"}`));
  const remove = element("button", "icon-button wheel-pair-card__remove", "×");
  remove.type = "button";
  remove.setAttribute("aria-label", `Retirar aposta da base ${a.base}`);
  remove.addEventListener("click", () => { removeSelection(key); $("#selection-toggle").focus(); });
  header.append(remove);
  card.append(header, element("p", "wheel-pair-meta", `Selecionado: ${formattedTime(entry.item)}`));
  if (a.status !== "ready") {
    card.append(element("p", "wheel-pair-unavailable", a.status === "no_previous" ? "Ocorrência anterior não encontrada nos 1.000 resultados carregados. Selecione uma ocorrência mais recente." : "Este resultado não permite formar um par válido."));
    return card;
  }
  card.append(element("p", "wheel-pair-meta", `Ocorrência anterior: ${formattedTime(entry.previous)}`));
  const facts = element("dl", "wheel-pair-facts");
  [["Par anterior", `[${a.offset}, ${a.base}]`], ["Base", a.base], ["Casas", a.offset]].forEach(([label, value]) => {
    const field = element("div");
    field.append(element("dt", "", label), element("dd", "", value));
    facts.append(field);
  });
  card.append(facts);
  const race = element("div", "wheel-pair-race");
  card.append(race);
  // Build after insertion below, so the existing SVG renderer has a real container.
  card._renderRace = () => addRace(race, a);
  const legend = element("div", "wheel-pair-legend");
  legend.append(element("span", "", "Esquerda"), element("span", "wheel-pair-legend__right", "Direita"), element("span", "wheel-pair-legend__base", "Base: borda tracejada"));
  card.append(legend);
  [["left", "← Esquerda", a.leftCenter, a.left], ["right", "Direita →", a.rightCenter, a.right]].forEach(([side, label, center, numbers]) => {
    const section = element("div", `wheel-pair-sector wheel-pair-sector--${side}`);
    section.append(element("span", "wheel-pair-sector__label", `${label} · centro ${center}`), numberList(numbers));
    card.append(section);
  });
  const bet = element("section", "wheel-pair-bet");
  bet.append(element("h4", "", `Aposta em ordem crescente · ${a.bet.length} números`), numberList(a.bet, "data-bet-number"));
  if (a.bet.length < 10) bet.append(element("p", "wheel-pair-note", `Os setores se sobrepõem: são ${a.bet.length} números distintos, sem repetir na aposta.`));
  card.append(bet);
  const counting = element("details", "wheel-pair-counting");
  counting.append(element("summary", "", "Ver contagem casa por casa"));
  counting.append(element("p", "", `← Esquerda: ${a.leftPath.join(" → ")}`), element("p", "", `Direita →: ${a.rightPath.join(" → ")}`));
  card.append(counting);
  return card;
}

function renderSelections() {
  list.replaceChildren();
  for (const [key, entry] of selected) {
    const card = selectionCard(key, entry);
    list.append(card);
    card._renderRace?.();
  }
  const analyses = [...selected.values()].map((entry) => entry.analysis);
  const ready = analyses.filter((a) => a.status === "ready");
  $("#wheel-pair-count").textContent = `${selected.size} ${selected.size === 1 ? "resultado selecionado" : "resultados selecionados"} · ${ready.length} ${ready.length === 1 ? "aposta" : "apostas"}`;
  $("#wheel-pair-placeholder").hidden = selected.size > 0;
  $("#wheel-pair-clear").disabled = !selected.size;
  summary.hidden = !ready.length;
  summary.replaceChildren();
  if (!ready.length) return;
  const totals = summarizeBets(ready);
  const title = element("h3", "", "Resumo geral");
  title.id = "wheel-pair-summary-title";
  summary.append(title, element("p", "wheel-pair-note", `Números presentes em duas ou mais das ${ready.length} apostas. Cada número conta uma vez por aposta.`));
  const repeats = element("div", "wheel-pair-numbers");
  repeats.style.marginTop = "12px";
  totals.repeated.forEach(({ number, count }) => {
    const repeat = element("span", "wheel-pair-repeat");
    repeat.dataset.repeatedNumber = number;
    repeat.dataset.count = count;
    repeat.setAttribute("aria-label", `${number}: presente em ${count} apostas`);
    repeat.append(numberChip(number), element("small", "", `${count}×`));
    repeats.append(repeat);
  });
  summary.append(totals.repeated.length ? repeats : element("p", "wheel-pair-note", ready.length === 1 ? "Selecione outro resultado para comparar as apostas." : "Nenhum número se repetiu entre as apostas selecionadas."));
  summary.append(element("p", "wheel-pair-union-label", `Todos os números · ${totals.union.length} distintos`), numberList(totals.union, "data-union-number"));
}

grid.addEventListener("click", (event) => {
  const card = event.target.closest(".result-card");
  if (!card || !grid.contains(card) || loading) return;
  const index = Number(card.dataset.resultIndex);
  const item = items[index];
  const key = item._wheelPairKey;
  lastSelectionKey = key;
  if (selected.has(key)) removeSelection(key);
  else {
    const analysis = analyzeSelection(items, index);
    selected.set(key, { item, previous: items[analysis.previousIndex], analysis });
    setPanelOpen(true);
    paintGridSelection();
    renderSelections();
  }
});

function showMessage(message) {
  $("#page-message").textContent = message;
  $("#page-message").hidden = !message;
}

function connectResults(generation) {
  if (paused || generation !== requestGeneration) return;
  let syncRevision = 0;
  let bufferedResults = null;
  let currentState = "connecting";
  let syncFailed = false;

  async function synchronize() {
    const revision = ++syncRevision;
    const buffer = [];
    bufferedResults = buffer;
    loading = true;
    grid.setAttribute("aria-busy", "true");
    paintGridSelection();
    $("#results-summary").textContent = "Sincronizando…";
    try {
      // Subscribe first, then fetch: this also closes the initial fetch/connect gap.
      const payload = await fetchHistory(slug, LIMIT);
      if (generation !== requestGeneration || revision !== syncRevision) return;
      const raw = payload.items || (payload.results || []).map((value) => ({ value }));
      items = raw.slice(0, LIMIT).map(normalizeItem);
      // Events received during the query may already be in the snapshot.
      for (const result of buffer) {
        if (result._id != null && items.some((item) => item._id === result._id)) continue;
        items.unshift(normalizeItem(result));
      }
      items = items.slice(0, LIMIT);
      for (const key of selected.keys()) if (!items.some((item) => item._wheelPairKey === key)) selected.delete(key);
      bufferedResults = null;
      loading = false;
      updateHistoryView();
      renderSelections();
      if (!selected.size) setPanelOpen(false);
      showMessage("");
      setLiveStatus($("#live-status"), $("#live-status-text"), paused ? "paused" : currentState);
    } catch (_) {
      if (generation !== requestGeneration || revision !== syncRevision) return;
      syncFailed = true;
      bufferedResults = null;
      loading = false;
      socket?.disconnect();
      updateHistoryView();
      showMessage("Não foi possível sincronizar os giros. Exibindo o histórico anterior; use Atualizar histórico para tentar novamente.");
      setLiveStatus($("#live-status"), $("#live-status-text"), "offline");
    } finally {
      if (generation === requestGeneration && revision === syncRevision) grid.setAttribute("aria-busy", String(loading));
    }
  }

  socket = new ResultsSocket({
    slug,
    onStatus: (state) => {
      if (generation !== requestGeneration) return;
      currentState = state;
      if (state === "online" && !paused && !syncFailed) { synchronize(); return; }
      setLiveStatus($("#live-status"), $("#live-status-text"), paused ? "paused" : state);
    },
    onResult: (event) => {
      if (generation !== requestGeneration || paused || syncFailed) return;
      const raw = event.full_result || { value: event.result };
      if (!Number.isInteger(raw.value) || raw.value < 0 || raw.value > 36) return;
      if (bufferedResults) { bufferedResults.push(raw); return; }
      if (loading) return;
      if (raw._id != null && items.some((item) => item._id === raw._id)) return;
      items.unshift(normalizeItem(raw));
      items = items.slice(0, LIMIT);
      updateHistoryView();
    },
  });
  socket.connect();
}

async function loadHistory() {
  const generation = ++requestGeneration;
  socket?.disconnect();
  loading = true;
  grid.setAttribute("aria-busy", "true");
  paintGridSelection();
  $("#results-summary").textContent = "Carregando…";
  showMessage("");
  try {
    const payload = await fetchHistory(slug, LIMIT);
    if (generation !== requestGeneration) return;
    const raw = payload.items || (payload.results || []).map((value) => ({ value }));
    items = raw.slice(0, LIMIT).map(normalizeItem);
    // Explicit refresh uses the new snapshot; keep only selections still present by ID.
    for (const key of selected.keys()) if (!items.some((item) => item._wheelPairKey === key)) selected.delete(key);
    loading = false;
    updateHistoryView();
    renderSelections();
    if (!selected.size) setPanelOpen(false);
    setLiveStatus($("#live-status"), $("#live-status-text"), paused ? "paused" : "connecting");
    connectResults(generation);
  } catch (_) {
    if (generation !== requestGeneration) return;
    loading = false;
    updateHistoryView();
    showMessage(`Não foi possível carregar o histórico. Use Atualizar histórico para tentar novamente.${items.length ? " Exibindo os resultados carregados anteriormente." : ""}`);
    setLiveStatus($("#live-status"), $("#live-status-text"), "offline");
  } finally {
    if (generation === requestGeneration) grid.setAttribute("aria-busy", String(loading));
  }
}

bindRoulettePicker({ dialog: $("#roulette-picker"), openButton: $("#roulette-picker-open"), closeButton: $("#roulette-picker-close") });
$("#roulette-list").addEventListener("click", (event) => {
  const link = event.target.closest("[data-roulette-slug]");
  if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  $("#roulette-picker").close();
  if (link.dataset.rouletteSlug === slug) return;
  slug = link.dataset.rouletteSlug;
  app.dataset.slug = slug;
  const name = link.querySelector("span").textContent;
  $("#roulette-picker-open span").textContent = name;
  document.title = `Contagem de casas | ${name} | Revesbot`;
  $("#history-link").href = `/history/${encodeURIComponent(slug)}`;
  $("#roulette-list").querySelectorAll("[data-roulette-slug]").forEach((item) => {
    const current = item === link;
    item.classList.toggle("roulette-picker__item--current", current);
    if (current) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  history.replaceState(null, "", link.href);
  selected.clear();
  items = [];
  setPanelOpen(false);
  updateHistoryView();
  renderSelections();
  loadHistory();
});

$("#wheel-pair-close").addEventListener("click", () => { setPanelOpen(false); $("#selection-toggle").focus(); });
$("#selection-toggle").addEventListener("click", () => setPanelOpen(panel.hidden));
$("#wheel-pair-clear").addEventListener("click", () => { selected.clear(); renderSelections(); paintGridSelection(); setPanelOpen(false); $("#selection-toggle").focus(); });
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("#roulette-picker").open && !panel.hidden) {
    setPanelOpen(false);
    const index = items.findIndex((item) => item._wheelPairKey === lastSelectionKey);
    (grid.children[index] || $("#selection-toggle")).focus();
  }
});
$("#refresh-history").addEventListener("click", () => loadHistory());
$("#socket-toggle").addEventListener("click", async () => {
  paused = !paused;
  $("#socket-toggle-icon").textContent = paused ? "▶" : "⏸";
  const label = paused ? "Retomar resultados ao vivo" : "Pausar resultados ao vivo";
  $("#socket-toggle").setAttribute("aria-label", label);
  $("#socket-toggle").title = label;
  if (paused) { socket?.disconnect(); setLiveStatus($("#live-status"), $("#live-status-text"), "paused"); }
  else await loadHistory();
});

const allowedColumns = new Set(["auto", "5", "8", "10", "12", "15", "20"]);
function applyColumns(value) {
  const setting = allowedColumns.has(value) ? value : "auto";
  $("#grid-columns").value = setting;
  if (setting === "auto") {
    delete grid.dataset.columns;
    delete grid.dataset.density;
    grid.style.removeProperty("--grid-columns");
    grid.style.removeProperty("--grid-min-width");
  } else {
    grid.dataset.columns = setting;
    grid.dataset.density = Number(setting) >= 16 ? "dense" : Number(setting) >= 12 ? "compact" : "comfortable";
    grid.style.setProperty("--grid-columns", setting);
    grid.style.setProperty("--grid-min-width", `${Number(setting) * 53 - 7}px`);
  }
}
try { applyColumns(localStorage.getItem("revesbot-history-columns")); document.documentElement.dataset.theme = localStorage.getItem("revesbot-theme") || "dark"; }
catch (_) { applyColumns("auto"); }
$("#grid-columns").addEventListener("change", (event) => {
  applyColumns(event.target.value);
  try { localStorage.setItem("revesbot-history-columns", event.target.value); } catch (_) { /* Optional preference. */ }
  $("#history-settings").open = false;
});
$("#theme-toggle").addEventListener("click", () => {
  const root = document.documentElement;
  root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
  try { localStorage.setItem("revesbot-theme", root.dataset.theme); } catch (_) { /* Optional preference. */ }
});
$("#copy-results").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  try { await copyResults(items); button.textContent = "✓"; button.setAttribute("aria-label", "Números copiados"); }
  catch (_) { showMessage("Não foi possível copiar. Verifique a permissão da área de transferência."); }
  window.setTimeout(() => { button.textContent = "⧉"; button.setAttribute("aria-label", "Copiar números"); }, 1400);
});
fetchRoulettes().then((data) => fillRouletteCounts($("#roulette-list"), data)).catch(() => {});
renderSelections();
await loadHistory();
