import { rouletteColor } from "../core/roulette-colors.js?v=3";

let highlightedValue = null;

function slotsLabel(slots) {
  if (!slots || (Array.isArray(slots) && !slots.length)) return "";
  if (Array.isArray(slots)) return slots.map((slot) => typeof slot === "object" ? JSON.stringify(slot) : slot).join(", ");
  return typeof slots === "object" ? Object.entries(slots).map(([number, multiplier]) => `${number}:${multiplier}x`).join(" · ") : String(slots);
}

function resultCard(item) {
  const value = Number(item.value ?? item.result);
  const card = document.createElement("button");
  card.type = "button";
  card.className = `result-card result-card--${rouletteColor(value)}`;
  card.dataset.value = String(value);
  card.setAttribute("aria-label", `Destacar todas as ocorrências do número ${value}`);
  if (highlightedValue === value) card.classList.add("result-card--highlighted");
  card.title = item.formatted || item.timestamp || "";

  const number = document.createElement("strong");
  number.className = "result-card__number";
  number.textContent = String(value);
  card.append(number);

  if (item.winning_multiplier != null) {
    const multiplier = document.createElement("span");
    multiplier.className = "result-card__multiplier";
    multiplier.textContent = `${item.winning_multiplier}x`;
    card.append(multiplier);
  }

  const slots = slotsLabel(item.slots);
  if (slots) card.title = `${card.title}${card.title ? " · " : ""}Multiplicadores: ${slots}`;
  return card;
}

export function setResultHighlight(container, value) {
  highlightedValue = value == null ? null : Number(value);
  container.querySelectorAll(".result-card").forEach((item) => {
    item.classList.toggle(
      "result-card--highlighted",
      highlightedValue !== null && Number(item.dataset.value) === highlightedValue,
    );
  });
}

export function renderResults(container, items) {
  const fragment = document.createDocumentFragment();
  items.forEach((item) => fragment.append(resultCard(item)));
  container.replaceChildren(fragment);
}

export function prependResult(container, item) {
  container.prepend(resultCard(item));
}

export function bindResultHighlight(container, onSelectionChange = () => {}) {
  container.addEventListener("click", (event) => {
    const card = event.target.closest(".result-card");
    if (!card || !container.contains(card)) return;
    const value = Number(card.dataset.value);
    setResultHighlight(container, highlightedValue === value ? null : value);
    onSelectionChange(highlightedValue);
  });
}
