'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { formatBRL } from '@/lib/format';
import RaceTrack from '@/components/RaceTrack';
import BetTable from '@/components/BetTable';
import CountdownRing from '@/components/CountdownRing';

// Ordem física da roda europeia (para calcular vizinhos e a pista).
const WHEEL = [
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24,
  16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
];
const REDS = new Set([
  1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36,
]);
const color = (n: number) => (n === 0 ? 'g' : REDS.has(n) ? 'r' : 'b');

const CHIPS = [0.5, 5, 10, 50, 250, 1000, 2500, 5000];
const chipLabel = (c: number) =>
  c >= 1000
    ? `${(c / 1000).toString().replace('.', ',')}K`
    : c.toString().replace('.', ',');
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
  timerDeadline?: number | null;
  kicked?: boolean;
  lastResult: number | null;
  lastNumbers: number[];
}

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
  const [timerDeadline, setTimerDeadline] = useState<number | null>(null);
  const [timerNow, setTimerNow] = useState(() => Date.now());
  const [lastNumbers, setLastNumbers] = useState<number[]>([]);
  const [lastResult, setLastResult] = useState<number | null>(null);
  const [chip, setChip] = useState(5);
  const [neigh, setNeigh] = useState(0);
  // Qual tabuleiro ocupa o slot central (maior): pista ou pano. O ⇄ troca.
  const [center, setCenter] = useState<'track' | 'felt'>('track');
  // Tempo total da rodada de apostas (para a fração do anel do contador).
  const [roundTotal, setRoundTotal] = useState(30);
  const prevPhaseRef = useRef<TableState['phase']>('idle');
  // placed: { numero: VALOR apostado em reais } — clicar de novo SOMA o valor
  // da ficha selecionada ao que já estava no número.
  const [placed, setPlaced] = useState<Record<number, number>>({});
  const [balance, setBalance] = useState<number | null>(initialBalance);
  const [msg, setMsg] = useState<string | null>(null);
  const [undoStack, setUndoStack] = useState<Record<number, number>[]>([]);
  const [repeatSlip, setRepeatSlip] = useState<Record<number, number> | null>(null);
  const sidRef = useRef<string | null>(null);
  // A mesa trata cada comando lpbet como o "slip" completo (substitui o anterior),
  // então mantemos o conjunto acumulado e reenviamos tudo a cada clique.
  const placedRef = useRef<Record<number, number>>({});
  // Pré-marcação: true quando há fichas marcadas com a mesa fechada, ainda não
  // enviadas — o slip é disparado ao reabrir as apostas.
  const pendingRef = useRef(false);

  // Aposta total da rodada (derivada do slip).
  const totalBet = Object.values(placed).reduce((s, v) => s + v, 0);

  // Cria a sessão da mesa (nosso WS via bet_ws) uma vez.
  useEffect(() => {
    let alive = true;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;
    let failedAttempts = 0;

    const connect = async () => {
      controller = new AbortController();
      if (alive) setConn('connecting');
      try {
        const res = await fetch(`/api/games/${gameId}/bet-session`, {
          method: 'POST',
          signal: controller.signal,
        });
        const contentType = res.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
          throw new Error(`Servidor da mesa respondeu em formato inválido (${res.status}).`);
        }
        const data: { sessionId?: string; error?: string } = await res.json();
        if (!res.ok) throw new Error(data.error ?? 'Falha ao conectar.');
        if (!data.sessionId) throw new Error('A sessão da mesa não foi criada.');
        if (!alive) return;
        sidRef.current = data.sessionId;
        setSessionId(data.sessionId);
        setMsg(null);
        failedAttempts = 0;
      } catch (e) {
        if (!alive || (e instanceof DOMException && e.name === 'AbortError')) return;
        setConn('error');
        setMsg(e instanceof Error ? e.message : 'Falha ao conectar à mesa.');
        const retryMs = Math.min(5000 * (2 ** failedAttempts), 60000);
        failedAttempts += 1;
        retryTimer = setTimeout(connect, retryMs);
      }
    };

    void connect();
    return () => {
      alive = false;
      controller?.abort();
      if (retryTimer) clearTimeout(retryTimer);
    };
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
        if (typeof s.timerDeadline === 'number' && Number.isFinite(s.timerDeadline)) {
          setTimerDeadline(s.timerDeadline);
          setTimerNow(Date.now());
        } else if (s.timerDeadline === null) {
          setTimerDeadline(null);
        } else if (s.phase === 'open' && typeof s.secondsLeft === 'number' && s.secondsLeft > 0) {
          // Compatibilidade durante atualização gradual do bet_ws.
          setTimerDeadline(Date.now() + s.secondsLeft * 1000);
          setTimerNow(Date.now());
        }
        if (Array.isArray(s.lastNumbers)) setLastNumbers(s.lastNumbers);
      } catch { /* ignora */ }
    });
    es.addEventListener('result', (ev) => {
      try {
        const { number } = JSON.parse((ev as MessageEvent).data);
        setLastResult(number);
        if (Object.keys(placedRef.current).length > 0) {
          setRepeatSlip({ ...placedRef.current });
        }
        setUndoStack([]);
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
    es.onerror = () => setConn((c) => (c === 'ready' ? c : 'error'));
    return () => es.close();
  }, [sessionId, gameId]);

  const seconds = timerDeadline == null
    ? null
    : Math.max(0, Math.ceil((timerDeadline - timerNow) / 1000));

  // Atualiza a apresentação usando um prazo absoluto. Assim throttling da aba
  // e eventos de fase não acumulam atraso nem reiniciam o número.
  useEffect(() => {
    if (timerDeadline == null) return;
    const tick = setInterval(() => setTimerNow(Date.now()), 250);
    const clear = setTimeout(
      () => setTimerDeadline((current) => (current === timerDeadline ? null : current)),
      Math.max(0, timerDeadline - Date.now()) + 700,
    );
    return () => {
      clearInterval(tick);
      clearTimeout(clear);
    };
  }, [timerDeadline]);

  // Ao ENTRAR na fase aberta, o primeiro secondsLeft é o total da rodada
  // (base para a fração do anel). Guardamos o maior visto no ciclo.
  useEffect(() => {
    if (phase === 'open' && seconds != null) {
      if (prevPhaseRef.current !== 'open') setRoundTotal(seconds || 30);
      else setRoundTotal((t) => (seconds > t ? seconds : t));
    }
    prevPhaseRef.current = phase;
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

  // Soma o valor da ficha nos números clicados. Com a mesa ABERTA, envia o slip
  // completo na hora (a mesa substitui a aposta anterior a cada envio). Com a
  // mesa FECHADA, apenas pré-marca localmente (pendingRef) — o slip é disparado
  // quando a mesa reabre.
  const commit = useCallback(
    async (added: number[]) => {
      if (added.length === 0) return;
      const sid = sidRef.current;
      if (!sid || conn !== 'ready') {
        setMsg('Ainda conectando à mesa… aguarde.');
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
      setUndoStack((stack) => [...stack, { ...prev }]);
      setMsg(null);

      // Apostas fechadas → guarda para a próxima rodada (não envia agora).
      if (phase !== 'open' && phase !== 'closing') {
        pendingRef.current = true;
        return;
      }

      try {
        const res = await fetch(`/api/games/${gameId}/place-bet`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ sessionId: sid, bets: next }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? 'Falha ao apostar.');
        pendingRef.current = false;
      } catch (e) {
        // reverte para o estado anterior a esta marcação
        placedRef.current = prev;
        setPlaced(prev);
        setUndoStack((stack) => stack.slice(0, -1));
        setMsg(e instanceof Error ? e.message : 'Erro ao apostar.');
      }
    },
    [phase, conn, chip, gameId, balance, totalBetCents],
  );

  // Ao REABRIR as apostas, dispara o slip pré-marcado (feito com a mesa fechada).
  useEffect(() => {
    if (phase !== 'open' || !pendingRef.current) return;
    const sid = sidRef.current;
    const slip = placedRef.current;
    if (!sid || Object.keys(slip).length === 0) {
      pendingRef.current = false;
      return;
    }
    (async () => {
      try {
        const res = await fetch(`/api/games/${gameId}/place-bet`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ sessionId: sid, bets: slip }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? 'Falha ao enviar a aposta.');
        pendingRef.current = false;
        setMsg(null);
      } catch (e) {
        setMsg(e instanceof Error ? e.message : 'Falha ao enviar a pré-marcação.');
      }
    })();
  }, [phase, gameId]);

  const placeOn = useCallback(
    (n: number) => commit(neighborsOf(n, neigh)),
    [commit, neigh],
  );

  const replaceSlip = useCallback(async (
    next: Record<number, number>,
    previous: Record<number, number>,
  ) => {
    const sid = sidRef.current;
    if (!sid || conn !== 'ready') {
      setMsg('Ainda conectando à mesa… aguarde.');
      return false;
    }

    placedRef.current = next;
    setPlaced(next);
    setMsg(null);

    if (phase !== 'open' && phase !== 'closing') {
      pendingRef.current = Object.keys(next).length > 0;
      return true;
    }

    try {
      const res = await fetch(`/api/games/${gameId}/place-bet`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ sessionId: sid, bets: next }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? 'Falha ao atualizar a aposta.');
      pendingRef.current = false;
      return true;
    } catch (e) {
      placedRef.current = previous;
      setPlaced(previous);
      setMsg(e instanceof Error ? e.message : 'Erro ao atualizar a aposta.');
      return false;
    }
  }, [conn, phase, gameId]);

  const undoBet = useCallback(async () => {
    const previous = undoStack.at(-1);
    if (!previous) return;
    const current = { ...placedRef.current };
    if (await replaceSlip(previous, current)) {
      setUndoStack((stack) => stack.slice(0, -1));
      setRepeatSlip(current);
    }
  }, [replaceSlip, undoStack]);

  const repeatBet = useCallback(async () => {
    if (!repeatSlip || Object.keys(repeatSlip).length === 0) return;
    const previous = { ...placedRef.current };
    if (balance != null) {
      const repeatedCents = Math.round(Object.values(repeatSlip).reduce((sum, value) => sum + value, 0) * 100);
      if (repeatedCents > balance) {
        setMsg('Saldo insuficiente para repetir esta aposta.');
        return;
      }
    }
    if (await replaceSlip({ ...repeatSlip }, previous)) {
      setUndoStack((stack) => [...stack, previous]);
      setRepeatSlip(null);
    }
  }, [balance, repeatSlip, replaceSlip]);

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

  // Só bloqueia a marcação quando a mesa não está utilizável (sem conexão/kick).
  // Com apostas fechadas a pessoa PODE marcar para a próxima jogada (pré-marca).
  const disabled = conn !== 'ready' || kicked;
  // Apostas fechadas: apenas ENCOLHE o tabuleiro central (sem sumir/bloquear).
  const betsClosed = conn === 'ready' && !kicked && (phase === 'closed' || phase === 'idle');

  // HUD que acompanha o tabuleiro central: contador (apostas abertas) e faixa
  // "Aguarde o próximo jogo" (entre rodadas). Fica logo acima do centro.
  const centerHud = (
    <div className="st-centerhud">
      {(phase === 'open' || phase === 'closing' || phase === 'closed') && seconds != null && (
        <CountdownRing
          seconds={seconds}
          total={roundTotal}
          alert={phase === 'closing' || phase === 'closed'}
        />
      )}
      {lastResult == null && seconds == null && (phase === 'idle' || phase === 'closed') && (
        <div className="st-waitbanner">Aguarde o próximo jogo</div>
      )}
    </div>
  );

  return (
    <div className={`st-overlay${betsClosed ? ' bets-closed' : ''}`}>
      {/* pano de apostas — objeto do mesmo plugin, fichas sincronizadas */}
      <div className={`st-felt ${center === 'felt' ? 'st-slot-center' : 'st-slot-side'}`}>
        {center === 'felt' && (
          <button
            className="st-swapbtn"
            title="Trocar pano ↔ pista"
            onClick={() => setCenter('track')}
          >
            ⇄
          </button>
        )}
        {center === 'felt' && centerHud}
        <BetTable
          placed={placed}
          lastResult={lastResult}
          disabled={disabled}
          onNumber={placeOn}
          onSection={commit}
        />
      </div>

      {/* pista oval (racetrack) */}
      <div className={`st-track ${center === 'track' ? 'st-slot-center' : 'st-slot-side'}`}>
        {center === 'track' && (
          <button
            className="st-swapbtn"
            title="Trocar pano ↔ pista"
            onClick={() => setCenter('felt')}
          >
            ⇄
          </button>
        )}
        {center === 'track' && centerHud}
        <RaceTrack
          placed={placed}
          lastResult={lastResult}
          disabled={disabled}
          onNumber={placeOn}
          onSection={commit}
        />
        {/* vizinhos (0–9): só aparece SOBRE a racetrack, no estilo da foto */}
        <div className="rt-neigh">
          <button
            className="rt-neigh-btn"
            onClick={() => setNeigh((k) => Math.max(0, k - 1))}
            aria-label="Menos vizinhos"
          >
            −
          </button>
          <span className="rt-neigh-val">{neigh}</span>
          <button
            className="rt-neigh-btn"
            onClick={() => setNeigh((k) => Math.min(9, k + 1))}
            aria-label="Mais vizinhos"
          >
            +
          </button>
        </div>
      </div>

      {/* painel compacto de resultados recentes */}
      <div className="st-side">
        <div className="st-panel">
          <div className="st-tabs">
            <span className="st-tab on">▦</span>
            <span className="st-tab">♥</span>
            <span className="st-tab">★</span>
            <span className="st-tab">▥</span>
          </div>
          <div className="st-lastrow">
            {lastNumbers.slice(0, 11).map((n, i) => (
              <span key={`${n}-${i}`} className={`st-last-n ${color(n)}${i === 0 ? ' first' : ''}`}>
                {n}
              </span>
            ))}
            {lastNumbers.length === 0 && <span className="st-panel-empty">Aguardando a mesa…</span>}
          </div>
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
        <button
          className="cb-round"
          disabled={disabled || undoStack.length === 0}
          title="Desfazer última aposta"
          aria-label="Desfazer última aposta"
          onClick={undoBet}
        >
          ↶
        </button>
        {CHIPS.map((c, i) => (
          <button
            key={c}
            className={`cb-chip c${i}${chip === c ? ' on' : ''}`}
            onClick={() => setChip(c)}
          >
            <span>{chipLabel(c)}</span>
          </button>
        ))}
        <button
          className="cb-round"
          disabled={disabled || !repeatSlip}
          title="Repetir aposta"
          aria-label="Repetir aposta"
          onClick={repeatBet}
        >
          ↻
        </button>
        {msg && <span className="rb-msg">{msg}</span>}
      </div>

      {/* A transmissão é independente da conexão de apostas. Este aviso não
          bloqueia mais o vídeo enquanto a sessão da mesa é reconectada. */}
      {(conn !== 'ready' || kicked) && (
        <div className={`st-connection-status ${conn === 'error' ? 'is-error' : ''}`}>
          {!kicked && <div className="st-spinner" aria-hidden />}
          <div className="st-connection-msg">
            {kicked
              ? 'Conta conectada em outro lugar'
              : conn === 'error'
                ? 'Reconectando apostas…'
                : 'Conectando apostas…'}
          </div>
        </div>
      )}
    </div>
  );
}
