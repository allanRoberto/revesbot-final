export function bindRoulettePicker({ dialog, openButton, closeButton }) {
  openButton.addEventListener("click", () => {
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  });

  closeButton.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

export function fillRouletteCounts(list, roulettes) {
  const counts = new Map(roulettes.map((item) => [item.id, item.count]));
  list.querySelectorAll("[data-roulette-slug]").forEach((item) => {
    const count = counts.get(item.dataset.rouletteSlug);
    const target = item.querySelector("[data-roulette-count]");
    if (target) target.textContent = count == null ? "Sem dados" : `${count.toLocaleString("pt-BR")} resultados`;
  });
}
