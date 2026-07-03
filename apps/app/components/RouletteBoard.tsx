'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { formatBRL } from '@/lib/format';

// Ordem física da roda europeia (para calcular vizinhos e a pista).
const WHEEL = [
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24,
  16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
];
const REDS = new Set([
  1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36,
]);
const color = (n: number) => (n === 0 ? 'g' : REDS.has(n) ? 'r' : 'b');

// Pano lateral (layout Pragmatic): colunas crescem de 3 em 3.
const FELT_ROWS = [
  [3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36],
  [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35],
  [1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34],
];

// Racetrack (pista oval), segmentos na ordem da roda.
const TRACK_LEFT = [0, 26, 3, 35]; // ponta esquerda (topo → base)
const TRACK_TOP = [32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30];
const TRACK_RIGHT = [8, 23, 10, 5]; // ponta direita (topo → base)
const TRACK_BOTTOM = [12, 28, 7, 29, 18, 22, 9, 31, 14, 20, 1, 33, 16, 24];

// Apostas anunciadas (call bets) — grupos clássicos da pista.
const SEC_JEU_ZERO = [0, 3, 12, 15, 26, 32, 35];
const SEC_VOISINS = [0, 2, 3, 4, 7, 12, 15, 18, 19, 21, 22, 25, 26, 28, 29, 32, 35];
const SEC_ORPHELINS = [1, 6, 9, 14, 17, 20, 31, 34];
const SEC_TIERS = [5, 8, 10, 11, 13, 16, 23, 24, 27, 30, 33, 36];

const CHIPS = [0.5, 1, 2, 5, 10, 25];
const POLL_MS = 15000;

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
  secondsLeft: number | null;
  kicked?: boolean;
  lastResult: number | null;
  lastNumbers: number[];
}

interface LogEntry {
  at: number;
  kind: string;
  label: string;
}

const PHASE_LABEL: Record<string, string> = {
  idle: 'Aguardando próxima rodada…',
  open: 'Apostas abertas',
  closing: 'Encerrando…',
  closed: 'Apostas fechadas',
};

