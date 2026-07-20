'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import styles from './triggers.module.css';

type WindowKey = '1h' | '3h' | '6h' | '12h' | '24h' | 'all';
type OutcomeStatus = 'hit' | 'miss' | 'pending';

interface AttemptMetric {
  attempt: number;
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
  return (
    <div className={styles.curve}>
      <div className={styles.curveHead}>
        <span>Acerto acumulado</span>
        <small>n = {selected?.sample_size ?? 0}</small>
      </div>
      <div className={styles.curveGrid}>
        {Array.from({ length: 5 }, (_, index) => {
          const row = attempts[index];
          return (
            <div key={index}>
              <span>{index + 1}ª</span>
              <strong>{pct(row?.hit_rate)}</strong>
              <small>base {pct(row?.random_baseline)}</small>
            </div>
          );
        })}
      </div>
      <div className={styles.coverageLine}>
        <span>Cobertura média</span>
        <strong>{selected?.entry?.average_target_size?.toFixed(1).replace('.', ',') ?? '0'} números</strong>
      </div>
    </div>
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
  if (trial.outcome.status === 'miss') return 'Não bateu em 5';
  return `${trial.attempts_observed}/5 observado`;
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
                {Array.from({ length: 5 }, (_, index) => {
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
  const fifth = overallWindow?.entry?.attempts?.[4];
  return (
    <>
      <div className={styles.detailIdentity}>
        <div>
          <span>Estratégia em acompanhamento</span>
          <h2>{data.strategy.name}</h2>
          <p>{data.strategy.summary}</p>
        </div>
        <strong>5 tentativas</strong>
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
          <span>Até a 5ª</span>
          <strong>{pct(fifth?.hit_rate)}</strong>
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
              <small>5 tentativas</small>
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
