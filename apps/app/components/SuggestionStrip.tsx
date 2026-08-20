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
  const [motorNumbers, setMotorNumbers] = useState<number[] | null>(null);
  const [last, setLast] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [auto, setAuto] = useState(true);
  const [recalcing, setRecalcing] = useState(false);
  const [locked, setLocked] = useState(false);

  // As duas sugestões rodam lado a lado para comparação de assertividade:
  // ensemble (algoritmo atual) e motor de correlações (porte do HTML).
  async function refresh() {
    try {
      const [res, resMotor] = await Promise.all([
        fetch(`/api/games/${gameId}/suggestion`, { cache: 'no-store' }),
        fetch(`/api/games/${gameId}/suggestion-motor`, { cache: 'no-store' }),
      ]);
      if (res.status === 402) {
        setLocked(true);
        return;
      }
      if (res.ok) {
        setLocked(false);
        const data = await res.json();
        if (Array.isArray(data.numbers)) setNumbers(data.numbers);
        if (Array.isArray(data.last)) setLast(data.last);
      }
      if (resMotor.ok) {
        const dataMotor = await resMotor.json();
        if (Array.isArray(dataMotor.numbers)) setMotorNumbers(dataMotor.numbers);
      }
    } catch {
      /* mantém último valor */
    } finally {
      setLoading(false);
    }
  }

  // Carrega uma vez ao abrir.
  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
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

  // "Marcar sugeridos": apenas simula o clique dos números no tabuleiro.
  // O RouletteBoard ouve este evento, coloca as fichas e envia a aposta —
  // a confirmação visual são as próprias fichas (sem mensagem).
  function markSuggested() {
    if (!numbers || numbers.length === 0) return;
    window.dispatchEvent(
      new CustomEvent('reves:mark', { detail: { numbers } }),
    );
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
        <div className="suggestion-group" title="Sugestão por ensemble (algoritmo atual)">
          <span className="suggestion-label">Ensemble</span>
          <div className="suggestion-chips">
            {locked ? (
              <span className="suggestion-empty">🔒 assine para ver</span>
            ) : loading && numbers === null ? (
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
        {!locked && (
          <div
            className="suggestion-group"
            title="Motor de correlações (porte do HTML) — em comparação com o ensemble"
          >
            <span className="suggestion-label">Motor</span>
            <div className="suggestion-chips">
              {loading && motorNumbers === null ? (
                <span className="suggestion-empty">calculando…</span>
              ) : motorNumbers && motorNumbers.length ? (
                motorNumbers.map((n) => (
                  <span key={n} className={`sug-chip ${colorClass(n)}`}>
                    {n}
                  </span>
                ))
              ) : (
                <span className="suggestion-empty">sem dados suficientes</span>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="suggestion-controls">
        {/* Marcar os números sugeridos na mesa (aposta real) */}
        {!locked && (
          <button
            className="mark-btn"
            onClick={markSuggested}
            disabled={!numbers || numbers.length === 0}
            title="Marcar os números sugeridos na mesa"
          >
            Marcar sugeridos
          </button>
        )}

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
