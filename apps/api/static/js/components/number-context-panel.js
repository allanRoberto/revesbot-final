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

  items.forEach((item, index) => {
    if (itemValue(item) !== selectedValue) return;
    matches.push(index);

    const hasCompleteAhead = index >= aheadCount;
    const hasCompleteBehind = index + behindCount < items.length;
    if (!hasCompleteAhead || !hasCompleteBehind) return;

    contexts.push({
      index,
      behind: items.slice(index + 1, index + 1 + behindCount).reverse().map(itemValue),
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

  const counts = new Map();
  contexts.forEach(({ ahead }) => ahead.forEach((value) => counts.set(value, (counts.get(value) || 0) + 1)));
  const total = contexts.length * aheadCount;

  if (!total) {
    container.textContent = "Ainda não há ocorrências com uma janela completa para analisar.";
    return;
  }

  [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0] - right[0])
    .forEach(([value, count]) => {
      const item = document.createElement("div");
      item.className = "context-ranking__item";
      item.append(numberChip(value, "context-ranking__number"));

      const metric = document.createElement("span");
      metric.textContent = `${count}× · ${((count / total) * 100).toFixed(1).replace(".", ",")}%`;
      item.append(metric);
      container.append(item);
    });
}

function appendSequence(group, values) {
  if (!values.length) {
    const empty = document.createElement("span");
    empty.className = "context-sequence__empty";
    empty.textContent = "—";
    group.append(empty);
    return;
  }
  values.forEach((value) => group.append(numberChip(value)));
}

function renderOccurrences(container, contexts, selectedValue) {
  container.replaceChildren();
  if (!contexts.length) {
    container.textContent = "Aumente a quantidade de resultados ou reduza a janela escolhida.";
    return;
  }

  contexts.forEach((context, occurrenceIndex) => {
    const row = document.createElement("article");
    row.className = "context-occurrence";

    const label = document.createElement("span");
    label.className = "context-occurrence__label";
    label.textContent = `Ocorrência ${occurrenceIndex + 1}`;
    row.append(label);

    const sequence = document.createElement("div");
    sequence.className = "context-sequence";

    const behind = document.createElement("div");
    behind.className = "context-sequence__group";
    behind.setAttribute("aria-label", "Números anteriores");
    appendSequence(behind, context.behind);
    sequence.append(behind);

    const selected = numberChip(selectedValue);
    selected.classList.add("context-number--selected");
    selected.setAttribute("aria-label", `Número analisado: ${selectedValue}`);
    sequence.append(selected);

    const ahead = document.createElement("div");
    ahead.className = "context-sequence__group";
    ahead.setAttribute("aria-label", "Números seguintes");
    appendSequence(ahead, context.ahead);
    sequence.append(ahead);

    row.append(sequence);
    container.append(row);
  });
}

export function createNumberContextPanel({ root, closeButton, behindInput, aheadInput, summary, ranking, occurrences, title, onClose }) {
  let selectedValue = null;
  let currentItems = [];

  function render() {
    if (selectedValue === null) return;
    const behindCount = normalizeWindow(behindInput.value, DEFAULT_BEHIND);
    const aheadCount = normalizeWindow(aheadInput.value, DEFAULT_AHEAD);
    behindInput.value = String(behindCount);
    aheadInput.value = String(aheadCount);

    const { contexts, totalMatches } = buildNumberContexts(currentItems, selectedValue, behindCount, aheadCount);
    title.textContent = `Análise do número ${selectedValue}`;
    summary.textContent = `${contexts.length} janelas completas de ${totalMatches} ocorrências em ${currentItems.length} resultados carregados.`;
    renderRanking(ranking, contexts, aheadCount);
    renderOccurrences(occurrences, contexts, selectedValue);
  }

  function close({ notify = true } = {}) {
    selectedValue = null;
    root.classList.remove("number-context-panel--open");
    root.setAttribute("aria-hidden", "true");
    if (notify) onClose?.();
  }

  function select(value, items) {
    selectedValue = Number(value);
    currentItems = items;
    root.classList.add("number-context-panel--open");
    root.setAttribute("aria-hidden", "false");
    render();
  }

  function update(items) {
    currentItems = items;
    render();
  }

  behindInput.value = String(readPreference(storageKeys.behind, DEFAULT_BEHIND));
  aheadInput.value = String(readPreference(storageKeys.ahead, DEFAULT_AHEAD));

  [[behindInput, storageKeys.behind, DEFAULT_BEHIND], [aheadInput, storageKeys.ahead, DEFAULT_AHEAD]].forEach(([input, key, fallback]) => {
    input.addEventListener("change", () => {
      const value = normalizeWindow(input.value, fallback);
      input.value = String(value);
      savePreference(key, value);
      render();
    });
  });

  closeButton.addEventListener("click", () => close());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && selectedValue !== null) close();
  });

  return { close, select, update };
}
