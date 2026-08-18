const RED = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);

export function rouletteColor(value) {
  if (Number(value) === 0) return "green";
  return RED.has(Number(value)) ? "red" : "black";
}
