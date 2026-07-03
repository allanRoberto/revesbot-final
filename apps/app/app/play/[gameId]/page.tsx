import Link from 'next/link';
import { redirect, notFound } from 'next/navigation';
import { getSession } from '@/lib/session';
import { findAppUser } from '@/lib/mongo';
import { getBookmakerUser } from '@/lib/bookmaker';
import { findRoulette, isGameAvailable, availableHouseNames } from '@/lib/games';
import SuggestionStrip from '@/components/SuggestionStrip';
import SubscriptionGate from '@/components/SubscriptionGate';
import TableVideo from '@/components/TableVideo';
import RouletteBoard from '@/components/RouletteBoard';

export default async function PlayPage({
  params,
}: {
  params: Promise<{ gameId: string }>;
}) {
  const { gameId } = await params;

  const game = findRoulette(gameId);
  if (!game) notFound();

  const session = await getSession();
  if (!session) redirect('/login');

  const user = await findAppUser(session.email, session.house);
  if (!user?.lotogreenToken) redirect('/login');

  // Mesa não oferecida por esta casa → bloqueia (a mesma checagem do dashboard).
  if (!isGameAvailable(game, session.house)) {
    return (
      <div className="play-shell">
        <header className="topbar play-topbar">
          <div className="play-head-left">
            <Link className="back-btn" href="/dashboard">
              <span className="back-arrow">‹</span>
              <span className="back-label">Voltar</span>
            </Link>
            <span className="play-title">{game.name}</span>
          </div>
        </header>
        <div className="play-error">
          <h2>Mesa indisponível nesta casa</h2>
          <p>Disponível apenas em: {availableHouseNames(game).join(', ')}.</p>
          <Link className="logout-sm" href="/dashboard">
            Voltar para as roletas
          </Link>
        </div>
      </div>
    );
  }

  // Vídeo vem do nosso servidor de mídia (não abrimos jogo na conta do usuário
  // aqui — a sessão da casa só é usada quando ele aposta via bet_ws).
  const bookmaker = await getBookmakerUser(user.lotogreenToken, session.house);

  return (
    <div className="stage">
      {/* vídeo da mesa em tela cheia (fundo) */}
      <TableVideo gameId={gameId} />

      {/* barra superior translúcida sobre o vídeo */}
      <header className="topbar play-topbar stage-topbar">
        <div className="play-head-left">
          <Link className="back-btn" href="/dashboard">
            <span className="back-arrow">‹</span>
            <span className="back-label">Voltar</span>
          </Link>
          <span className="play-title">{game.name}</span>
        </div>
        <SuggestionStrip gameId={gameId} />
      </header>

      {/* overlays de aposta (pano, pista, saldo, painel) */}
      <RouletteBoard gameId={gameId} initialBalance={bookmaker?.balance ?? null} />

      <SubscriptionGate />
    </div>
  );
}
