import { rouletteColor } from "../core/roulette-colors.js?v=3";
import { createRouletteSelectionBoards } from "./roulette-selection-boards.js?v=2";

function selectionChip(number, onRemove) {
  const button = document.createElement("button");
  button.className = `roulette-selection-panel__chip roulette-number--${rouletteColor(number)}`;
  button.type = "button";
  button.textContent = String(number);
  button.setAttribute("aria-label", `Remover número ${number} da seleção`);
  button.addEventListener("click", () => onRemove(number));
  return button;
}

export function createRouletteSelectionPanel({
  root,
  openButton,
  closeButton,
  backdrop,
  clearButton,
  count,
  selectedList,
  racetrackContainer,
  feltContainer,
}) {
  const selected = new Set();
  let isOpen = false;

  const boards = createRouletteSelectionBoards({
    racetrackContainer,
    feltContainer,
    onToggle: toggle,
  });

  function selectedValues() {
    return [...selected].sort((left, right) => left - right);
  }

  function announceChange() {
    root.dispatchEvent(new CustomEvent("roulette-selection-change", {
      bubbles: true,
      detail: { numbers: selectedValues() },
    }));
  }

  function render() {
    const values = selectedValues();
    count.textContent = values.length === 1 ? "1 número selecionado" : `${values.length} números selecionados`;
    clearButton.disabled = values.length === 0;
    selectedList.replaceChildren();

    if (!values.length) {
      const empty = document.createElement("span");
      empty.className = "roulette-selection-panel__empty";
      empty.textContent = "Clique nos números da racetrack ou do pano.";
      selectedList.append(empty);
    } else {
      values.forEach((number) => selectedList.append(selectionChip(number, toggle)));
    }

    boards.render(selected);
  }

  function toggle(number) {
    const normalized = Number(number);
    if (!Number.isInteger(normalized) || normalized < 0 || normalized > 36) return;
    if (selected.has(normalized)) selected.delete(normalized);
    else selected.add(normalized);
    render();
    announceChange();
  }

  function open() {
    if (isOpen) return;
    isOpen = true;
    root.classList.add("roulette-selection-panel--open");
    root.setAttribute("aria-hidden", "false");
    openButton.setAttribute("aria-expanded", "true");
    document.body.classList.add("roulette-selection-panel-open");
    window.requestAnimationFrame(() => closeButton.focus());
  }

  function close({ restoreFocus = true } = {}) {
    if (!isOpen) return;
    isOpen = false;
    root.classList.remove("roulette-selection-panel--open");
    root.setAttribute("aria-hidden", "true");
    openButton.setAttribute("aria-expanded", "false");
    document.body.classList.remove("roulette-selection-panel-open");
    if (restoreFocus) openButton.focus();
  }

  function clear() {
    if (!selected.size) return;
    selected.clear();
    render();
    announceChange();
  }

  openButton.addEventListener("click", open);
  closeButton.addEventListener("click", () => close());
  backdrop.addEventListener("click", () => close());
  clearButton.addEventListener("click", clear);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && isOpen) close();
  });

  render();

  return {
    open,
    close,
    clear,
    getSelection: selectedValues,
    setSelection(numbers) {
      selected.clear();
      numbers.forEach((number) => {
        const normalized = Number(number);
        if (Number.isInteger(normalized) && normalized >= 0 && normalized <= 36) selected.add(normalized);
      });
      render();
      announceChange();
    },
  };
}
