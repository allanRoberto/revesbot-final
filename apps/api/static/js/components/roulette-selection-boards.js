import { rouletteColor } from "../core/roulette-colors.js?v=3";

export const EUROPEAN_WHEEL = Object.freeze([
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
  5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
]);

const TABLE_ROWS = Object.freeze([
  [3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36],
  [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35],
  [1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34],
]);

const RACETRACK_TOP = Object.freeze([15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11]);
const RACETRACK_BOTTOM = Object.freeze([12, 28, 7, 29, 18, 22, 9, 31, 14, 20, 1, 33, 16]);
const RACETRACK_LEFT = Object.freeze([32, 0, 26, 3, 35]);
const RACETRACK_RIGHT = Object.freeze([30, 8, 23, 10, 5, 24]);

const SVG_NS = "http://www.w3.org/2000/svg";

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
  return element;
}

function bindActivation(element, callback) {
  element.addEventListener("click", callback);
  element.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    callback();
  });
}

function racetrackNumberGroup(number, onToggle) {
  const group = svgElement("g", {
    class: `roulette-racetrack-picker__number roulette-number--${rouletteColor(number)}`,
    "data-number": number,
    role: "button",
    tabindex: 0,
    "aria-label": `Selecionar número ${number}`,
    "aria-pressed": "false",
  });
  bindActivation(group, () => onToggle(number));
  return group;
}

function appendRacetrackLabel(group, number, x, y) {
  const text = svgElement("text", { x, y, "text-anchor": "middle" });
  text.textContent = String(number);
  group.append(text);
}

function appendStraightNumber(svg, number, x, y, width, height, onToggle) {
  const group = racetrackNumberGroup(number, onToggle);
  group.append(svgElement("rect", { x, y, width, height }));
  appendRacetrackLabel(group, number, x + (width / 2), y + (height / 2) + 5);
  svg.append(group);
}

function appendCurveNumbers(svg, numbers, centerX, centerY, outerRadius, innerRadius, side, onToggle) {
  numbers.forEach((number, index) => {
    const startAngle = (90 - ((index * 180) / numbers.length)) * Math.PI / 180;
    const endAngle = (90 - (((index + 1) * 180) / numbers.length)) * Math.PI / 180;
    const sign = side === "left" ? -1 : 1;
    const outerSweep = side === "left" ? 0 : 1;
    const innerSweep = side === "left" ? 1 : 0;
    const outerStartX = centerX + (sign * outerRadius * Math.cos(startAngle));
    const outerStartY = centerY - (outerRadius * Math.sin(startAngle));
    const outerEndX = centerX + (sign * outerRadius * Math.cos(endAngle));
    const outerEndY = centerY - (outerRadius * Math.sin(endAngle));
    const innerStartX = centerX + (sign * innerRadius * Math.cos(startAngle));
    const innerStartY = centerY - (innerRadius * Math.sin(startAngle));
    const innerEndX = centerX + (sign * innerRadius * Math.cos(endAngle));
    const innerEndY = centerY - (innerRadius * Math.sin(endAngle));
    const path = [
      `M ${outerStartX} ${outerStartY}`,
      `A ${outerRadius} ${outerRadius} 0 0 ${outerSweep} ${outerEndX} ${outerEndY}`,
      `L ${innerEndX} ${innerEndY}`,
      `A ${innerRadius} ${innerRadius} 0 0 ${innerSweep} ${innerStartX} ${innerStartY}`,
      "Z",
    ].join(" ");
    const middleAngle = (startAngle + endAngle) / 2;
    const labelRadius = (innerRadius + outerRadius) / 2;
    const labelX = centerX + (sign * labelRadius * Math.cos(middleAngle));
    const labelY = centerY - (labelRadius * Math.sin(middleAngle)) + 5;
    const group = racetrackNumberGroup(number, onToggle);
    group.append(svgElement("path", { d: path }));
    appendRacetrackLabel(group, number, labelX, labelY);
    svg.append(group);
  });
}

