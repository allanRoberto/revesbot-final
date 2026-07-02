import { getSession } from '@/lib/session';
import { findRoulette } from '@/lib/games';
import { isActive } from '@/lib/subscription';
import { openSessionEvents } from '@/lib/betws';

export const dynamic = 'force-dynamic';

// SSE: repassa o stream de estado da mesa (bet_ws) para o navegador.
// O browser conecta via EventSource (mesma origem, autenticado pelo cookie).
export async function GET(
  req: Request,
  { params }: { params: Promise<{ gameId: string }> },
) {
  const { gameId } = await params;
  if (!findRoulette(gameId)) {
    return new Response('jogo indisponível', { status: 404 });
  }
  const session = await getSession();
  if (!session) return new Response('não autenticado', { status: 401 });
  if (!(await isActive(session.email))) {
    return new Response('assinatura necessária', { status: 402 });
  }

  const sessionId = new URL(req.url).searchParams.get('sessionId');
  if (!sessionId) return new Response('sessionId obrigatório', { status: 400 });

  const upstream = await openSessionEvents(sessionId);
  if (!upstream.ok || !upstream.body) {
    return new Response('sessão não encontrada', { status: upstream.status || 502 });
  }

  return new Response(upstream.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
    },
  });
}
