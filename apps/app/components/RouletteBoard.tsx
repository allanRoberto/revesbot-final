'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { formatBRL } from '@/lib/format';
import RaceTrack from '@/components/RaceTrack';
import BetTable from '@/components/BetTable';

// Ordem física da roda europeia (para calcular vizinhos e a pista).
const WHEEL = [
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24,
  16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
];
const REDS = new Set([
  1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36,
]);
const color = (n: number) => (n === 0 ? 'g' : REDS.has(n) ? 'r' : 'b');

const CHIPS = [0.5, 1, 2, 5, 10, 25];
const chipLabel = (c: number) => c.toString().replace('.', ',');
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
  // placed: { numero: VALOR apostado em reais } — clicar de novo SOMA o valor
  // da ficha selecionada ao que já estava no número.
  const [placed, setPlaced] = useState<Record<number, number>>({});
  const [balance, setBalance] = useState<number | null>(initialBalance);
  const [msg, setMsg] = useState<string | null>(null);
  const sidRef = useRef<string | null>(null);
  // A mesa trata cada comando lpbet como o "slip" completo (substitui o anterior),
  // então mantemos o conjunto acumulado e reenviamos tudo a cada clique.
  const placedRef = useRef<Record<number, number>>({});

  // Aposta total da rodada (derivada do slip).
  const totalBet = Object.values(placed).reduce((s, v) => s + v, 0);

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
        // rodada liquidada: ressincroniza o saldo real (ganho/perda já debitado)
        fetch('/api/me', { cache: 'no-store' })
          .then((r) => r.json())
          .then((d) => { if (typeof d.balance === 'number') setBalance(d.balance); })
          .catch(() => {});
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

  // Saldo-base (centavos): o valor real da conta. Só atualiza pelo polling
  // quando NÃO há aposta na mesa — assim o "disponível" (base − aposta total)
  // não conta em dobro se a casa debitar durante a rodada.
  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const res = await fetch('/api/me', { cache: 'no-store' });
        if (!res.ok || !active) return;
        const data = await res.json();
        if (typeof data.balance === 'number' && Object.keys(placedRef.current).length === 0) {
          setBalance(data.balance);
        }
      } catch { /* mantém último valor */ }
    }
    const id = setInterval(refresh, POLL_MS);
    return () => { active = false; clearInterval(id); };
  }, []);

  // Saldo disponível = base − aposta total desta rodada (em centavos).
  const totalBetCents = Math.round(totalBet * 100);
  const availableCents = balance != null ? balance - totalBetCents : null;

  // Soma o valor da ficha nos números clicados e reenvia o slip COMPLETO num
  // único comando — a mesa substitui a aposta anterior a cada envio.
  const commit = useCallback(
    async (added: number[]) => {
      if (added.length === 0) return;
      const sid = sidRef.current;
      if (!sid || conn !== 'ready') {
        setMsg('Ainda conectando à mesa… aguarde.');
        return;
      }
      if (phase !== 'open' && phase !== 'closing') {
        setMsg(
          phase === 'closed'
            ? 'Apostas fechadas — aguarde a próxima rodada.'
            : 'Aguarde as apostas abrirem para marcar.',
        );
        return;
      }

      // Bloqueia se o novo total ultrapassar o saldo da conta.
      const addedCostCents = Math.round(added.length * chip * 100);
      if (balance != null && totalBetCents + addedCostCents > balance) {
        setMsg('Saldo insuficiente para esta aposta.');
        return;
      }

      const prev = placedRef.current;
      const next = { ...prev };
      added.forEach((x) => {
        next[x] = Math.round(((next[x] || 0) + chip) * 100) / 100;
      });
      placedRef.current = next;
      setPlaced(next);
      setMsg(null);

      try {
        const res = await fetch(`/api/games/${gameId}/place-bet`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ sessionId: sid, bets: next }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? 'Falha ao apostar.');
      } catch (e) {
        // reverte para o estado anterior a esta marcação
        placedRef.current = prev;
        setPlaced(prev);
        setMsg(e instanceof Error ? e.message : 'Erro ao apostar.');
      }
    },
    [phase, conn, chip, gameId, balance, totalBetCents],
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

      {/* pano de apostas (esquerda) — objeto do mesmo plugin, fichas sincronizadas */}
      <div className="st-felt">
        <BetTable placed={placed} disabled={disabled} onNumber={placeOn} />
      </div>

      {/* pista oval (racetrack) */}
      <div className="st-track">
        <RaceTrack
          placed={placed}
          lastResult={lastResult}
          disabled={disabled}
          onNumber={placeOn}
          onSection={commit}
        />
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
            {availableCents != null ? formatBRL(Math.max(0, availableCents)) : '—'}
          </span>
        </div>
        <div className="st-wallet-seg">
          <span className="st-wallet-lbl">Aposta total</span>
          <span className="st-wallet-val">
            {formatBRL(totalBetCents)}
          </span>
        </div>
      </div>

      {/* seletor de fichas + vizinhos (centro inferior, estilo Pragmatic) */}
      <div className="st-chipbar">
        <button className="cb-round" disabled title="Em breve">↺</button>
        {CHIPS.map((c, i) => (
          <button
            key={c}
            className={`cb-chip c${i}${chip === c ? ' on' : ''}`}
            onClick={() => setChip(c)}
          >
            {chipLabel(c)}
          </button>
        ))}
        <button className="cb-round" disabled title="Em breve">⟳</button>
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
