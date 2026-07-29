import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { finalizeAutomationRun } from '@/lib/automation';
import { getAutomationRuns } from '@/lib/mongo';

export async function POST() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  }

  const runs = await getAutomationRuns();
  const run = await runs.findOne(
    {
      email: session.email,
      house: session.house,
      status: { $in: ['starting', 'waiting_signal', 'running'] },
    },
    { sort: { criadoEm: -1 } },
  );
  if (!run) {
    return NextResponse.json(
      { error: 'O automático não está ligado.' },
      { status: 409 },
    );
  }

  // Até a central de sinais ser conectada, nenhuma sessão externa é aberta.
  // Encerrar somente o ciclo persistido mantém a publicação compatível com o
  // serviço de apostas que já está em produção.
  const finalized = await finalizeAutomationRun(run.runId, 'user_stop');
  return NextResponse.json({ ok: true, run: finalized });
}
