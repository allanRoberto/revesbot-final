'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from './page.module.css';

const RED = new Set([
  1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36,
]);

interface RankingRow {
  number: number;
  probability: number;
  weighted_rank_score: number;
  top9_support: number;
  top12_support: number;
  pivot_ranks: number[];
}

interface PivotRow {
  position: number;
  pivot: number;
  weight: number;
  top9: number[];
  top12: number[];
  abstained: boolean;
}

type WindowKey = '1h' | '3h' | '6h' | '12h' | '24h' | 'all';

interface AttemptMetric {
  attempt: number;
  hits: number;
  hit_rate: number;
  random_baseline: number;
  delta_percentage_points: number;
}

interface PerformanceWindow {
  sample_size: number;
  top9: { attempts: AttemptMetric[] };
  top12: { attempts: AttemptMetric[] };
}

interface PerformanceSummary {
  available: boolean;
  pending_trials: number;
  resolved_trials: number;
  windows: Record<WindowKey, PerformanceWindow>;
  best_hour: {
    label: string;
    sample_size: number;
    hit_rate: number;
    target_attempt: number;
    delta_percentage_points: number;
    provisional: boolean;
  } | null;
}

interface HistoryOutcome {
  status: 'hit' | 'miss' | 'pending';
  first_hit_attempt: number | null;
  first_hit_timestamp_utc: string | null;
}

interface HistoryAttempt {
  attempt: number;
  number: number;
  timestamp_utc: string | null;
  top9_match: boolean;
  top12_match: boolean;
  top12_only_match: boolean;
}

interface HistoryTrial {
  trial_id: string;
  anchor_timestamp_utc: string;
  anchor_number: number | null;
  recent_pivots: number[];
  top9: number[];
  top12: number[];
  attempts: HistoryAttempt[];
  attempts_observed: number;
  max_attempts: number;
  status: 'pending' | 'resolved';
  display_status: 'top9_hit' | 'top12_hit' | 'miss' | 'pending';
  top9_outcome: HistoryOutcome;
  top12_outcome: HistoryOutcome;
}

interface RouletteRow {
  available: boolean;
  roulette_id: string;
  name: string;
  anchor_timestamp_utc?: string;
  error?: string;
  performance?: PerformanceSummary | null;
  history?: HistoryTrial[];
  prediction?: {
    recent_pivots: number[];
    top9: number[];
    top12: number[];
    abstained: boolean;
    pivots: PivotRow[];
    ranking: RankingRow[];
  };
}

const WINDOW_OPTIONS: { key: WindowKey; label: string }[] = [
  { key: '1h', label: '1 hora' },
  { key: '3h', label: '3 horas' },
  { key: '6h', label: '6 horas' },
  { key: '12h', label: '12 horas' },
  { key: '24h', label: '24 horas' },
  { key: 'all', label: 'Geral' },
];

function percentage(value: number): string {
  return `${(value * 100).toFixed(1).replace('.', ',')}%`;
}

function formatTime(value?: string | null): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value));
}

function formatDateTime(value?: string | null): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value));
}

interface SuggestionsPayload {
  generated_at: string;
  pivot_count: number;
  memory_occurrences: number;
  roulettes: RouletteRow[];
  error?: string;
}

function colorClass(number: number): string {
  if (number === 0) return styles.green;
  return RED.has(number) ? styles.red : styles.black;
}

function NumberBall({
  number,
  support,
  compact = false,
}: {
  number: number;
  support?: number;
  compact?: boolean;
}) {
  return (
    <span className={`${styles.ballWrap} ${compact ? styles.compact : ''}`}>
      <span className={`${styles.ball} ${colorClass(number)}`}>{number}</span>
      {support !== undefined ? <small>{support}/3</small> : null}
    </span>
  );
}

