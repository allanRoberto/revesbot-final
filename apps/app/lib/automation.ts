import { randomUUID } from 'crypto';
import { MongoServerError } from 'mongodb';
import {
  AutomationBet,
  AutomationRun,
  ensureAutomationIndexes,
  getAutomationBets,
  getAutomationBillingAccounts,
  getAutomationRuns,
  getCommissionPaymentOrders,
} from '@/lib/mongo';
import {
  calculateCommissionCents,
  calculateMaxLossCents,
  calculateTargetProfitCents,
  COMMISSION_BPS,
  maxLossRateBps,
  PIXGO_MIN_PAYMENT_CENTS,
  targetRateBps,
} from '@/lib/automationPolicy';
import { createCommissionInvoice, listAutomationInvoices } from '@/lib/invoices';

export function automationOwnerKey(
  email: string,
  house: string,
  gameId: string,
): string {
  return `${email}:${house}:${gameId}`;
}

export async function createAutomationRun(input: {
  email: string;
  house: string;
  gameId?: string;
  rouletteId?: string;
  betSessionId?: string;
  bankrollStartCents: number;
  chipValueCents?: number;
  targetProfitCents?: number;
  maxLossCents?: number;
  waitingForSignal?: boolean;
}): Promise<AutomationRun> {
  await ensureAutomationIndexes();
  const [runs, billing] = await Promise.all([
    getAutomationRuns(),
    getAutomationBillingAccounts(),
  ]);

  const account = await billing.findOne({ email: input.email });
  if (account && account.status !== 'clear') {
    throw new Error('PAYMENT_REQUIRED');
  }

  const existing = await runs.findOne({
    email: input.email,
    house: input.house,
    status: { $in: ['starting', 'waiting_signal', 'running'] },
  });
  if (existing) throw new Error('AUTOMATION_ALREADY_RUNNING');

  const now = new Date();
  const targetProfitCents =
    input.targetProfitCents ?? calculateTargetProfitCents(input.bankrollStartCents);
  const maxLossCents =
    input.maxLossCents ?? calculateMaxLossCents(input.bankrollStartCents);
  const run: AutomationRun = {
    runId: randomUUID(),
    email: input.email,
    house: input.house,
    gameId: input.gameId,
    rouletteId: input.rouletteId,
    betSessionId: input.betSessionId,
    status: input.waitingForSignal ? 'waiting_signal' : 'starting',
    bankrollStartCents: input.bankrollStartCents,
    targetRateBps: Math.round(
      (targetProfitCents * 10_000) / input.bankrollStartCents,
    ),
    targetProfitCents,
    maxLossCents,
    chipValueCents: input.chipValueCents ?? 0,
    commissionBps: COMMISSION_BPS,
    netProfitCents: 0,
    totalStakeCents: 0,
    totalPayoutCents: 0,
    roundsSettled: 0,
    startedAt: now,
    expiresAt: new Date(now.getTime() + 24 * 60 * 60 * 1000),
    criadoEm: now,
    atualizadoEm: now,
  };
  await runs.insertOne(run);
  return run;
}

export async function markAutomationRunning(runId: string): Promise<void> {
  const runs = await getAutomationRuns();
  await runs.updateOne(
    { runId, status: 'starting' },
    { $set: { status: 'running', atualizadoEm: new Date() } },
  );
}

export async function markAutomationError(
  runId: string,
  message: string,
): Promise<void> {
  const runs = await getAutomationRuns();
  await runs.updateOne(
    { runId, status: { $in: ['starting', 'running'] } },
    {
      $set: {
        status: 'error',
        stopReason: 'error',
        stoppedAt: new Date(),
        atualizadoEm: new Date(),
        errorMessage: message,
      },
    },
  );
}

export interface RoundSettlementInput {
  runId: string;
  roundId: string;
  betsCents: Record<string, number>;
  totalStakeCents: number;
  winningNumber: number;
  payoutCents: number;
  netProfitCents: number;
  settledAt: Date;
}

