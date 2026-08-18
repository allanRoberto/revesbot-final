export async function copyResults(items) {
  const text = items.map((item) => item.value ?? item.result).join(", ");
  await navigator.clipboard.writeText(text);
}
