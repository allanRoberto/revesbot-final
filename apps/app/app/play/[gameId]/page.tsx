import Link from 'next/link';
import { redirect, notFound } from 'next/navigation';
import { getSession } from '@/lib/session';
import { getUsers } from '@/lib/mongo';
import { getBookmakerUser, startGame } from '@/lib/bookmaker';
import { findRoulette } from '@/lib/games';
import BalanceBadge from '@/components/BalanceBadge';
import SuggestionCarousel from '@/components/SuggestionCarousel';

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

  const users = await getUsers();
  const user = await users.findOne({ email: session.email });
  if (!user?.lotogreenToken) redirect('/login');

  const [bookmaker, result] = await Promise.all([
    getBookmakerUser(user.lotogreenToken),
    startGame(gameId, user.lotogreenToken),
  ]);

  return (
    <div className="play-shell">
      <header className="topbar">
        <div className="play-head-left">
          <Link className="back-btn" href="/dashboard">
            <span className="back-arrow">‹</span>
            <span className="back-label">Voltar</span>
          </Link>
          <span className="play-title">{game.name}</span>
        </div>
        <BalanceBadge initial={bookmaker?.balance ?? null} />
      </header>

      <SuggestionCarousel gameId={gameId} />

      {result.ok && result.link ? (
        <iframe
          className="game-frame"
          src={result.link}
          title={game.name}
          allow="autoplay; fullscreen; payment"
          allowFullScreen
        />
      ) : (
        <div className="play-error">
          <h2>Não foi possível abrir o jogo</h2>
          <p>{result.error ?? 'Tente novamente em instantes.'}</p>
          <Link className="logout-sm" href="/dashboard">
            Voltar para as roletas
          </Link>
        </div>
      )}
    </div>
  );
}