export async function recordRoundSettlement(
  input: RoundSettlementInput,
): Promise<{ duplicate: boolean; run: AutomationRun | null }> {
  await ensureAutomationIndexes();
  const [bets, runs] = await Promise.all([
    getAutomationBets(),
    getAutomationRuns(),
  ]);
  const doc: AutomationBet = {
    ...input,
    criadoEm: new Date(),
  };

  try {
    await bets.insertOne(doc);
  } catch (error) {
    if (error instanceof MongoServerError && error.code === 11000) {
      return { duplicate: true, run: await runs.findOne({ runId: input.runId }) };
    }
    throw error;
  }

  await runs.updateOne(
    { runId: input.runId, status: 'running' },
    {
      $inc: {
        netProfitCents: input.netProfitCents,
        totalStakeCents: input.totalStakeCents,
        totalPayoutCents: input.payoutCents,
        roundsSettled: 1,
      },
      $set: { atualizadoEm: new Date() },
    },
  );

  const run = await runs.findOne({ runId: input.runId });
  return { duplicate: false, run };
}

export async function finalizeAutomationRun(
  runId: string,
  reason: AutomationRun['stopReason'],
): Promise<AutomationRun | null> {
  await ensureAutomationIndexes();
  const [runs, billing] = await Promise.all([
    getAutomationRuns(),
    getAutomationBillingAccounts(),
  ]);
  const now = new Date();

  // A marca billingFinalizedAt torna o fechamento idempotente: callback e
  // botão de parada podem chegar quase ao mesmo tempo sem cobrar duas vezes.
  const claimed = await runs.updateOne(
    {
      runId,
      status: { $in: ['starting', 'waiting_signal', 'running'] },
      billingFinalizedAt: { $exists: false },
    },
    {
      $set: {
        stopReason: reason,
        stoppedAt: now,
        billingFinalizedAt: now,
        atualizadoEm: now,
      },
    },
  );
  if (claimed.modifiedCount === 0) return runs.findOne({ runId });

  const run = await runs.findOne({ runId });
  if (!run) return null;

  const commissionCents = calculateCommissionCents(run.netProfitCents);
  let amountDueCents = 0;
  let nextStatus: AutomationRun['status'] = 'completed';

  if (commissionCents > 0) {
    await createCommissionInvoice({
      email: run.email,
      runId: run.runId,
      amountCents: commissionCents,
      netProfitCents: run.netProfitCents,
      commissionBps: run.commissionBps,
    });
    await billing.updateOne(
      { email: run.email },
      {
        $inc: { outstandingCents: commissionCents },
        $set: { atualizadoEm: now },
        $setOnInsert: {
          email: run.email,
          status: 'clear',
          criadoEm: now,
        },
      },
      { upsert: true },
    );
    const account = await billing.findOne({ email: run.email });
    amountDueCents = account?.outstandingCents ?? commissionCents;
    if (amountDueCents >= PIXGO_MIN_PAYMENT_CENTS) {
      nextStatus = 'payment_due';
      await billing.updateOne(
        { email: run.email },
        {
          $set: {
            status: 'payment_due',
            activeRunId: run.runId,
            atualizadoEm: now,
          },
        },
      );
    }
  }

  await runs.updateOne(
    { runId },
    {
      $set: {
        status: nextStatus,
        commissionCents,
        amountDueCents,
        atualizadoEm: now,
      },
    },
  );
  return runs.findOne({ runId });
}

export async function getAutomationView(email: string, gameId?: string) {
  await ensureAutomationIndexes();
  const [runs, bets, billing, orders, invoices] = await Promise.all([
    getAutomationRuns(),
    getAutomationBets(),
    getAutomationBillingAccounts(),
    getCommissionPaymentOrders(),
    listAutomationInvoices(email),
  ]);
  const run = await runs.findOne(
    { email, ...(gameId ? { gameId } : {}) },
    { sort: { criadoEm: -1 } },
  );
  const account = await billing.findOne({ email });
  const order = await orders.findOne(
    { email, status: 'pending' },
    { sort: { criadoEm: -1 } },
  );
  const entries = run
    ? await bets
        .find({ runId: run.runId })
        .sort({ settledAt: -1 })
        .limit(200)
        .toArray()
    : [];
  return {
    run,
    entries,
    invoices,
    billing: account ?? {
      email,
      status: 'clear' as const,
      outstandingCents: 0,
    },
    order,
    policy: {
      commissionBps: COMMISSION_BPS,
      targetRateBps: targetRateBps(),
      maxLossRateBps: maxLossRateBps(),
      minimumPaymentCents: PIXGO_MIN_PAYMENT_CENTS,
    },
  };
}