function PerformancePanel({
  performance,
  windowKey,
}: {
  performance?: PerformanceSummary | null;
  windowKey: WindowKey;
}) {
  const selected = performance?.windows?.[windowKey];
  const sampleSize = selected?.sample_size ?? 0;
  const top12ByAttempt = new Map(
    selected?.top12?.attempts.map((attempt) => [attempt.attempt, attempt]) ?? [],
  );

  return (
    <section className={styles.performanceBlock}>
      <div className={styles.performanceHead}>
        <div>
          <span className={styles.sectionLabel}>Desempenho prospectivo</span>
          <h3>Acerto acumulado por tentativa</h3>
        </div>
        <span className={styles.sampleBadge}>n = {sampleSize}</span>
      </div>

      {sampleSize > 0 && selected ? (
        <>
          <div className={styles.metricLegend}>
            <span><i className={styles.legendTop9} /> Top 9</span>
            <span><i className={styles.legendTop12} /> Top 12</span>
          </div>
          <div className={styles.attemptGrid}>
            {selected.top9.attempts.map((top9) => {
              const top12 = top12ByAttempt.get(top9.attempt);
              return (
                <div className={styles.attemptMetric} key={top9.attempt}>
                  <span>{top9.attempt}ª</span>
                  <strong>{percentage(top9.hit_rate)}</strong>
                  <small>{top12 ? percentage(top12.hit_rate) : '—'}</small>
                </div>
              );
            })}
          </div>
        </>
      ) : (
        <div className={styles.collecting}>
          <span className={styles.pulse} />
          <div>
            <strong>Coletando janelas completas</strong>
            <small>
              {performance?.pending_trials ?? 0} previsões estão acompanhando os próximos giros.
            </small>
          </div>
        </div>
      )}

      <div className={styles.bestHour}>
        <div>
          <span>Melhor horário histórico</span>
          <strong>{performance?.best_hour?.label ?? 'Aguardando histórico'}</strong>
        </div>
        {performance?.best_hour ? (
          <small>
            Top 9 até a 3ª: {percentage(performance.best_hour.hit_rate)} · n ={' '}
            {performance.best_hour.sample_size}
            {performance.best_hour.provisional ? ' · provisório' : ''}
          </small>
        ) : (
          <small>Horário de Brasília · será calculado automaticamente</small>
        )}
      </div>
    </section>
  );
}

function historyStatus(trial: HistoryTrial): string {
  if (trial.display_status === 'top9_hit') {
    return `Top 9 · ${trial.top9_outcome.first_hit_attempt}ª`;
  }
  if (trial.display_status === 'top12_hit') {
    return `Top 12 · ${trial.top12_outcome.first_hit_attempt}ª`;
  }
  if (trial.display_status === 'miss') return 'Não bateu';
  return `${trial.attempts_observed}/${trial.max_attempts}`;
}

