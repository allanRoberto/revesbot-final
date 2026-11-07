import { analyzeOccurrences, CONFIG, neighborsOf, rankFollowing } from "../core/contextual-similarity-model.js?v=20261106-30-top6";

const $ = (selector) => document.querySelector(selector);
const status = $("#analysis-status");
const button = $("#run-analysis");
const redNumbers = new Set([1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]);
let activeController = null;

function numberPill(value) {
  const pill = document.createElement("span");
  pill.className = `cs-number ${value === 0 ? "cs-number--green" : redNumbers.has(value) ? "cs-number--red" : "cs-number--black"}`;
  pill.textContent = String(value);
  return pill;
}

function numberList(values) {
  const list = document.createElement("span");
  list.className = "cs-number-list";
  if (Array.isArray(values)) values.forEach((value) => list.append(numberPill(value)));
  else list.textContent = "—";
  return list;
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

function renderOccurrences(analysis) {
  const body = $("#occurrence-rows");
  const selectedIds = new Set(analysis.selected.map((row) => row.id));
  const sorted = [...analysis.rows].sort((left, right) => {
    if (!left.score) return right.score ? 1 : left.index - right.index;
    if (!right.score) return -1;
    return right.score.score - left.score.score || right.score.exact - left.score.exact || left.index - right.index;
  });
  body.replaceChildren();
  if (!sorted.length) {
    const row = body.insertRow();
    cell(row, "A API não retornou ocorrências.", "cs-empty").colSpan = 10;
    return;
  }
  sorted.forEach((occurrence, index) => {
    const selected = selectedIds.has(occurrence.id);
    const row = body.insertRow();
    row.className = selected ? "cs-selected-row" : "";
    cell(row, index + 1);
    cell(row, occurrence.id || "ID ausente", "cs-id");
    cell(row, numberList(occurrence.precedingValid ? occurrence.preceding : null));
    cell(row, numberList(occurrence.contextValid ? occurrence.context : null));
    cell(row, numberList(occurrence.followingValid ? occurrence.following : null));
    cell(row, occurrence.score?.exact ?? "—");
    cell(row, occurrence.score?.neighbor ?? "—");
    cell(row, occurrence.score?.score ?? "—");
    cell(row, occurrence.score ? formatPercent(occurrence.score.similarity) : "—");
    const state = selected ? "Selecionada" : occurrence.approved ? "Aprovada" :
      !occurrence.precedingValid ? `Anterior ${occurrence.preceding_complete ? "inválido" : occurrence.preceding_lookup_status}` :
        !occurrence.contextValid ? "Contexto inválido" : "Abaixo do corte";
    cell(row, state, selected ? "cs-status-cell cs-status-cell--selected" : "cs-status-cell");
  });
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

async function runAnalysis() {
  activeController?.abort();
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
    $("#returned-count").textContent = String(payload.occurrences.length);
    $("#comparable-count").textContent = String(analysis.comparableCount);
    $("#approved-count").textContent = String(analysis.rows.filter((row) => row.approved).length);
    renderOccurrences(analysis);
    renderRanking(ranked);
    renderSelected(analysis);
    setBusy(false, `${analysis.selected.length} ocorrência(s) selecionada(s); ${ranked.analyzedResults} resultado(s) posterior(es) analisado(s).`);
  } catch (error) {
    if (error.name === "AbortError") return;
    setBusy(false, error.message || "A análise não pôde ser concluída.");
    status.dataset.state = "error";
  }
}

button.addEventListener("click", runAnalysis);
const root = document.documentElement;
try {
  const savedTheme = localStorage.getItem("revesbot-theme");
  if (savedTheme) root.dataset.theme = savedTheme;
} catch (_) { /* tema salvo é opcional */ }
runAnalysis();