function appendRacetrackCenter(svg) {
  svg.append(svgElement("path", {
    class: "roulette-racetrack-picker__center",
    d: "M 90 90 H 584 A 50 50 0 0 1 584 190 H 90 A 50 50 0 0 1 90 90 Z",
  }));

  [184, 316, 448].forEach((x) => svg.append(svgElement("line", {
    class: "roulette-racetrack-picker__divider",
    x1: x,
    y1: 90,
    x2: x,
    y2: 190,
  })));

  [
    [112, "JEU ZERO"],
    [250, "VOISINS"],
    [382, "ORPHELINS"],
    [522, "TIERS"],
  ].forEach(([x, label]) => {
    const text = svgElement("text", {
      class: "roulette-racetrack-picker__section-label",
      x,
      y: 146,
      "text-anchor": "middle",
    });
    text.textContent = label;
    svg.append(text);
  });
}

function createRacetrack(container, onToggle) {
  const svg = svgElement("svg", {
    class: "roulette-racetrack-picker",
    viewBox: "0 0 680 280",
    role: "group",
    "aria-label": "Racetrack da roleta europeia",
  });

  const cellWidth = 38;
  const cellHeight = 36;
  const centerY = 140;
  const outerRadius = 88;
  const innerRadius = 50;
  const straightStartX = 90;
  const topY = centerY - outerRadius;
  const bottomY = centerY + outerRadius - cellHeight;
  const straightEndX = straightStartX + (RACETRACK_TOP.length * cellWidth);

  appendRacetrackCenter(svg);
  RACETRACK_TOP.forEach((number, index) => appendStraightNumber(
    svg, number, straightStartX + (index * cellWidth), topY, cellWidth, cellHeight, onToggle,
  ));
  RACETRACK_BOTTOM.forEach((number, index) => appendStraightNumber(
    svg, number, straightStartX + (index * cellWidth), bottomY, cellWidth, cellHeight, onToggle,
  ));
  appendCurveNumbers(svg, RACETRACK_LEFT, straightStartX, centerY, outerRadius, innerRadius, "left", onToggle);
  appendCurveNumbers(svg, RACETRACK_RIGHT, straightEndX, centerY, outerRadius, innerRadius, "right", onToggle);

  container.replaceChildren(svg);
  return svg;
}

function feltButton(number, onToggle) {
  const button = document.createElement("button");
  button.className = `roulette-felt-picker__number roulette-number--${rouletteColor(number)}`;
  button.type = "button";
  button.dataset.number = String(number);
  button.setAttribute("aria-label", `Selecionar número ${number}`);
  button.setAttribute("aria-pressed", "false");
  button.textContent = String(number);
  button.addEventListener("click", () => onToggle(number));
  return button;
}

function createFelt(container, onToggle) {
  const felt = document.createElement("div");
  felt.className = "roulette-felt-picker";
  felt.setAttribute("role", "group");
  felt.setAttribute("aria-label", "Pano da roleta europeia");

  const zero = feltButton(0, onToggle);
  zero.classList.add("roulette-felt-picker__zero");
  felt.append(zero);

  TABLE_ROWS.forEach((row, rowIndex) => {
    row.forEach((number, columnIndex) => {
      const button = feltButton(number, onToggle);
      button.style.gridColumn = String(columnIndex + 2);
      button.style.gridRow = String(rowIndex + 1);
      felt.append(button);
    });
  });

  container.replaceChildren(felt);
  return felt;
}

export function createRouletteSelectionBoards({ racetrackContainer, feltContainer, onToggle }) {
  const racetrack = createRacetrack(racetrackContainer, onToggle);
  const felt = createFelt(feltContainer, onToggle);

  function render(selectedNumbers) {
    const selected = selectedNumbers instanceof Set ? selectedNumbers : new Set(selectedNumbers);
    [racetrack, felt].forEach((board) => {
      board.querySelectorAll("[data-number]").forEach((element) => {
        const isSelected = selected.has(Number(element.dataset.number));
        element.classList.toggle("is-selected", isSelected);
        element.setAttribute("aria-pressed", String(isSelected));
      });
    });
  }

  return { render };
}