function OutcomeBox({ label, outcome }: { label: string; outcome: HistoryOutcome }) {
  let value = 'Aguardando próximos giros';
  if (outcome.status === 'hit') {
    value = `Bateu na ${outcome.first_hit_attempt}ª · ${formatTime(outcome.first_hit_timestamp_utc)}`;
  } else if (outcome.status === 'miss') {
    value = 'Não bateu em 10 tentativas';
  }
  return (
    <div className={`${styles.outcomeBox} ${styles[`outcome${outcome.status}`]}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function HistoryDetail({ trial }: { trial: HistoryTrial }) {
  const attempts = new Map(trial.attempts.map((attempt) => [attempt.attempt, attempt]));
  return (
    <div className={styles.historyDetail}>
      <div className={styles.historyDetailHead}>
        <div>
          <span className={styles.sectionLabel}>Previsão selecionada</span>
          <strong>{formatDateTime(trial.anchor_timestamp_utc)}</strong>
        </div>
        <span className={`${styles.historyStatus} ${styles[trial.display_status]}`}>
          {historyStatus(trial)}
        </span>
      </div>

      <div className={styles.historyPivots}>
        <span>Pivôs</span>
        <div>
          {trial.recent_pivots.map((number, index) => (
            <span key={`${number}-${index}`}>
              <NumberBall number={number} compact />
              <small>{index === 0 ? 'Último' : index === 1 ? 'Penúltimo' : 'Antepenúltimo'}</small>
            </span>
          ))}
        </div>
      </div>

      <div className={styles.historyPredictions}>
        <div>
          <span>Top 9 previsto</span>
          <div>{trial.top9.map((number) => <NumberBall number={number} compact key={number} />)}</div>
        </div>
        <div>
          <span>Top 12 previsto</span>
          <div>{trial.top12.map((number) => <NumberBall number={number} compact key={number} />)}</div>
        </div>
      </div>

      <div className={styles.historyOutcomes}>
        <OutcomeBox label="Top 9" outcome={trial.top9_outcome} />
        <OutcomeBox label="Top 12" outcome={trial.top12_outcome} />
      </div>

      <div className={styles.attemptHistory}>
        <span className={styles.sectionLabel}>Resultados após a previsão</span>
        <div>
          {Array.from({ length: trial.max_attempts }, (_, index) => {
            const position = index + 1;
            const attempt = attempts.get(position);
            const matchClass = attempt?.top9_match
              ? styles.attemptHit9
              : attempt?.top12_only_match
                ? styles.attemptHit12
                : '';
            return (
              <div className={`${styles.historyAttempt} ${matchClass}`} key={position}>
                <span>{position}ª</span>
                {attempt ? <NumberBall number={attempt.number} compact /> : <i>—</i>}
                <small>{formatTime(attempt?.timestamp_utc)}</small>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function HistoryPanel({
  items,
  selectedTrialId,
  onSelect,
}: {
  items: HistoryTrial[];
  selectedTrialId: string | null;
  onSelect: (trialId: string) => void;
}) {
  const selected = items.find((item) => item.trial_id === selectedTrialId) ?? items[0];
  if (!selected) {
    return <div className={styles.emptyHistory}>O histórico começará a aparecer nos próximos giros.</div>;
  }
  return (
    <section className={styles.historyPanel}>
      <div className={styles.historyList}>
        {items.map((trial) => (
          <button
            aria-label={`Abrir previsão do número ${trial.anchor_number ?? 'sem número'} às ${formatTime(trial.anchor_timestamp_utc)}`}
            className={selected.trial_id === trial.trial_id ? styles.selectedHistory : ''}
            key={trial.trial_id}
            onClick={() => onSelect(trial.trial_id)}
            type="button"
          >
            {trial.anchor_number !== null ? <NumberBall number={trial.anchor_number} compact /> : <i>—</i>}
            <span>{formatTime(trial.anchor_timestamp_utc)}</span>
            <small>{historyStatus(trial)}</small>
          </button>
        ))}
      </div>
      <HistoryDetail trial={selected} />
    </section>
  );
}

function RouletteCard({ row, windowKey }: { row: RouletteRow; windowKey: WindowKey }) {
  const [cardTab, setCardTab] = useState<'current' | 'history'>('current');
  const [selectedTrialId, setSelectedTrialId] = useState<string | null>(null);
  if (!row.available || !row.prediction) {
    return (
      <article className={`${styles.card} ${styles.unavailable}`}>
        <div className={styles.cardHead}>
          <div>
            <span className={styles.tableType}>Roleta</span>
            <h2>{row.name}</h2>
          </div>
        </div>
        <p>{row.error ?? 'Ainda não há histórico suficiente para esta mesa.'}</p>
      </article>
    );
  }

  const ranking = new Map(row.prediction.ranking.map((item) => [item.number, item]));
  const updated = row.anchor_timestamp_utc
    ? new Intl.DateTimeFormat('pt-BR', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }).format(new Date(row.anchor_timestamp_utc))
    : null;

  return (
    <article className={styles.card}>
      <div className={styles.cardHead}>
        <div>
          <span className={styles.tableType}>Roleta ao vivo</span>
          <h2>{row.name}</h2>
          <code>{row.roulette_id}</code>
        </div>
        <div className={styles.cardStatus}>
          <span>{row.prediction.abstained ? 'Estudo' : 'Ativo'}</span>
          {updated ? <small>giro {updated}</small> : null}
        </div>
      </div>

      <div className={styles.cardTabs} role="tablist" aria-label={`Conteúdo de ${row.name}`}>
        <button
          aria-selected={cardTab === 'current'}
          className={cardTab === 'current' ? styles.activeCardTab : ''}
          onClick={() => setCardTab('current')}
          role="tab"
          type="button"
        >
          Atual
        </button>
        <button
          aria-selected={cardTab === 'history'}
          className={cardTab === 'history' ? styles.activeCardTab : ''}
          onClick={() => setCardTab('history')}
          role="tab"
          type="button"
        >
          Histórico <span>{row.history?.length ?? 0}</span>
        </button>
      </div>

      {cardTab === 'current' ? <>
        <section className={styles.pivotSection}>
        <span className={styles.sectionLabel}>Pivôs recentes</span>
        <div className={styles.pivots}>
          {row.prediction.pivots.map((pivot) => (
            <div className={styles.pivot} key={`${pivot.position}-${pivot.pivot}`}>
              <NumberBall number={pivot.pivot} compact />
              <span>
                {pivot.position === 0
                  ? 'Último'
                  : pivot.position === 1
                    ? 'Penúltimo'
                    : 'Antepenúltimo'}
              </span>
              <small>peso {pivot.weight.toFixed(2).replace('.', ',')}</small>
            </div>
          ))}
        </div>
        </section>

        <section className={styles.suggestionBlock}>
        <div className={styles.blockTitle}>
          <div>
            <span className={styles.sectionLabel}>Sugestão principal</span>
            <h3>Top 9</h3>
          </div>
          <span className={styles.consensus}>consenso dos 3 rankings</span>
        </div>
        <div className={styles.numberGrid}>
          {row.prediction.top9.map((number) => (
            <NumberBall
              key={number}
              number={number}
              support={ranking.get(number)?.top9_support ?? 0}
            />
          ))}
        </div>
        </section>

        <section className={`${styles.suggestionBlock} ${styles.secondary}`}>
        <div className={styles.blockTitle}>
          <div>
            <span className={styles.sectionLabel}>Cobertura ampliada</span>
            <h3>Top 12</h3>
          </div>
          <span className={styles.consensus}>+3 alternativas</span>
        </div>
        <div className={`${styles.numberGrid} ${styles.twelve}`}>
          {row.prediction.top12.map((number, index) => (
            <span className={index >= 9 ? styles.extra : ''} key={number}>
              <NumberBall
                number={number}
                support={ranking.get(number)?.top12_support ?? 0}
                compact
              />
            </span>
          ))}
        </div>
        </section>

        <PerformancePanel performance={row.performance} windowKey={windowKey} />
      </> : (
        <HistoryPanel
          items={row.history ?? []}
          selectedTrialId={selectedTrialId}
          onSelect={setSelectedTrialId}
        />
      )}

      <footer className={styles.cardFooter}>
        Ranking observacional · sem exclusões · 6 ocorrências por pivô
      </footer>
    </article>
  );
}

export default function OrbitDashboard() {
  const [data, setData] = useState<SuggestionsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [windowKey, setWindowKey] = useState<WindowKey>('24h');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/orbit-suggestions', { cache: 'no-store' });
      const payload = (await response.json()) as SuggestionsPayload;
      if (!response.ok) throw new Error(payload.error ?? 'Falha ao carregar sugestões.');
      setData(payload);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Falha ao carregar sugestões.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(load, 0);
    const interval = window.setInterval(load, 15_000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(interval);
    };
  }, [load]);

  const generatedAt = data?.generated_at
    ? new Intl.DateTimeFormat('pt-BR', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }).format(new Date(data.generated_at))
    : null;

  return (
    <>
      <div className={styles.toolbar}>
        <div>
          <span className={styles.pulse} />
          {loading && !data
            ? 'Calculando três órbitas por mesa…'
            : generatedAt
              ? `Atualizado às ${generatedAt}`
              : 'Aguardando atualização'}
        </div>
        <button type="button" onClick={load} disabled={loading}>
          {loading ? 'Atualizando…' : 'Atualizar agora'}
        </button>
      </div>

      {error ? <div className={styles.error}>{error}</div> : null}

      <div className={styles.windowFilter}>
        <span>Período das estatísticas</span>
        <div>
          {WINDOW_OPTIONS.map((option) => (
            <button
              className={windowKey === option.key ? styles.activeWindow : ''}
              key={option.key}
              onClick={() => setWindowKey(option.key)}
              type="button"
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {loading && !data ? (
        <div className={styles.skeletonGrid} aria-label="Carregando sugestões">
          {[0, 1, 2].map((item) => <div className={styles.skeleton} key={item} />)}
        </div>
      ) : (
        <div className={styles.cards}>
          {data?.roulettes.map((row) => (
            <RouletteCard row={row} windowKey={windowKey} key={row.roulette_id} />
          ))}
        </div>
      )}
    </>
  );
}
