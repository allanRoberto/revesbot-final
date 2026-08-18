async function requestJson(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Falha HTTP ${response.status}`);
  return response.json();
}

export async function fetchHistory(slug, limit = 100) {
  return requestJson(`/history/${encodeURIComponent(slug)}?limit=${limit}`);
}

export async function fetchDetailedHistory(slug, filters, limit = 500) {
  const params = new URLSearchParams({ limit: String(limit) });
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== "" && value != null) params.set(key, String(value));
  });
  return requestJson(`/history-detailed/${encodeURIComponent(slug)}?${params}`);
}

export function fetchRoulettes() {
  return requestJson("/api/roulettes-list");
}
