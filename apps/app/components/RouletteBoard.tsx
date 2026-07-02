'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

// Ordem física da roda europeia (para calcular vizinhos).
const WHEEL = [
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24,
  16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
];
const REDS = new Set([
  1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36,
]);
const color = (n: number) => (n === 0 ? 'g' : REDS.has(n) ? 'r' : 'b');

// Layout do pano: 3 linhas × 12 colunas (do topo para baixo).
const ROWS = [
  [3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36],
  [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35],
  [1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34],
];

const CHIPS = [0.5, 1, 2, 5, 10, 25];

function neighborsOf(n: number, k: number): number[] {
  const i = WHEEL.indexOf(n);
  if (i < 0) return [n];
  const out = [n];
  for (let d = 1; d <= k; d++) {
    out.push(WHEEL[(i - d + WHEEL.length) % WHEEL.length]);
    out.push(WHEEL[(i + d) % WHEEL.length]);
  }
  return [...new Set(out)];
}

interface TableState {
  sessionId: string;
  connected: boolean;
  phase: 'idle' | 'open' | 'closing' | 'closed';
  lastResult: number | null;
  lastNumbers: number[];
}

const PHASE_LABEL: Record<string, string> = {
  idle: 'Aguardando…',
  open: 'Apostas abertas',
  closing: 'Encerrando…',
  closed: 'Apostas fechadas',
};

export default function RouletteBoard({ gameId }: { gameId: string }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [conn, setConn] = useState<'connecting' | 'ready' | 'error'>('connecting');
  const [phase, setPhase] = useState<TableState['phase']>('idle');
  const [lastNumbers, setLastNumbers] = useState<number[]>([]);
  const [lastResult, setLastResult] = useState<number | null>(null);
  const [chip, setChip] = useState(1);
  const [neigh, setNeigh] = useState(0);
  const [placed, setPlaced] = useState<Record<number, number>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const sidRef = useRef<string | null>(null);

  // Cria a sessão da mesa (nosso WS via bet_ws) uma vez.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch(`/api/games/${gameId}/bet-session`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? 'Falha ao conectar.');
        if (!alive) return;
        sidRef.current = data.sessionId;
        setSessionId(data.sessionId);
      } catch (e) {
        if (alive) { setConn('error'); setMsg(e instanceof Error ? e.message : 'Erro'); }
      }
    })();
    return () => { alive = false; };
  }, [gameId]);

  // Assina o SSE de estado quando houver sessão.
  useEffect(() => {
    if (!sessionId) return;
    const es = new EventSource(`/api/games/${gameId}/table-events?sessionId=${sessionId}`);
    es.addEventListener('state', (ev) => {
      try {
        const s: TableState = JSON.parse((ev as MessageEvent).data);
        setConn('ready');
        setPhase(s.phase);
        if (Array.isArray(s.lastNumbers)) setLastNumbers(s.lastNumbers);
      } catch { /* ignora */ }
    });
    es.addEventListener('result', (ev) => {
      try {
        const { number } = JSON.parse((ev as MessageEvent).data);
        setLastResult(number);
        setPlaced({}); // nova rodada: limpa as fichas do pano
        setTimeout(() => setLastResult((r) => (r === number ? null : r)), 6000);
      } catch { /* ignora */ }
    });
    es.onerror = () => setConn((c) => (c === 'ready' ? c : 'error'));
    return () => es.close();
  }, [sessionId, gameId]);

  const placeOn = useCallback(
    async (n: number) => {
      const sid = sidRef.current;
      if (!sid || phase !== 'open') return;
      const numbers = neighborsOf(n, neigh);
      setPlaced((p) => {
        const c = { ...p };
        numbers.forEach((x) => (c[x] = (c[x] || 0) + 1));
        return c;
      });
      setMsg(null);
      try {
        const res = await fetch(`/api/games/${gameId}/place-bet`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ sessionId: sid, numbers, chipValue: chip }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? 'Falha ao apostar.');
      } catch (e) {
        // reverte a marcação otimista
        setPlaced((p) => {
          const c = { ...p };
          numbers.forEach((x) => { c[x] = Math.max(0, (c[x] || 0) - 1); if (!c[x]) delete c[x]; });
          return c;
        });
        setMsg(e instanceof Error ? e.message : 'Erro ao apostar.');
      }
    },
    [phase, neigh, chip, gameId],
  );

  const disabled = phase !== 'open' || conn !== 'ready';

  const cell = (n: number) => (
    <button
      key={n}
      className={`rb-num ${color(n)}${lastResult === n ? ' win' : ''}`}
      onClick={() => placeOn(n)}
      disabled={disabled}
      title={neigh > 0 ? `${n} + ${neigh} vizinho(s)` : `${n}`}
    >
      {n}
      {placed[n] ? <span className="rb-chip">{placed[n]}</span> : null}
    </button>
  );

  return (
    <div className="rb">
      <div className="rb-top">
        <div className={`rb-phase ph-${phase}`}>
          {conn === 'connecting' ? 'Conectando à mesa…' : PHASE_LABEL[phase]}
        </div>
        <div className="rb-last">
          {lastNumbers.slice(0, 12).map((n, i) => (
            <span key={`${n}-${i}`} className={`rb-last-n ${color(n)}`}>{n}</span>
          ))}
        </div>
      </div>

      <div className="rb-felt">
        <button
          className={`rb-num g zero${lastResult === 0 ? ' win' : ''}`}
          onClick={() => placeOn(0)}
          disabled={disabled}
        >
          0{placed[0] ? <span className="rb-chip">{placed[0]}</span> : null}
        </button>
        <div className="rb-grid">
          {ROWS.map((row, ri) => (
            <div key={ri} className="rb-row">{row.map(cell)}</div>
          ))}
        </div>
      </div>

      <div className="rb-controls">
        <div className="rb-chips">
          <span className="rb-lbl">Ficha</span>
          {CHIPS.map((c) => (
            <button
              key={c}
              className={`rb-chip-btn${chip === c ? ' on' : ''}`}
              onClick={() => setChip(c)}
            >
              {c}
            </button>
          ))}
        </div>
        <div className="rb-neigh">
          <span className="rb-lbl">Vizinhos</span>
          {[0, 1, 2].map((k) => (
            <button
              key={k}
              className={`rb-chip-btn${neigh === k ? ' on' : ''}`}
              onClick={() => setNeigh(k)}
            >
              {k}
            </button>
          ))}
        </div>
        {msg && <span className="rb-msg">{msg}</span>}
      </div>
    </div>
  );
}
