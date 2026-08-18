import { fetchHistory, fetchRoulettes } from "../core/api-client.js?v=3";
import { ResultsSocket } from "../core/results-socket.js?v=3";
import { copyResults } from "../components/copy-results.js?v=3";
import { setLiveStatus } from "../components/live-status.js?v=3";
import { bindResultHighlight, prependResult, renderResults } from "../components/result-grid.js?v=3";
import { bindRouletteSelector, fillRouletteCounts } from "../components/roulette-selector.js?v=3";

const app = document.querySelector("#history-app");
const slug = app.dataset.slug;
const grid = document.querySelector("#result-grid");
const empty = document.querySelector("#empty-state");
const summary = document.querySelector("#results-summary");
const limitSelect = document.querySelector("#result-limit");
const columnsSelect = document.querySelector("#grid-columns");
const status = document.querySelector("#live-status");
const statusText = document.querySelector("#live-status-text");
const socketToggle = document.querySelector("#socket-toggle");
let items = [];
let paused = false;

const columnsStorageKey = "revesbot-history-columns";
const allowedColumnValues = new Set(["auto", "5", "8", "10", "12", "15", "20"]);

function applyGridColumns(value) {
  const selectedValue = allowedColumnValues.has(value) ? value : "auto";
  columnsSelect.value = selectedValue;

  if (selectedValue === "auto") {
    grid.removeAttribute("data-columns");
    grid.removeAttribute("data-density");
    grid.style.removeProperty("--grid-columns");
    grid.style.removeProperty("--grid-min-width");
    return;
  }

  const columns = Number(selectedValue);
  grid.dataset.columns = selectedValue;
  grid.dataset.density = columns >= 16 ? "dense" : columns >= 12 ? "compact" : "comfortable";
  grid.style.setProperty("--grid-columns", selectedValue);
  grid.style.setProperty("--grid-min-width", `${(columns * 53) - 7}px`);
}

function readSavedGridColumns() {
  try { return localStorage.getItem(columnsStorageKey) || "auto"; }
  catch (_) { return "auto"; }
}

function updateView(nextItems) {
  items = nextItems;
  renderResults(grid, items);
  summary.textContent = `${items.length.toLocaleString("pt-BR")} resultados`;
  empty.hidden = items.length > 0;
}

async function loadHistory() {
  summary.textContent = "Carregando…";
  try {
    const payload = await fetchHistory(slug, Number(limitSelect.value));
    updateView(payload.items || (payload.results || []).map((value) => ({ value })));
  } catch (error) {
    summary.textContent = "Não foi possível carregar";
    empty.hidden = false;
  }
}

const socket = new ResultsSocket({
  slug,
  onStatus: (state) => setLiveStatus(status, statusText, paused ? "paused" : state),
  onResult: (event) => {
    const item = event.full_result || { value: event.result };
    const itemId = item._id;
    if (itemId && items.some((current) => current._id === itemId)) return;
    items.unshift(item);
    items = items.slice(0, Number(limitSelect.value));
    prependResult(grid, item);
    while (grid.children.length > items.length) grid.lastElementChild?.remove();
    summary.textContent = `${items.length.toLocaleString("pt-BR")} resultados`;
    empty.hidden = true;
  },
});

bindRouletteSelector(document.querySelector("#roulette-select"));
bindResultHighlight(grid);

limitSelect.addEventListener("change", loadHistory);
columnsSelect.addEventListener("change", () => {
  applyGridColumns(columnsSelect.value);
  try { localStorage.setItem(columnsStorageKey, columnsSelect.value); }
  catch (_) { /* The preference remains active for this page load. */ }
});
socketToggle.addEventListener("click", async () => {
  paused = !paused;
  socketToggle.textContent = paused ? "Retomar ao vivo" : "Pausar ao vivo";
  if (paused) { socket.disconnect(); setLiveStatus(status, statusText, "paused"); }
  else { await loadHistory(); socket.resume(); }
});

document.querySelector("#copy-results").addEventListener("click", async (event) => {
  const original = event.currentTarget.textContent;
  try { await copyResults(items); event.currentTarget.textContent = "Copiado"; }
  catch (_) { event.currentTarget.textContent = "Falha ao copiar"; }
  window.setTimeout(() => { event.currentTarget.textContent = original; }, 1400);
});

const root = document.documentElement;
const savedTheme = localStorage.getItem("revesbot-theme");
if (savedTheme) root.dataset.theme = savedTheme;
document.querySelector("#theme-toggle").addEventListener("click", () => {
  root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
  localStorage.setItem("revesbot-theme", root.dataset.theme);
});

fetchRoulettes().then((data) => fillRouletteCounts(document.querySelector("#roulette-select"), data)).catch(() => {});
applyGridColumns(readSavedGridColumns());
await loadHistory();
socket.connect();
