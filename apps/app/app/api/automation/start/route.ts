import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { findAppUser } from '@/lib/mongo';
import { getBookmakerUser } from '@/lib/bookmaker';
import { isActive } from '@/lib/subscription';
import { createAutomationRun } from '@/lib/automation';
import { calculateTargetProfitCents } from '@/lib/automationPolicy';
import { automationIsActivated } from '@/lib/invoices';

export async function POST(req: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  }
  if (!(await isActive(session.email))) {
    return NextResponse.json(
      { error: 'Assinatura necessária.', paywall: true },
      { status: 402 },
    );
  }
  if (!(await automationIsActivated(session.email))) {
    return NextResponse.json(
      {
        error: 'Pague a fatura de ativação para ligar o bot automático.',
        activationRequired: true,
      },
      { status: 402 },
    );
  }

  let body: { stopLossCents?: number };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Requisição inválida.' }, { status: 400 });
  }

  const user = await findAppUser(session.email, session.house);
  if (!user?.lotogreenToken) {
    return NextResponse.json(
      { error: 'Reconecte-se à casa de apostas.' },
      { status: 409 },
    );
  }
  const bookmaker = await getBookmakerUser(user.lotogreenToken, session.house);
  const bankrollStartCents = Number(bookmaker?.balance);
  if (!Number.isInteger(bankrollStartCents) || bankrollStartCents <= 0) {
    return NextResponse.json(
      { error: 'Não foi possível confirmar a banca atual.' },
      { status: 409 },
    );
  }

  const maxLossCents = Number(body.stopLossCents);
  if (
    !Number.isInteger(maxLossCents) ||
    maxLossCents < 100 ||
    maxLossCents > bankrollStartCents
  ) {
    return NextResponse.json(
      {
        error:
          'O Stop Loss deve ficar entre R$ 1,00 e o saldo disponível na casa.',
      },
      { status: 400 },
    );
  }

  try {
    const run = await createAutomationRun({
      email: session.email,
      house: session.house,
      bankrollStartCents,
      targetProfitCents: calculateTargetProfitCents(bankrollStartCents),
      maxLossCents,
      waitingForSignal: true,
    });
    return NextResponse.json({
      ok: true,
      run,
      signalSourceConnected:
        process.env.AUTOMATION_SIGNAL_SOURCE_ENABLED === 'true',
    });
  } catch (error) {
    const code = error instanceof Error ? error.message : '';
    if (code === 'PAYMENT_REQUIRED') {
      return NextResponse.json(
        {
          error: 'Pague as faturas de comissão pendentes para ligar novamente.',
          paymentDue: true,
        },
        { status: 402 },
      );
    }
    if (code === 'AUTOMATION_ALREADY_RUNNING') {
      return NextResponse.json(
        { error: 'O automático já está ligado ou aguardando sinais.' },
        { status: 409 },
      );
    }
    throw error;
  }
}
