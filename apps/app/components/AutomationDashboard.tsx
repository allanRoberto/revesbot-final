'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { formatBRL } from '@/lib/format';

type RunStatus =
  | 'starting'
  | 'waiting_signal'
  | 'running'
  | 'payment_due'
  | 'completed'
  | 'error';

interface AutomationRun {
  runId: string;
  status: RunStatus;
  bankrollStartCents: number;
  targetProfitCents: number;
  maxLossCents: number;
  netProfitCents: number;
  roundsSettled: number;
  startedAt: string;
  expiresAt?: string;
  stopReason?: string;
}

interface AutomationEntry {
  roundId: string;
  signalId?: string;
  house?: string;
  rouletteId?: string;
  betsCents: Record<string, number>;
  totalStakeCents: number;
  winningNumber: number;
  payoutCents: number;
  netProfitCents: number;
  settledAt: string;
}

interface AutomationInvoice {
  invoiceId: string;
  type: 'activation' | 'commission';
  description: string;
  amountCents: number;
  status: 'pending' | 'awaiting_payment' | 'paid' | 'canceled';
  netProfitCents?: number;
  criadoEm: string;
  paidAt?: string;
}

interface StatusPayload {
  run: AutomationRun | null;
  entries: AutomationEntry[];
  invoices: AutomationInvoice[];
  activated: boolean;
  connection: {
    house: string;
    houseName: string;
    connected: boolean;
    balanceCents: number | null;
  };
  signalSourceConnected: boolean;
  policy: {
    commissionBps: number;
    targetRateBps: number;
  };
}

function invoiceStatus(status: AutomationInvoice['status']): string {
  if (status === 'paid') return 'Paga';
  if (status === 'awaiting_payment') return 'PIX gerado';
  if (status === 'canceled') return 'Cancelada';
  return 'Pendente';
}

function runStatus(run: AutomationRun | null): string {
  if (!run) return 'Desligado';
  if (run.status === 'waiting_signal') return 'Aguardando sinal';
  if (run.status === 'running') return 'Executando entrada';
  if (run.status === 'starting') return 'Iniciando';
  if (run.status === 'payment_due') return 'Aguardando pagamento';
  if (run.status === 'error') return 'Pausado por erro';
  return 'Finalizado';
}

function remainingLabel(expiresAt?: string): string {
  if (!expiresAt) return '24:00:00';
  const seconds = Math.max(
    0,
    Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000),
  );
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return [hours, minutes, rest].map((part) => String(part).padStart(2, '0')).join(':');
}

function BalanceProjection({
  run,
  entries,
}: {
  run: AutomationRun | null;
  entries: AutomationEntry[];
}) {
  const points = useMemo(() => {
    const chronological = [...entries].reverse();
    const initialBalance = run?.bankrollStartCents ?? 0;
    return chronological.reduce<number[]>(
      (values, entry) => [
        ...values,
        (values.at(-1) ?? initialBalance) + entry.netProfitCents,
      ],
      [initialBalance],
    );
  }, [entries, run]);

  const start = run?.bankrollStartCents ?? 0;
  const green = start + (run?.targetProfitCents ?? 0);
  const loss = start - (run?.maxLossCents ?? 0);
  const current = points.at(-1) ?? start;
  const projected =
    points.length > 1 ? current + (current - start) * Math.max(1, 8 - points.length) : current;
  const all = [...points, green, loss, projected];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = Math.max(1, max - min);
  const x = (index: number, total: number) =>
    total <= 1 ? 28 : 28 + (index / (total - 1)) * 704;
  const y = (value: number) => 190 - ((value - min) / span) * 154;
  const actualPath = points
    .map((value, index) => `${index ? 'L' : 'M'} ${x(index, points.length)} ${y(value)}`)
    .join(' ');

  return (
    <div className="automation-chart">
      <div className="automation-section-head">
        <div>
          <h2>Projeção de saldo</h2>
          <p>Evolução exclusiva das entradas automáticas.</p>
        </div>
        <span>Projeção não garante resultado</span>
      </div>
      <svg viewBox="0 0 760 220" role="img" aria-label="Gráfico de projeção do saldo">
        <line x1="28" x2="732" y1={y(green)} y2={y(green)} className="chart-green" />
        <line x1="28" x2="732" y1={y(loss)} y2={y(loss)} className="chart-loss" />
        <path d={actualPath} className="chart-actual" />
        <line
          x1={x(points.length - 1, points.length)}
          y1={y(current)}
          x2="732"
          y2={y(projected)}
          className="chart-projection"
        />
        <text x="32" y={Math.max(14, y(green) - 7)} className="chart-label green">
          Stop Green {formatBRL(run?.targetProfitCents ?? 0)}
        </text>
        <text x="32" y={Math.min(214, y(loss) + 15)} className="chart-label loss">
          Stop Loss {formatBRL(run?.maxLossCents ?? 0)}
        </text>
      </svg>
    </div>
  );
}

