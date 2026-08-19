import { rouletteColor } from "../core/roulette-colors.js?v=3";

const MIN_WINDOW = 0;
const MAX_WINDOW = 20;
const DEFAULT_BEHIND = 3;
const DEFAULT_AHEAD = 5;
const storageKeys = {
  behind: "revesbot-context-behind",
  ahead: "revesbot-context-ahead",
};

function itemValue(item) {
  return Number(item?.value ?? item?.result);
}

function normalizeWindow(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(MIN_WINDOW, Math.min(MAX_WINDOW, parsed));
}

function readPreference(key, fallback) {
  try { return normalizeWindow(localStorage.getItem(key), fallback); }
  catch (_) { return fallback; }
}

function savePreference(key, value) {
  try { localStorage.setItem(key, String(value)); }
  catch (_) { /* The current selection still remains active. */ }
}

function numberChip(value, className = "context-number") {
  const chip = document.createElement("span");
  chip.className = `${className} ${className}--${rouletteColor(value)}`;
  chip.textContent = String(value);
  return chip;
}

export function buildNumberContexts(items, selectedValue, behindCount, aheadCount) {
  const matches = [];
  const contexts = [];
  let latestOccurrenceSkipped = false;

  items.forEach((item, index) => {
    if (itemValue(item) !== selectedValue) return;

    if (!latestOccurrenceSkipped) {
      latestOccurrenceSkipped = true;
      return;
    }
    matches.push(index);

    const hasCompleteAhead = index >= aheadCount;
    if (!hasCompleteAhead) return;

    contexts.push({
      index,
      behind: items.slice(index + 1, index + 1 + behindCount).map(itemValue),
      ahead: items.slice(index - aheadCount, index).reverse().map(itemValue),
    });
  });

  return { contexts, totalMatches: matches.length };
}

function renderRanking(container, contexts, aheadCount) {
  container.replaceChildren();
  if (aheadCount === 0) {
    container.textContent = "Escolha ao menos 1 número à frente para gerar o ranking.";
    return;
  }

  const rankedValues = rankedAheadValues(contexts);
  if (!rankedValues.length) {
    container.textContent = "Ainda não há ocorrências com uma janela completa para analisar.";
    return;
  }

  rankedValues.forEach((value) => container.append(numberChip(value, "context-ranking__number")));
}

export function rankedAheadValues(contexts) {
  const counts = new Map();
  contexts.forEach(({ ahead }) => ahead.forEach((value) => counts.set(value, (counts.get(value) || 0) + 1)));

  return [...counts.entries()]
    .sort(([leftValue, leftCount], [rightValue, rightCount]) => (
      rightCount - leftCount || leftValue - rightValue
    ))
    .map(([value]) => value);
}

export function createNumberContextPanel({ root, closeButton, behindInput, aheadInput, ranking, title, onClose }) {
  let selectedValue = null;
  let currentItems = [];

  function render() {
    if (selectedValue === null) return;
    const behindCount = normalizeWindow(behindInput.value, DEFAULT_BEHIND);
    const aheadCount = normalizeWindow(aheadInput.value, DEFAULT_AHEAD);
    behindInput.value = String(behindCount);
    aheadInput.value = String(aheadCount);

    const { contexts } = buildNumberContexts(currentItems, selectedValue, behindCount, aheadCount);
    title.textContent = `Análise do número ${selectedValue}`;
    renderRanking(ranking, contexts, aheadCount);
  }

  function close({ notify = true } = {}) {
    selectedValue = null;
    root.classList.remove("number-context-panel--open");
    root.setAttribute("aria-hidden", "true");
    if (notify) onClose?.();
  }

  function select(value, items) {
    selectedValue = Number(value);
    currentItems = items.slice();
    root.classList.add("number-context-panel--open");
    root.setAttribute("aria-hidden", "false");
    render();
  }

  function update(items) {
    if (selectedValue !== null) return;
    currentItems = items.slice();
  }

  behindInput.value = String(readPreference(storageKeys.behind, DEFAULT_BEHIND));
  aheadInput.value = String(readPreference(storageKeys.ahead, DEFAULT_AHEAD));

  [[behindInput, storageKeys.behind, DEFAULT_BEHIND], [aheadInput, storageKeys.ahead, DEFAULT_AHEAD]].forEach(([input, key, fallback]) => {
    function applyInput() {
      if (input.value === "") return;
      const value = normalizeWindow(input.value, fallback);
      input.value = String(value);
      savePreference(key, value);
      render();
    }

    input.addEventListener("input", applyInput);
    input.addEventListener("change", () => {
      if (input.value === "") input.value = String(fallback);
      applyInput();
    });
  });

  closeButton.addEventListener("click", () => close());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && selectedValue !== null) close();
  });

  return { close, select, update };
}
