'use client';

import { useEffect, useState } from 'react';

// Cores da roleta (conhecimento público — não é o algoritmo).
const REDS = new Set([
  1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36,
]);
const colorClass = (n: number) => (n === 0 ? 'g' : REDS.has(n) ? 'r' : 'b');

const POLL_MS = 15000;

export default function SuggestionStrip({ gameId }: { gameId: string }) {
  const [numbers, setNumbers] = useState<number[] | null>(null);
  const [last, setLast] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [auto, setAuto] = useState(true);
  const [recalcing, setRecalcing] = useState(false);

  async function refresh() {
    try {
      const res = await fetch(`/api/games/${gameId}/suggestion`, {
        cache: 'no-store',
      });
      if (!res.ok) return;
      const data = await res.json();
      if (Array.isArray(data.numbers)) setNumbers(data.numbers);
      if (Array.isArray(data.last)) setLast(data.last);
    } catch {
      /* mantém último valor */
    } finally {
      setLoading(false);
    }
  }

  // Carrega uma vez ao abrir.
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gameId]);

  // Recálculo automático: só quando ligado.
  useEffect(() => {
    if (!auto) return;
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, gameId]);

  async function manualRecalc() {
    setRecalcing(true);
    await refresh();
    setRecalcing(false);
  }

  return (
    <div className="suggestion-zone">
      <div className="suggestion" title="Sugestão de aposta">
        {last.length > 0 && (
          <div
            className="suggestion-group suggestion-last"
            title="Últimos números da mesa (base da análise)"
          >
            <span className="suggestion-label">Últimos</span>
            <div className="suggestion-chips">
              {last.map((n, i) => (
                <span key={`${n}-${i}`} className={`sug-chip ${colorClass(n)}`}>
                  {n}
                </span>
              ))}
            </div>
          </div>
        )}
        <div className="suggestion-group">
          <span className="suggestion-label">Sugestão</span>
          <div className="suggestion-chips">
            {loading && numbers === null ? (
              <span className="suggestion-empty">calculando…</span>
            ) : numbers && numbers.length ? (
              numbers.map((n) => (
                <span key={n} className={`sug-chip ${colorClass(n)}`}>
                  {n}
                </span>
              ))
            ) : (
              <span className="suggestion-empty">sem dados suficientes</span>
            )}
          </div>
        </div>
      </div>

      <div className="suggestion-controls">
        {/* Recalcular agora (manual) */}
        <button
          className={`recalc-btn${recalcing ? ' spinning' : ''}`}
          onClick={manualRecalc}
          disabled={recalcing}
          title="Recalcular agora"
          aria-label="Recalcular agora"
        >
          ↻
        </button>

        {/* Toggle de recálculo automático (sempre visível) */}
        <label className="auto-toggle" title="Recálculo automático">
          <input
            type="checkbox"
            checked={auto}
            onChange={(e) => setAuto(e.target.checked)}
          />
          <span>Auto</span>
        </label>
      </div>
    </div>
  );
}