export default function RouletteBoard({
  gameId,
  initialBalance = null,
}: {
  gameId: string;
  initialBalance?: number | null;
}) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [conn, setConn] = useState<'connecting' | 'ready' | 'error'>('connecting');
  const [phase, setPhase] = useState<TableState['phase']>('idle');
  const [kicked, setKicked] = useState(false);
  const [seconds, setSeconds] = useState<number | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [lastNumbers, setLastNumbers] = useState<number[]>([]);
  const [lastResult, setLastResult] = useState<number | null>(null);
  const [chip, setChip] = useState(1);
  const [neigh, setNeigh] = useState(0);
  const [placed, setPlaced] = useState<Record<number, number>>({});
  const [totalBet, setTotalBet] = useState(0); // em reais (valor enviado no slip)
  const [balance, setBalance] = useState<number | null>(initialBalance);
  const [msg, setMsg] = useState<string | null>(null);
  const sidRef = useRef<string | null>(null);
  // A mesa trata cada comando lpbet como o "slip" completo (substitui o anterior),
  // então mantemos o conjunto acumulado e reenviamos tudo a cada clique.
  const placedRef = useRef<Record<number, number>>({});

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
        setKicked(!!s.kicked);
        setSeconds(typeof s.secondsLeft === 'number' ? s.secondsLeft : null);
        if (Array.isArray(s.lastNumbers)) setLastNumbers(s.lastNumbers);
      } catch { /* ignora */ }
    });
    es.addEventListener('result', (ev) => {
      try {
        const { number } = JSON.parse((ev as MessageEvent).data);
        setLastResult(number);
        placedRef.current = {};
        setPlaced({}); // nova rodada: limpa as fichas do pano
        setTotalBet(0);
        setTimeout(() => setLastResult((r) => (r === number ? null : r)), 6000);
      } catch { /* ignora */ }
    });
    es.addEventListener('log', (ev) => {
      try {
        const l: LogEntry = JSON.parse((ev as MessageEvent).data);
        setLog((prev) => [l, ...prev].slice(0, 20));
      } catch { /* ignora */ }
    });
    es.onerror = () => setConn((c) => (c === 'ready' ? c : 'error'));
    return () => es.close();
  }, [sessionId, gameId]);

  // Countdown local: decrementa 1/s enquanto a mesa está aberta.
  useEffect(() => {
    if (phase !== 'open' || seconds == null) return;
    if (seconds <= 0) return;
    const t = setInterval(() => setSeconds((s) => (s == null || s <= 0 ? s : s - 1)), 1000);
    return () => clearInterval(t);
  }, [phase, seconds]);

  // Saldo ao vivo (mesma fonte do BalanceBadge).
  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const res = await fetch('/api/me', { cache: 'no-store' });
        if (!res.ok || !active) return;
        const data = await res.json();
        if (typeof data.balance === 'number') setBalance(data.balance);
      } catch { /* mantém último valor */ }
    }
    const id = setInterval(refresh, POLL_MS);
    return () => { active = false; clearInterval(id); };
  }, []);

  // Adiciona um conjunto de números (já expandidos) ao slip e reenvia tudo num
  // único comando — a mesa substitui a aposta anterior a cada envio.
  const commit = useCallback(
    async (added: number[]) => {
      const sid = sidRef.current;
      if (!sid || (phase !== 'open' && phase !== 'closing') || added.length === 0) return;

      const prev = placedRef.current;
      const prevTotal = totalBet;
      const next = { ...prev };
      added.forEach((x) => (next[x] = (next[x] || 0) + 1));
      placedRef.current = next;
      setPlaced(next);
      setMsg(null);

      const numbers = Object.keys(next).map(Number);
      setTotalBet(numbers.length * chip);
      try {
        const res = await fetch(`/api/games/${gameId}/place-bet`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ sessionId: sid, numbers, chipValue: chip }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? 'Falha ao apostar.');
      } catch (e) {
        // reverte para o estado anterior a esta marcação
        placedRef.current = prev;
        setPlaced(prev);
        setTotalBet(prevTotal);
        setMsg(e instanceof Error ? e.message : 'Erro ao apostar.');
      }
    },
    [phase, chip, gameId, totalBet],
  );

  const placeOn = useCallback(
    (n: number) => commit(neighborsOf(n, neigh)),
    [commit, neigh],
  );

  // "Marcar sugeridos": o SuggestionStrip dispara este evento com os números;
  // simulamos o clique deles no tabuleiro (fichas aparecem, aposta é enviada).
  useEffect(() => {
    const handler = (e: Event) => {
      const nums = (e as CustomEvent<{ numbers?: number[] }>).detail?.numbers;
      if (!Array.isArray(nums) || nums.length === 0) return;
      const expanded = [...new Set(nums.flatMap((n) => neighborsOf(n, neigh)))];
      commit(expanded);
    };
    window.addEventListener('reves:mark', handler);
    return () => window.removeEventListener('reves:mark', handler);
  }, [commit, neigh]);

  const disabled = (phase !== 'open' && phase !== 'closing') || conn !== 'ready';

  const feltCell = (n: number) => (
    <button
      key={n}
      className={`felt-cell ${color(n)}${lastResult === n ? ' win' : ''}`}
      onClick={() => placeOn(n)}
      disabled={disabled}
      title={neigh > 0 ? `${n} + ${neigh} vizinho(s)` : `${n}`}
    >
      {n}
      {placed[n] ? <span className="rb-chip">{placed[n]}</span> : null}
    </button>
  );

  const trackCell = (n: number) => (
    <button
      key={n}
      className={`track-cell ${color(n)}${lastResult === n ? ' win' : ''}`}
      onClick={() => placeOn(n)}
      disabled={disabled}
      title={neigh > 0 ? `${n} + ${neigh} vizinho(s)` : `${n}`}
    >
      {n}
      {placed[n] ? <span className="rb-chip sm">{placed[n]}</span> : null}
    </button>
  );

  const section = (label: string, numbers: number[], extra = '') => (
    <button
      className={`track-sec ${extra}`}
      onClick={() => commit(numbers)}
      disabled={disabled}
      title={`${label}: ${numbers.length} números`}
    >
      {label}
    </button>
  );

  return (
    <div className="st-overlay">
      {/* fase da mesa (pílula central no topo) */}
      <div className={`rb-phase st-phase ph-${phase}`}>
        {kicked
          ? 'Conta conectada em outro lugar'
          : conn === 'connecting'
            ? 'Conectando à mesa…'
            : conn === 'error'
              ? 'Sem conexão com a mesa'
              : phase === 'open' && seconds != null
                ? `${PHASE_LABEL[phase]} · ${seconds}s`
                : PHASE_LABEL[phase]}
      </div>

      {/* pano de apostas (esquerda) */}
      <div className="st-felt">
        <div className="felt-top">
          <button
            className={`felt-zero${lastResult === 0 ? ' win' : ''}`}
            onClick={() => placeOn(0)}
            disabled={disabled}
          >
            0{placed[0] ? <span className="rb-chip">{placed[0]}</span> : null}
          </button>
          <div className="felt-grid">
            {FELT_ROWS.map((row) => row.map(feltCell))}
          </div>
          <div className="felt-2to1">
            {[0, 1, 2].map((i) => (
              <button key={i} className="felt-out" disabled title="Em breve">
                2:1
              </button>
            ))}
          </div>
        </div>
        <div className="felt-dozens">
          {['1.ª 12', '2.ª 12', '3.ª 12'].map((d) => (
            <button key={d} className="felt-out" disabled title="Em breve">
              {d}
            </button>
          ))}
        </div>
        <div className="felt-evens">
          <button className="felt-out" disabled title="Em breve">1-18</button>
          <button className="felt-out" disabled title="Em breve">PARES</button>
          <button className="felt-out" disabled title="Em breve"><span className="fd r" /></button>
          <button className="felt-out" disabled title="Em breve"><span className="fd b" /></button>
          <button className="felt-out" disabled title="Em breve">ÍMPARES</button>
          <button className="felt-out" disabled title="Em breve">19-36</button>
        </div>
      </div>

      {/* pista oval (racetrack) */}
      <div className="st-track">
        <div className="track">
          <div className="track-end track-endL">{TRACK_LEFT.map(trackCell)}</div>
          <div className="track-mid">
            <div className="track-row">{TRACK_TOP.map(trackCell)}</div>
            <div className="track-sections">
              {section('JEU ZERO', SEC_JEU_ZERO, 'jz')}
              {section('VOISINS', SEC_VOISINS)}
              {section('ORPHELINS', SEC_ORPHELINS)}
              {section('TIERS', SEC_TIERS, 'tiers')}
            </div>
            <div className="track-row">{TRACK_BOTTOM.map(trackCell)}</div>
          </div>
          <div className="track-end track-endR">{TRACK_RIGHT.map(trackCell)}</div>
        </div>
      </div>

      {/* painel lateral direito (conteúdo definitivo virá depois) */}
      <div className="st-side">
        <div className="st-panel">
          <div className="st-tabs">
            <span className="st-tab on">▦</span>
            <span className="st-tab">♥</span>
            <span className="st-tab">★</span>
            <span className="st-tab">▥</span>
          </div>
          <div className="st-panel-body">
            {log.length > 0 ? (
              <ul className="rb-log-list">
                {log.map((l, i) => (
                  <li key={`${l.at}-${i}`} className={`rb-log-item lg-${l.kind}`}>
                    <span className="rb-log-time">
                      {new Date(l.at).toLocaleTimeString('pt-BR', { hour12: false })}
                    </span>
                    <span className="rb-log-label">{l.label}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <span className="st-panel-empty">Aguardando a mesa…</span>
            )}
          </div>
        </div>
        <div className="st-lastrow">
          {lastNumbers.slice(0, 11).map((n, i) => (
            <span key={`${n}-${i}`} className={`st-last-n ${color(n)}${i === 0 ? ' first' : ''}`}>
              {n}
            </span>
          ))}
        </div>
      </div>

      {/* saldo + aposta total (canto inferior esquerdo) */}
      <div className="st-wallet">
        <span className="st-wallet-ico" aria-hidden />
        <div className="st-wallet-seg">
          <span className="st-wallet-lbl">Saldo</span>
          <span className="st-wallet-val">
            {typeof balance === 'number' ? formatBRL(balance) : '—'}
          </span>
        </div>
        <div className="st-wallet-seg">
          <span className="st-wallet-lbl">Aposta total</span>
          <span className="st-wallet-val">
            {formatBRL(Math.round(totalBet * 100))}
          </span>
        </div>
      </div>

      {/* seletor de fichas + vizinhos (centro inferior) */}
      <div className="st-chipbar">
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
