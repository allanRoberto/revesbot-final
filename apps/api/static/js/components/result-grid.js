import { rouletteColor } from "../core/roulette-colors.js";

function timeLabel(item) {
  if (item.time) return item.time;
  if (!item.timestamp) return "";
  const date = new Date(item.timestamp);
  return Number.isNaN(date.valueOf()) ? "" : date.toLocaleTimeString("pt-BR");
}

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

  const time = document.createElement("span");
  time.className = "result-card__time";
  time.textContent = timeLabel(item);
  card.append(time);

  if (item.winning_multiplier != null) {
    const multiplier = document.createElement("span");
    multiplier.className = "result-card__multiplier";
    multiplier.textContent = `${item.winning_multiplier}x`;
    card.append(multiplier);
  }

  const slots = slotsLabel(item.slots);
  if (slots) {
    const details = document.createElement("span");
    details.className = "result-card__slots";
    details.textContent = slots;
    details.title = slots;
    card.append(details);
  }
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
