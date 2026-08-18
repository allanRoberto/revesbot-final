export function bindHistoryFilters(form, clearButton, onApply) {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    onApply(Object.fromEntries(new FormData(form).entries()));
  });
  clearButton.addEventListener("click", () => { form.reset(); onApply({}); });
}
