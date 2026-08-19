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

const SVG_NS = "http://www.w3.org/2000/svg";

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
  return element;
}

function ellipsePoint(cx, cy, rx, ry, angle) {
  return { x: cx + (rx * Math.cos(angle)), y: cy + (ry * Math.sin(angle)) };
}

function racetrackSectorPath(index, total) {
  const cx = 380;
  const cy = 160;
  const outerRx = 350;
  const outerRy = 145;
  const innerRx = 248;
  const innerRy = 72;
  const startAngle = (-Math.PI / 2) + ((Math.PI * 2 * index) / total);
  const endAngle = (-Math.PI / 2) + ((Math.PI * 2 * (index + 1)) / total);
  const outerStart = ellipsePoint(cx, cy, outerRx, outerRy, startAngle);
  const outerEnd = ellipsePoint(cx, cy, outerRx, outerRy, endAngle);
  const innerEnd = ellipsePoint(cx, cy, innerRx, innerRy, endAngle);
  const innerStart = ellipsePoint(cx, cy, innerRx, innerRy, startAngle);

  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${outerRx} ${outerRy} 0 0 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${innerRx} ${innerRy} 0 0 0 ${innerStart.x} ${innerStart.y}`,
    "Z",
  ].join(" ");
}

function bindActivation(element, callback) {
  element.addEventListener("click", callback);
  element.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    callback();
  });
}

function createRacetrack(container, onToggle) {
  const svg = svgElement("svg", {
    class: "roulette-racetrack-picker",
    viewBox: "0 0 760 320",
    role: "group",
    "aria-label": "Racetrack da roleta europeia",
  });

  svg.append(svgElement("ellipse", {
    class: "roulette-racetrack-picker__center",
    cx: 380,
    cy: 160,
    rx: 236,
    ry: 62,
  }));

  const centerLabel = svgElement("text", {
    class: "roulette-racetrack-picker__label",
    x: 380,
    y: 164,
    "text-anchor": "middle",
  });
  centerLabel.textContent = "RACETRACK EUROPEIA";
  svg.append(centerLabel);

  EUROPEAN_WHEEL.forEach((number, index) => {
    const middleAngle = (-Math.PI / 2) + ((Math.PI * 2 * (index + 0.5)) / EUROPEAN_WHEEL.length);
    const labelPoint = ellipsePoint(380, 160, 299, 108, middleAngle);
    const group = svgElement("g", {
      class: `roulette-racetrack-picker__number roulette-number--${rouletteColor(number)}`,
      "data-number": number,
      role: "button",
      tabindex: 0,
      "aria-label": `Selecionar número ${number}`,
      "aria-pressed": "false",
    });
    group.append(svgElement("path", { d: racetrackSectorPath(index, EUROPEAN_WHEEL.length) }));
    const text = svgElement("text", {
      x: labelPoint.x,
      y: labelPoint.y + 4,
      "text-anchor": "middle",
    });
    text.textContent = String(number);
    group.append(text);
    bindActivation(group, () => onToggle(number));
    svg.append(group);
  });

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
