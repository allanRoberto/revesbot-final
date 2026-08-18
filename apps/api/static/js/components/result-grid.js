import { rouletteColor } from "../core/roulette-colors.js";

function slotsLabel(slots) {
  if (!slots || (Array.isArray(slots) && !slots.length)) return "";
  if (Array.isArray(slots)) return slots.map((slot) => typeof slot === "object" ? JSON.stringify(slot) : slot).join(", ");
  return typeof slots === "object" ? Object.entries(slots).map(([number, multiplier]) => `${number}:${multiplier}x`).join(" · ") : String(slots);
}

function resultCard(item) {
  const value = Number(item.value ?? item.result);
  const card = document.createElement("article");
  card.className = `result-card result-card--${rouletteColor(value)}`;
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

export function renderResults(container, items) {
  const fragment = document.createDocumentFragment();
  items.forEach((item) => fragment.append(resultCard(item)));
  container.replaceChildren(fragment);
}

export function prependResult(container, item) {
  container.prepend(resultCard(item));
}
