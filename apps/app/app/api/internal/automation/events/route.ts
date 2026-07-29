import { NextResponse } from 'next/server';
import { isValidInternalRequest } from '@/lib/internalAuth';
import {
  finalizeAutomationRun,
  recordRoundSettlement,
} from '@/lib/automation';

const STOP_REASONS = new Set([
  'target_reached',
  'max_loss',
  'time_limit',
  'user_stop',
  'error',
]);

export async function POST(req: Request) {
  if (!isValidInternalRequest(req)) {
    return NextResponse.json({ error: 'Não autorizado.' }, { status: 401 });
  }

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Payload inválido.' }, { status: 400 });
  }
  const event = String(body.event || '');
  const runId = String(body.runId || '');
  if (!event || !runId) {
    return NextResponse.json({ error: 'Evento incompleto.' }, { status: 400 });
  }

  if (event === 'round_settled') {
    const roundId = String(body.roundId || '');
    const betsCents = (body.betsCents || {}) as Record<string, number>;
    const totalStakeCents = Number(body.totalStakeCents);
    const winningNumber = Number(body.winningNumber);
    const payoutCents = Number(body.payoutCents);
    const netProfitCents = Number(body.netProfitCents);
    const validBets = Object.entries(betsCents).every(([number, value]) => {
      const n = Number(number);
      return (
        Number.isInteger(n) &&
        n >= 0 &&
        n <= 36 &&
        Number.isInteger(value) &&
        value > 0
      );
    });
    const calculatedStakeCents = Object.values(betsCents).reduce(
      (sum, value) => sum + Number(value),
      0,
    );
    const calculatedPayoutCents =
      Number(betsCents[String(winningNumber)] || 0) * 36;
    const calculatedNetProfitCents =
      calculatedPayoutCents - calculatedStakeCents;
    if (
      !roundId ||
      !validBets ||
      !Number.isInteger(totalStakeCents) ||
      totalStakeCents <= 0 ||
      !Number.isInteger(winningNumber) ||
      winningNumber < 0 ||
      winningNumber > 36 ||
      !Number.isInteger(payoutCents) ||
      payoutCents < 0 ||
      !Number.isInteger(netProfitCents) ||
      totalStakeCents !== calculatedStakeCents ||
      payoutCents !== calculatedPayoutCents ||
      netProfitCents !== calculatedNetProfitCents
    ) {
      return NextResponse.json({ error: 'Liquidação inválida.' }, { status: 400 });
    }
    const result = await recordRoundSettlement({
      runId,
      roundId,
      betsCents,
      totalStakeCents,
      winningNumber,
      payoutCents,
      netProfitCents,
      settledAt: new Date(String(body.settledAt || new Date().toISOString())),
    });
    const run = result.run;
    if (
      run?.status === 'running' &&
      run.netProfitCents >= run.targetProfitCents
    ) {
      await finalizeAutomationRun(runId, 'target_reached');
    } else if (
      run?.status === 'running' &&
      run.netProfitCents <= -run.maxLossCents
    ) {
      await finalizeAutomationRun(runId, 'max_loss');
    }
    return NextResponse.json({ ok: true, duplicate: result.duplicate });
  }

  if (event === 'run_stopped') {
    const reason = String(body.reason || 'user_stop');
    if (!STOP_REASONS.has(reason)) {
      return NextResponse.json({ error: 'Motivo inválido.' }, { status: 400 });
    }
    await finalizeAutomationRun(
      runId,
      reason as
        | 'target_reached'
        | 'max_loss'
        | 'time_limit'
        | 'user_stop'
        | 'error',
    );
    return NextResponse.json({ ok: true });
  }

  if (event === 'run_error') {
    await finalizeAutomationRun(runId, 'error');
    return NextResponse.json({ ok: true });
  }

  return NextResponse.json({ error: 'Evento desconhecido.' }, { status: 400 });
}