export default function AutomationDashboard() {
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [stopLoss, setStopLoss] = useState('');
  const [riskAccepted, setRiskAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [payerName, setPayerName] = useState('');
  const [payerCpf, setPayerCpf] = useState('');
  const [payerPhone, setPayerPhone] = useState('');
  const [disclosureAccepted, setDisclosureAccepted] = useState(false);
  const [checkoutInvoice, setCheckoutInvoice] = useState<string | null>(null);
  const [pixQr, setPixQr] = useState<string | null>(null);
  const [pixCode, setPixCode] = useState<string | null>(null);
  const [, tick] = useState(0);

  const refresh = useCallback(async () => {
    const response = await fetch('/api/automation/status', { cache: 'no-store' });
    if (!response.ok) return;
    const payload = (await response.json()) as StatusPayload;
    setStatus(payload);
    if (payload.connection.balanceCents) {
      setStopLoss((current) =>
        current || ((payload.connection.balanceCents! * 0.2) / 100).toFixed(2),
      );
    }
  }, []);

  useEffect(() => {
    const initial = setTimeout(() => void refresh(), 0);
    const poll = setInterval(() => void refresh(), 5000);
    const clock = setInterval(() => tick((value) => value + 1), 1000);
    return () => {
      clearTimeout(initial);
      clearInterval(poll);
      clearInterval(clock);
    };
  }, [refresh]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const cents = Math.round(Number(stopLoss.replace(',', '.')) * 100);
      const response = await fetch('/api/automation/start', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ stopLossCents: cents }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Não foi possível ligar.');
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Não foi possível ligar.');
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch('/api/automation/stop', { method: 'POST' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Não foi possível parar.');
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Não foi possível parar.');
    } finally {
      setBusy(false);
    }
  }

  async function generatePix(invoiceId: string) {
    setBusy(true);
    setError(null);
    setPixQr(null);
    setPixCode(null);
    try {
      const response = await fetch(`/api/billing/invoices/${invoiceId}/checkout`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          name: payerName,
          cpf: payerCpf,
          phone: payerPhone,
          disclosureAccepted,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Não foi possível gerar o PIX.');
      setCheckoutInvoice(invoiceId);
      setPixQr(payload.pixQr || payload.order?.qrImageUrl || null);
      setPixCode(payload.order?.qrCode || null);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Não foi possível gerar o PIX.');
    } finally {
      setBusy(false);
    }
  }

  const run = status?.run ?? null;
  const active = Boolean(
    run && ['starting', 'waiting_signal', 'running'].includes(run.status),
  );
  const balance = status?.connection.balanceCents ?? null;
  const suggestedGreen =
    balance == null || !status
      ? null
      : Math.round((balance * status.policy.targetRateBps) / 10_000);
  const pendingInvoices =
    status?.invoices.filter((invoice) =>
      ['pending', 'awaiting_payment'].includes(invoice.status),
    ) ?? [];

  return (
    <main className="automation-main">
      <section className="automation-hero">
        <div>
          <span className="automation-eyebrow">CENTRAL DO AUTOMÁTICO</span>
          <h1>Configure o risco. O bot cuida das entradas.</h1>
          <p>
            A central de sinais escolherá a mesa e somente as apostas feitas pelo bot
            serão contabilizadas.
          </p>
        </div>
        <div className={`automation-state${active ? ' on' : ''}`}>
          <span />
          {runStatus(run)}
        </div>
      </section>

      <section className="automation-summary-grid">
        <article className="automation-summary-card">
          <span>Casa conectada</span>
          <strong>{status?.connection.houseName ?? '—'}</strong>
          <small>{status?.connection.connected ? 'Sessão disponível' : 'Reconecte sua conta'}</small>
        </article>
        <article className="automation-summary-card">
          <span>Saldo atual</span>
          <strong>{balance == null ? '—' : formatBRL(balance)}</strong>
          <small>Banca usada para sugerir a meta</small>
        </article>
        <article className="automation-summary-card">
          <span>Stop Green sugerido</span>
          <strong>{suggestedGreen == null ? '—' : formatBRL(suggestedGreen)}</strong>
          <small>10% da banca atual</small>
        </article>
        <article className="automation-summary-card">
          <span>Tempo restante</span>
          <strong>{remainingLabel(active ? run?.expiresAt : undefined)}</strong>
          <small>O ciclo encerra em até 24 horas</small>
        </article>
      </section>

      <section className="automation-control-card">
        <div className="automation-control-copy">
          <span>CONTROLE DE RISCO</span>
          <h2>{active ? 'Bot ligado' : 'Pronto para configurar'}</h2>
          <p>
            Comissão de 50% somente sobre o lucro líquido das entradas automáticas.
          </p>
        </div>
        <div className="automation-control-form">
          {active ? (
            <>
              <div className="automation-live-metrics">
                <span>
                  Lucro do bot <b>{formatBRL(run?.netProfitCents ?? 0)}</b>
                </span>
                <span>
                  Entradas <b>{run?.roundsSettled ?? 0}</b>
                </span>
                <span>
                  Stop Loss <b>{formatBRL(run?.maxLossCents ?? 0)}</b>
                </span>
              </div>
              <button className="automation-stop-button" onClick={stop} disabled={busy}>
                {busy ? 'Parando…' : 'Parar com segurança'}
              </button>
            </>
          ) : (
            <>
              <label className="automation-field">
                <span>Stop Loss</span>
                <div>
                  <b>R$</b>
                  <input
                    type="number"
                    min="1"
                    step="0.01"
                    value={stopLoss}
                    onChange={(event) => setStopLoss(event.target.value)}
                    placeholder="0,00"
                  />
                </div>
              </label>
              <label className="automation-risk-check">
                <input
                  type="checkbox"
                  checked={riskAccepted}
                  onChange={(event) => setRiskAccepted(event.target.checked)}
                />
                <span>
                  Autorizo o bot a realizar apostas e compreendo o risco de perda.
                </span>
              </label>
              <button
                className="automation-play-button"
                onClick={start}
                disabled={
                  busy ||
                  !riskAccepted ||
                  !status?.activated ||
                  !status?.connection.connected ||
                  !stopLoss
                }
              >
                <span>▶</span>
                {busy ? 'Preparando…' : 'Ligar automático'}
              </button>
              {!status?.activated && (
                <small className="automation-locked">
                  Pague a fatura de ativação para liberar o botão.
                </small>
              )}
            </>
          )}
        </div>
      </section>

      <BalanceProjection run={run} entries={status?.entries ?? []} />

      <section className="automation-table-card">
        <div className="automation-section-head">
          <div>
            <h2>Entradas automáticas</h2>
            <p>Apostas manuais não aparecem e não entram no cálculo.</p>
          </div>
        </div>
        <div className="automation-table-wrap">
          <table>
            <thead>
              <tr>
                <th>Horário</th>
                <th>Casa</th>
                <th>Mesa</th>
                <th>Números</th>
                <th>Apostado</th>
                <th>Resultado</th>
                <th>Lucro/Prejuízo</th>
              </tr>
            </thead>
            <tbody>
              {status?.entries.length ? (
                status.entries.map((entry) => (
                  <tr key={`${entry.roundId}-${entry.signalId ?? ''}`}>
                    <td>{new Date(entry.settledAt).toLocaleString('pt-BR')}</td>
                    <td>{entry.house ?? status.connection.houseName}</td>
                    <td>{entry.rouletteId ?? '—'}</td>
                    <td>{Object.keys(entry.betsCents).join(', ')}</td>
                    <td>{formatBRL(entry.totalStakeCents)}</td>
                    <td>{entry.winningNumber}</td>
                    <td className={entry.netProfitCents >= 0 ? 'positive' : 'negative'}>
                      {formatBRL(entry.netProfitCents)}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} className="automation-empty">
                    Nenhuma entrada automática registrada.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="automation-invoices-card">
        <div className="automation-section-head">
          <div>
            <h2>Faturas</h2>
            <p>As faturas pertencem à RevesBot. A PixGo processa apenas o PIX.</p>
          </div>
          <span>{pendingInvoices.length} pendente(s)</span>
        </div>

        <div className="automation-invoice-list">
          {status?.invoices.map((invoice) => (
            <article key={invoice.invoiceId} className="automation-invoice-row">
              <div>
                <strong>{invoice.description}</strong>
                <span>{new Date(invoice.criadoEm).toLocaleDateString('pt-BR')}</span>
              </div>
              <b>{formatBRL(invoice.amountCents)}</b>
              <span className={`invoice-status ${invoice.status}`}>
                {invoiceStatus(invoice.status)}
              </span>
              {invoice.status !== 'paid' && invoice.status !== 'canceled' ? (
                <button
                  onClick={() => setCheckoutInvoice(invoice.invoiceId)}
                  disabled={busy}
                >
                  Pagar com PIX
                </button>
              ) : (
                <span className="invoice-paid-date">
                  {invoice.paidAt
                    ? new Date(invoice.paidAt).toLocaleDateString('pt-BR')
                    : '—'}
                </span>
              )}
            </article>
          ))}
        </div>

        {checkoutInvoice && (
          <div className="automation-checkout">
            <input
              value={payerName}
              onChange={(event) => setPayerName(event.target.value)}
              placeholder="Nome completo do pagador"
            />
            <input
              value={payerCpf}
              onChange={(event) => setPayerCpf(event.target.value)}
              placeholder="CPF/CNPJ"
              inputMode="numeric"
            />
            <input
              value={payerPhone}
              onChange={(event) => setPayerPhone(event.target.value)}
              placeholder="Telefone com DDD (opcional)"
              inputMode="tel"
            />
            <label>
              <input
                type="checkbox"
                checked={disclosureAccepted}
                onChange={(event) => setDisclosureAccepted(event.target.checked)}
              />
              <span>
                Estou ciente do processamento do pagamento PIX pela PixGo/DEPIX.
              </span>
            </label>
            <button
              onClick={() => generatePix(checkoutInvoice)}
              disabled={busy || !disclosureAccepted}
            >
              {busy ? 'Gerando…' : 'Gerar PIX de pagamento'}
            </button>
            {pixQr && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={pixQr} alt="QR Code PIX" />
            )}
            {pixCode && (
              <button
                className="pix-copy"
                onClick={() => void navigator.clipboard?.writeText(pixCode)}
              >
                Copiar código PIX
              </button>
            )}
          </div>
        )}
      </section>

      {error && <div className="automation-page-error">{error}</div>}
    </main>
  );
}
