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
  const [locked, setLocked] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [betting, setBetting] = useState(false);
  const [betMsg, setBetMsg] = useState<string | null>(null);

  async function refresh() {
    try {
      const res = await fetch(`/api/games/${gameId}/suggestion`, {
        cache: 'no-store',
      });
      if (res.status === 402) {
        setLocked(true);
        return;
      }
      if (!res.ok) return;
      setLocked(false);
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

  // Garante uma sessão de mesa (captura o WS via bet_ws). Reaproveita a atual.
  async function ensureSession(): Promise<string> {
    if (sessionId) return sessionId;
    const res = await fetch(`/api/games/${gameId}/bet-session`, {
      method: 'POST',
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error ?? 'Falha ao conectar na mesa.');
    setSessionId(data.sessionId);
    return data.sessionId;
  }

  // Marca (aposta) os números sugeridos na mesa.
  async function markSuggested() {
    setBetting(true);
    setBetMsg(null);
    try {
      let sid = await ensureSession();
      let res = await fetch(`/api/games/${gameId}/bet`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ sessionId: sid }),
      });
      // Sessão expirou/derrubada: recria uma vez e tenta de novo.
      if (res.status === 409 || res.status === 404) {
        const data = await res.clone().json().catch(() => ({}));
        if (String(data.error || '').includes('session_not_found')) {
          setSessionId(null);
          sid = await ensureSession();
          res = await fetch(`/api/games/${gameId}/bet`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ sessionId: sid }),
          });
        }
      }
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? 'Não foi possível marcar.');
      setBetMsg(`✓ Marcado: ${data.numbers.join(', ')}`);
    } catch (e) {
      setBetMsg(e instanceof Error ? e.message : 'Erro ao marcar.');
    } finally {
      setBetting(false);
    }
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
      </div>

      <div className="suggestion-controls">
        {/* Marcar os números sugeridos na mesa (aposta real) */}
        {!locked && (
          <button
            className="mark-btn"
            onClick={markSuggested}
            disabled={betting || !numbers || numbers.length === 0}
            title="Marcar os números sugeridos na mesa"
          >
            {betting ? 'Marcando…' : 'Marcar sugeridos'}
          </button>
        )}

        {betMsg && <span className="bet-msg">{betMsg}</span>}

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
