'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import styles from './triggers.module.css';

type WindowKey = '1h' | '3h' | '6h' | '12h' | '24h' | 'all';
type OutcomeStatus = 'hit' | 'miss' | 'pending';

interface AttemptMetric {
  attempt: number;
  exact_hits: number;
  exact_hit_rate: number;
  hits: number;
  hit_rate: number;
  confidence_lower: number;
  confidence_upper: number;
  random_baseline: number;
  delta_percentage_points: number;
}

interface PerformanceWindow {
  sample_size: number;
  entry: {
    sample_size: number;
    average_target_size: number;
    misses_after_max_attempts: number;
    attempts: AttemptMetric[];
  };
}

interface TriggerPerformance {
  strategy_slug: string;
  available: boolean;
  total_trials: number;
  pending_trials: number;
  active_candidates: number;
  latest_activation_timestamp_utc: string | null;
  resolved_trials: number;
  max_attempts: number;
  windows: Record<WindowKey, PerformanceWindow>;
  best_hour: {
    label: string;
    sample_size: number;
    hit_rate: number;
    provisional: boolean;
  } | null;
}

interface StrategySpec {
  slug: string;
  name: string;
  short_name: string;
  summary: string;
  activation_rule: string;
  entry_rule: string;
  max_attempts: number;
}

interface CatalogStrategy extends StrategySpec {
  performance: TriggerPerformance;
}

interface CatalogPayload {
  engine_version: string;
  max_attempts: number;
  strategies: CatalogStrategy[];
  generated_at: string;
  error?: string;
}

interface TriggerAttempt {
  attempt: number;
  number: number;
  timestamp_utc: string | null;
  match: boolean;
}

interface TriggerTrial {
  event_id: string;
  strategy_slug: string;
  roulette_id: string;
  activation_timestamp_utc: string | null;
  activation_number: number | null;
  recent_pivots: number[];
  base_numbers: number[];
  entry_numbers: number[];
  target_size: number;
  metadata: Record<string, unknown>;
  attempts: TriggerAttempt[];
  attempts_observed: number;
  max_attempts: number;
  status: string;
  display_status: OutcomeStatus;
  outcome: {
    status: OutcomeStatus;
    first_hit_attempt: number | null;
    first_hit_timestamp_utc: string | null;
  };
}

interface RouletteDetail {
  roulette_id: string;
  name: string;
  performance: TriggerPerformance;
  history: TriggerTrial[];
}

interface DetailPayload {
  engine_version: string;
  strategy: StrategySpec;
  overall: TriggerPerformance;
  roulettes: RouletteDetail[];
  generated_at: string;
  error?: string;
}

interface ProfitChartPoint {
  signal: number;
  bank: number;
  net_profit: number;
  timestamp_utc: string | null;
}

interface ProfitabilityStrategy {
  slug: string;
  name: string;
  short_name: string;
  max_attempts: number;
  records_capped: boolean;
  initial_bank: number;
  final_bank: number;
  net_profit: number;
  roi_on_staked: number;
  bank_growth: number;
  total_staked: number;
  total_returned: number;
  signals_available: number;
  signals_started: number;
  signals_completed: number;
  winning_signals: number;
  losing_signals: number;
  unplayed_signals: number;
  exact_hits_by_attempt: Array<{ attempt: number; hits: number }>;
  max_drawdown: number;
  max_drawdown_rate: number;
  bankroll_insufficient: boolean;
  bankroll_stop: { signal: number; attempt: number } | null;
  chart: {
    points: ProfitChartPoint[];
    points_total: number;
    points_capped: boolean;
  };
}

interface ProfitabilityRoulette {
  roulette_id: string;
  name: string;
  strategies: ProfitabilityStrategy[];
}

interface ProfitabilityPayload {
  engine_version: string;
  window: WindowKey;
  initial_bank: number;
  attempt_stakes: number[];
  calculation_scope: 'per_roulette';
  roulettes: ProfitabilityRoulette[];
  generated_at: string;
  error?: string;
}

