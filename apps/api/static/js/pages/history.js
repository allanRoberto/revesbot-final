import { fetchHistory, fetchRoulettes } from "../core/api-client.js?v=3";
import { ResultsSocket } from "../core/results-socket.js?v=3";
import { copyResults } from "../components/copy-results.js?v=3";
import { setLiveStatus } from "../components/live-status.js?v=3";
import { createNumberContextPanel } from "../components/number-context-panel.js?v=5";
import { bindResultHighlight, prependResult, renderResults, setResultHighlight } from "../components/result-grid.js?v=6";
import { bindRoulettePicker, fillRouletteCounts } from "../components/roulette-selector.js?v=4";

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
const socketToggleIcon = document.querySelector("#socket-toggle-icon");
const settingsMenu = document.querySelector("#history-settings");
let items = [];
let paused = false;

const contextPanel = createNumberContextPanel({
  root: document.querySelector("#number-context-panel"),
  closeButton: document.querySelector("#number-context-close"),
  behindInput: document.querySelector("#context-behind"),
  aheadInput: document.querySelector("#context-ahead"),
  ranking: document.querySelector("#context-ranking"),
  title: document.querySelector("#number-context-title"),
  onClose: () => setResultHighlight(grid, null),
  onVisibilityChange: (open) => document.body.classList.toggle("number-context-panel-open", open),
});

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
  contextPanel.update(items);
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
    contextPanel.update(items);
  },
});

bindRoulettePicker({
  dialog: document.querySelector("#roulette-picker"),
  openButton: document.querySelector("#roulette-picker-open"),
  closeButton: document.querySelector("#roulette-picker-close"),
});
bindResultHighlight(grid, (value, card, index) => {
  if (value === null) contextPanel.close({ notify: false });
  else {
    contextPanel.select(value, items, index);
    if (window.matchMedia("(max-width: 640px)").matches) {
      card.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }
});

limitSelect.addEventListener("change", () => {
  settingsMenu.open = false;
  loadHistory();
});
columnsSelect.addEventListener("change", () => {
  applyGridColumns(columnsSelect.value);
  try { localStorage.setItem(columnsStorageKey, columnsSelect.value); }
  catch (_) { /* The preference remains active for this page load. */ }
  settingsMenu.open = false;
});
socketToggle.addEventListener("click", async () => {
  paused = !paused;
  const label = paused ? "Retomar resultados ao vivo" : "Pausar resultados ao vivo";
  socketToggleIcon.textContent = paused ? "▶" : "⏸";
  socketToggle.setAttribute("aria-label", label);
  socketToggle.title = label;
  if (paused) { socket.disconnect(); setLiveStatus(status, statusText, "paused"); }
  else { await loadHistory(); socket.resume(); }
});

document.querySelector("#copy-results").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const original = button.textContent;
  try {
    await copyResults(items);
    button.textContent = "✓";
    button.setAttribute("aria-label", "Números copiados");
    button.title = "Números copiados";
  } catch (_) {
    button.textContent = "!";
    button.setAttribute("aria-label", "Falha ao copiar números");
    button.title = "Falha ao copiar números";
  }
  window.setTimeout(() => {
    button.textContent = original;
    button.setAttribute("aria-label", "Copiar números");
    button.title = "Copiar números";
  }, 1400);
});

const root = document.documentElement;
const savedTheme = localStorage.getItem("revesbot-theme");
if (savedTheme) root.dataset.theme = savedTheme;
document.querySelector("#theme-toggle").addEventListener("click", () => {
  root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
  localStorage.setItem("revesbot-theme", root.dataset.theme);
});

fetchRoulettes().then((data) => fillRouletteCounts(document.querySelector("#roulette-list"), data)).catch(() => {});
applyGridColumns(readSavedGridColumns());
await loadHistory();
socket.connect();
