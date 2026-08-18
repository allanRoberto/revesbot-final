export function bindRouletteSelector(select) {
  select.addEventListener("change", () => {
    location.assign(`/history/${encodeURIComponent(select.value)}`);
  });
}

export function fillRouletteCounts(select, roulettes) {
  const counts = new Map(roulettes.map((item) => [item.id, item.count]));
  [...select.options].forEach((option) => {
    const base = option.textContent.replace(/\s+\([\d.]+ resultados\)$/, "");
    const count = counts.get(option.value);
    option.textContent = count == null ? base : `${base} (${count.toLocaleString("pt-BR")} resultados)`;
  });
}