const WINDOWS: Array<{ key: WindowKey; label: string }> = [
  { key: '1h', label: '1 hora' },
  { key: '3h', label: '3 horas' },
  { key: '6h', label: '6 horas' },
  { key: '12h', label: '12 horas' },
  { key: '24h', label: '24 horas' },
  { key: 'all', label: 'Geral' },
];

const RED = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);

function pct(value: number | undefined): string {
  return `${((value ?? 0) * 100).toFixed(1).replace('.', ',')}%`;
}

function money(value: number | undefined): string {
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
  }).format(value ?? 0);
}

function time(value: string | null | undefined): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value));
}

function dateTime(value: string | null | undefined): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value));
}

function NumberBall({ number, small = false }: { number: number; small?: boolean }) {
  const tone = number === 0 ? styles.greenBall : RED.has(number) ? styles.redBall : styles.blackBall;
  return <span className={`${styles.ball} ${tone} ${small ? styles.smallBall : ''}`}>{number}</span>;
}

function WindowFilter({ value, onChange }: { value: WindowKey; onChange: (key: WindowKey) => void }) {
  return (
    <div className={styles.windowFilter}>
      <span>Período das estatísticas</span>
      <div>
        {WINDOWS.map((window) => (
          <button
            className={value === window.key ? styles.activeWindow : ''}
            key={window.key}
            onClick={() => onChange(window.key)}
            type="button"
          >
            {window.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function AttemptCurve({ performance, windowKey }: { performance: TriggerPerformance; windowKey: WindowKey }) {
  const selected = performance.windows?.[windowKey];
  const attempts = selected?.entry?.attempts ?? [];
  const maxAttempts = Math.max(1, performance.max_attempts ?? attempts.length);
  return (
    <div className={styles.curve}>
      <div className={styles.curveHead}>
        <span>Acertos por tentativa</span>
        <small>n = {selected?.sample_size ?? 0}</small>
      </div>
      <div className={styles.curveGrid}>
        {Array.from({ length: maxAttempts }, (_, index) => {
          const row = attempts[index];
          return (
            <div key={index}>
              <span>{index + 1}ª</span>
              <strong>{row?.exact_hits ?? 0} sinais</strong>
              <small>{pct(row?.exact_hit_rate)} nesta</small>
              <small>acum. {pct(row?.hit_rate)}</small>
              <small>base {pct(row?.random_baseline)}</small>
            </div>
          );
        })}
      </div>
      <div className={styles.coverageLine}>
        <span>Sem acerto: <b>{selected?.entry?.misses_after_max_attempts ?? 0} sinais</b></span>
        <span>Cobertura média: <b>{selected?.entry?.average_target_size?.toFixed(1).replace('.', ',') ?? '0'} números</b></span>
      </div>
    </div>
  );
}

function ProfitChart({ strategy, rouletteName }: { strategy: ProfitabilityStrategy; rouletteName: string }) {
  const points = strategy.chart.points;
  const width = 620;
  const height = 190;
  const paddingX = 30;
  const paddingY = 22;
  if (points.length < 2) {
    return <div className={styles.emptyChart}>Sem sinais encerrados neste período.</div>;
  }
  const banks = points.map((point) => point.bank);
  let minimum = Math.min(...banks, strategy.initial_bank);
  let maximum = Math.max(...banks, strategy.initial_bank);
  if (minimum === maximum) {
    minimum -= 1;
    maximum += 1;
  }
  const x = (index: number) => paddingX + (index / (points.length - 1)) * (width - paddingX * 2);
  const y = (value: number) => paddingY + ((maximum - value) / (maximum - minimum)) * (height - paddingY * 2);
  const line = points.map((point, index) => `${x(index)},${y(point.bank)}`).join(' ');
  const baselineY = y(strategy.initial_bank);
  const positive = strategy.net_profit >= 0;
  return (
    <div className={styles.profitChartWrap}>
      <svg
        aria-label={`Evolução da banca do ${strategy.name} na ${rouletteName}, de ${money(strategy.initial_bank)} para ${money(strategy.final_bank)}`}
        className={styles.profitChart}
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <title>Evolução da banca — {strategy.name} — {rouletteName}</title>
        <desc>Saldo exclusivo desta roleta após cada sinal histórico encerrado no período selecionado.</desc>
        {[0, 1, 2, 3].map((row) => {
          const gridY = paddingY + (row / 3) * (height - paddingY * 2);
          return <line className={styles.chartGridLine} key={row} x1={paddingX} x2={width - paddingX} y1={gridY} y2={gridY} />;
        })}
        <line className={styles.chartBaseline} x1={paddingX} x2={width - paddingX} y1={baselineY} y2={baselineY} />
        <polyline className={positive ? styles.chartPositive : styles.chartNegative} fill="none" points={line} />
        <circle
          className={positive ? styles.chartPointPositive : styles.chartPointNegative}
          cx={x(points.length - 1)}
          cy={y(points[points.length - 1].bank)}
          r="4"
        />
        <text className={styles.chartLabel} x={paddingX} y={height - 2}>0</text>
        <text className={styles.chartLabel} textAnchor="end" x={width - paddingX} y={height - 2}>
          {points[points.length - 1].signal} sinais
        </text>
        <text className={styles.chartValue} x={paddingX} y={14}>{money(maximum)}</text>
        <text className={styles.chartValue} x={paddingX} y={height - 17}>{money(minimum)}</text>
      </svg>
    </div>
  );
}

function ProfitabilityCard({ strategy, rouletteName }: { strategy: ProfitabilityStrategy; rouletteName: string }) {
  const positive = strategy.net_profit >= 0;
  return (
    <article className={styles.profitCard}>
      <header>
        <div>
          <span>{rouletteName} · simulação histórica</span>
          <h3>{strategy.short_name}</h3>
        </div>
        <strong className={positive ? styles.positiveMoney : styles.negativeMoney}>
          {money(strategy.net_profit)}
        </strong>
      </header>
      <div className={styles.profitStats}>
        <span><small>Banca final</small><strong>{money(strategy.final_bank)}</strong></span>
        <span><small>ROI investido</small><strong>{pct(strategy.roi_on_staked)}</strong></span>
        <span><small>Investido</small><strong>{money(strategy.total_staked)}</strong></span>
        <span><small>Retornado</small><strong>{money(strategy.total_returned)}</strong></span>
        <span><small>Green / loss</small><strong>{strategy.winning_signals} / {strategy.losing_signals}</strong></span>
        <span><small>Queda máxima</small><strong>{money(strategy.max_drawdown)}</strong></span>
      </div>
      <div className={styles.profitAttempts}>
        {strategy.exact_hits_by_attempt.map((row) => (
          <span key={row.attempt}><small>{row.attempt}ª</small><strong>{row.hits}</strong></span>
        ))}
      </div>
      <ProfitChart rouletteName={rouletteName} strategy={strategy} />
      <footer>
        <span>{strategy.signals_completed} de {strategy.signals_available} sinais simulados</span>
        {strategy.bankroll_insufficient && strategy.bankroll_stop ? (
          <b>Banca insuficiente no sinal {strategy.bankroll_stop.signal}, {strategy.bankroll_stop.attempt}ª tentativa</b>
        ) : strategy.records_capped ? <b>Limite de registros aplicado</b> : null}
      </footer>
    </article>
  );
}

function ProfitabilityCalculator({
  slug,
  windowKey,
  maxAttempts = 5,
}: {
  slug?: string;
  windowKey: WindowKey;
  maxAttempts?: number;
}) {
  const [initialBank, setInitialBank] = useState('1000');
  const [stakes, setStakes] = useState([
    '1',
    '2',
    '4',
    '8',
    '16',
    '32',
    '64',
    '128',
    '256',
    '512',
  ]);
  const [result, setResult] = useState<ProfitabilityPayload | null>(null);
  const [selectedRouletteId, setSelectedRouletteId] = useState('');
  const [calculating, setCalculating] = useState(false);
  const [calculatorError, setCalculatorError] = useState<string | null>(null);

  const parseMoney = (value: string) => Number(value.trim().replace(',', '.'));
  const selectedRoulette = result?.roulettes.find(
    (roulette) => roulette.roulette_id === selectedRouletteId,
  ) ?? result?.roulettes[0];

  async function calculate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const bank = parseMoney(initialBank);
    const parsedStakes = stakes.map(parseMoney);
    if (
      !Number.isFinite(bank)
      || bank <= 0
      || parsedStakes.some((value) => (
        !Number.isFinite(value) || value < 0 || !Number.isInteger(value)
      ))
    ) {
      setCalculatorError(
        `Informe uma banca positiva e ${maxAttempts} fichas inteiras maiores ou iguais a zero.`,
      );
      return;
    }
    setCalculating(true);
    try {
      const response = await fetch('/api/orbit-triggers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          initial_bank: bank,
          attempt_stakes: parsedStakes,
          window: windowKey,
          strategy_slugs: slug ? [slug] : undefined,
        }),
      });
      const payload = (await response.json()) as ProfitabilityPayload;
      if (!response.ok) throw new Error(payload.error ?? 'Falha ao calcular lucratividade.');
      setResult(payload);
      setSelectedRouletteId((current) => (
        payload.roulettes.some((roulette) => roulette.roulette_id === current)
          ? current
          : (payload.roulettes[0]?.roulette_id ?? '')
      ));
      setCalculatorError(null);
    } catch (reason) {
      setCalculatorError(reason instanceof Error ? reason.message : 'Falha ao calcular lucratividade.');
    } finally {
      setCalculating(false);
    }
  }

  return (
    <section className={styles.calculatorSection}>
      <div className={styles.calculatorHead}>
        <div>
          <span>Simulador financeiro</span>
          <h2>Assertividade e lucratividade por roleta</h2>
          <p>
            Cada valor é a ficha inteira aplicada em cada número protegido. O custo da
            tentativa é a ficha multiplicada pela cobertura.
            {maxAttempts !== 5
              ? ` Esta estratégia encerra em ${maxAttempts} tentativas.`
              : ''}
          </p>
        </div>
        <small>Pagamento bruto: 36× a ficha do número acertado</small>
      </div>
      <form
        className={`${styles.calculatorForm} ${
          maxAttempts === 10 ? styles.tenAttemptCalculatorForm : ''
        }`}
        onSubmit={calculate}
      >
        <label>
          <span>Banca inicial</span>
          <input inputMode="decimal" onChange={(event) => setInitialBank(event.target.value)} value={initialBank} />
        </label>
        {stakes.slice(0, maxAttempts).map((stake, index) => (
          <label key={index}>
            <span>{index + 1}ª tentativa · ficha por número</span>
            <input
              inputMode="numeric"
              min="0"
              onChange={(event) => setStakes((current) => current.map((value, position) => position === index ? event.target.value : value))}
              step="1"
              type="number"
              value={stake}
            />
          </label>
        ))}
        <button disabled={calculating} type="submit">
          {calculating ? 'Calculando…' : 'Calcular lucratividade'}
        </button>
      </form>
      {calculatorError ? <div className={styles.calculatorError}>{calculatorError}</div> : null}
      {result && result.roulettes.length ? (
        <div className={styles.profitResults}>
          <div className={styles.profitRouletteBar}>
            <div className={styles.profitRouletteIdentity}>
              <span>Resultado isolado por mesa</span>
              <strong>{selectedRoulette?.name}</strong>
              <small>A banca inicial é reiniciada para cada roleta.</small>
            </div>
            <div aria-label="Roleta da simulação" className={styles.profitRouletteTabs} role="group">
              {result.roulettes.map((roulette) => (
                <button
                  aria-pressed={roulette.roulette_id === selectedRouletteId}
                  className={roulette.roulette_id === selectedRouletteId ? styles.activeProfitRoulette : ''}
                  key={roulette.roulette_id}
                  onClick={() => setSelectedRouletteId(roulette.roulette_id)}
                  type="button"
                >
                  {roulette.name}
                </button>
              ))}
            </div>
          </div>
          <div className={styles.profitGrid}>
            {selectedRoulette?.strategies.map((strategy) => (
              <ProfitabilityCard
                key={strategy.slug}
                rouletteName={selectedRoulette.name}
                strategy={strategy}
              />
            ))}
          </div>
        </div>
      ) : (
        <div className={styles.calculatorHint}>Configure os valores e calcule separadamente os sinais encerrados de cada roleta.</div>
      )}
    </section>
  );
}

function StatusCounts({ performance }: { performance: TriggerPerformance }) {
  return (
    <div className={styles.statusCounts}>
      <span><strong>{performance.total_trials}</strong> entradas</span>
      <span><strong>{performance.pending_trials}</strong> acompanhando</span>
      <span><strong>{performance.active_candidates}</strong> gatilhos armados</span>
    </div>
  );
}

function CatalogView({ data, windowKey }: { data: CatalogPayload; windowKey: WindowKey }) {
  return (
    <div className={styles.strategyGrid}>
      {data.strategies.map((strategy, index) => (
        <article className={styles.strategyCard} key={strategy.slug}>
          <div className={styles.strategyHead}>
            <span>Modelo {String(index + 1).padStart(2, '0')}</span>
            <small>{strategy.max_attempts} tentativas</small>
          </div>
          <h2>{strategy.short_name}</h2>
          <p>{strategy.summary}</p>
          <StatusCounts performance={strategy.performance} />
          <AttemptCurve performance={strategy.performance} windowKey={windowKey} />
          <div className={styles.rulePreview}>
            <span>Entrada</span>
            <p>{strategy.entry_rule}</p>
          </div>
          <Link className={styles.detailLink} href={`/orbit/triggers/${strategy.slug}`}>
            Abrir página da estratégia
          </Link>
        </article>
      ))}
    </div>
  );
}

function outcomeLabel(trial: TriggerTrial): string {
  if (trial.outcome.status === 'hit') return `Green na ${trial.outcome.first_hit_attempt}ª`;
  if (trial.outcome.status === 'miss') return `Não bateu em ${trial.max_attempts}`;
  return `${trial.attempts_observed}/${trial.max_attempts} observado`;
}

function NumberSet({ label, numbers }: { label: string; numbers: number[] }) {
  return (
    <div className={styles.numberSet}>
      <span>{label}</span>
      <div>{numbers.map((number, index) => <NumberBall key={`${number}-${index}`} number={number} small />)}</div>
    </div>
  );
}

function TrialHistory({ trials }: { trials: TriggerTrial[] }) {
  if (!trials.length) {
    return <div className={styles.empty}>As primeiras entradas aparecerão após o gatilho ocorrer.</div>;
  }
  return (
    <div className={styles.history}>
      <span className={styles.sectionLabel}>Últimas entradas</span>
      {trials.map((trial) => (
        <details key={trial.event_id}>
          <summary>
            <span className={`${styles.outcomeDot} ${styles[trial.display_status]}`} />
            {trial.activation_number !== null ? <NumberBall number={trial.activation_number} small /> : null}
            <span>
              <strong>{dateTime(trial.activation_timestamp_utc)}</strong>
              <small>{trial.target_size} números protegidos</small>
            </span>
            <b>{outcomeLabel(trial)}</b>
          </summary>
          <div className={styles.historyDetail}>
            <NumberSet label="Pivôs no gatilho" numbers={trial.recent_pivots} />
            <NumberSet label="Centros da regra" numbers={trial.base_numbers} />
            <NumberSet label="Entrada congelada" numbers={trial.entry_numbers} />
            <div className={styles.attempts}>
              <span>Resultados posteriores</span>
              <div>
                {Array.from({ length: trial.max_attempts }, (_, index) => {
                  const attempt = trial.attempts[index];
                  return (
                    <div className={attempt?.match ? styles.matchAttempt : ''} key={index}>
                      <span>{index + 1}ª</span>
                      {attempt ? <NumberBall number={attempt.number} small /> : <i>—</i>}
                      <small>{time(attempt?.timestamp_utc)}</small>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </details>
      ))}
    </div>
  );
}

function DetailView({ data, windowKey }: { data: DetailPayload; windowKey: WindowKey }) {
  const overallWindow = data.overall.windows?.[windowKey];
  const maxAttempts = data.strategy.max_attempts;
  const finalAttempt = overallWindow?.entry?.attempts?.[maxAttempts - 1];
  return (
    <>
      <div className={styles.detailIdentity}>
        <div>
          <span>Estratégia em acompanhamento</span>
          <h2>{data.strategy.name}</h2>
          <p>{data.strategy.summary}</p>
        </div>
        <strong>{maxAttempts} tentativas</strong>
      </div>
      <div className={styles.ruleBoard}>
        <div>
          <span>Condição de ativação</span>
          <p>{data.strategy.activation_rule}</p>
        </div>
        <div>
          <span>Entrada congelada</span>
          <p>{data.strategy.entry_rule}</p>
        </div>
        <div className={styles.overallResult}>
          <span>Até a {maxAttempts}ª</span>
          <strong>{pct(finalAttempt?.hit_rate)}</strong>
          <small>n = {overallWindow?.sample_size ?? 0}</small>
        </div>
      </div>

      <div className={styles.rouletteGrid}>
        {data.roulettes.map((roulette) => (
          <article className={styles.rouletteCard} key={roulette.roulette_id}>
            <header>
              <div>
                <span>Roleta monitorada</span>
                <h2>{roulette.name}</h2>
                <code>{roulette.roulette_id}</code>
              </div>
              <small>{maxAttempts} tentativas</small>
            </header>
            <StatusCounts performance={roulette.performance} />
            <AttemptCurve performance={roulette.performance} windowKey={windowKey} />
            {roulette.performance.best_hour ? (
              <div className={styles.bestHour}>
                <span>Melhor horário histórico</span>
                <strong>{roulette.performance.best_hour.label}</strong>
                <small>{roulette.performance.best_hour.provisional ? 'provisório' : 'validado'}</small>
              </div>
            ) : null}
            <TrialHistory trials={roulette.history} />
          </article>
        ))}
      </div>
    </>
  );
}

export default function TriggerDashboard({ slug }: { slug?: string }) {
  const [data, setData] = useState<CatalogPayload | DetailPayload | null>(null);
  const [windowKey, setWindowKey] = useState<WindowKey>('24h');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const query = slug ? `?slug=${encodeURIComponent(slug)}` : '';
      const response = await fetch(`/api/orbit-triggers${query}`, { cache: 'no-store' });
      const payload = (await response.json()) as CatalogPayload | DetailPayload;
      if (!response.ok) throw new Error(payload.error ?? 'Falha ao carregar gatilhos.');
      setData(payload);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Falha ao carregar gatilhos.');
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    const initial = window.setTimeout(load, 0);
    const interval = window.setInterval(load, 15_000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(interval);
    };
  }, [load]);

  const calculatorMaxAttempts = data && 'strategy' in data
    ? data.strategy.max_attempts
    : data && 'strategies' in data
      ? data.max_attempts
      : 5;

  return (
    <>
      <div className={styles.toolbar}>
        <span><i />{loading && !data ? 'Conectando ao monitor…' : `Monitor prospectivo · ${data?.engine_version ?? 'v1'}`}</span>
        <button disabled={loading} onClick={load} type="button">
          {loading ? 'Atualizando…' : 'Atualizar agora'}
        </button>
      </div>
      {error ? <div className={styles.error}>{error}</div> : null}
      <WindowFilter value={windowKey} onChange={setWindowKey} />
      <ProfitabilityCalculator
        key={`${slug ?? 'catalog'}-${windowKey}-${calculatorMaxAttempts}`}
        maxAttempts={calculatorMaxAttempts}
        slug={slug}
        windowKey={windowKey}
      />
      {loading && !data ? (
        <div className={styles.loadingGrid}>{[0, 1, 2].map((item) => <div key={item} />)}</div>
      ) : data && 'strategies' in data ? (
        <CatalogView data={data} windowKey={windowKey} />
      ) : data && 'strategy' in data ? (
        <DetailView data={data} windowKey={windowKey} />
      ) : null}
    </>
  );
}
