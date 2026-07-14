'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  type RouletteGame,
  type CasinoGame,
  isGameAvailable,
  availableHouseNames,
} from '@/lib/games';

function RouletteWheel() {
  return (
    <svg viewBox="0 0 120 120" className="wheel" aria-hidden="true">
      <defs>
        <radialGradient id="rim" cx="50%" cy="40%" r="70%">
          <stop offset="0%" stopColor="#1c2f22" />
          <stop offset="100%" stopColor="#0a120d" />
        </radialGradient>
      </defs>
      <circle cx="60" cy="60" r="56" fill="url(#rim)" stroke="var(--gold)" strokeWidth="2" />
      {Array.from({ length: 16 }).map((_, i) => {
        const a = (i / 16) * Math.PI * 2;
        const r = (n: number) => Math.round(n * 100) / 100;
        const x1 = r(60 + Math.cos(a) * 18);
        const y1 = r(60 + Math.sin(a) * 18);
        const x2 = r(60 + Math.cos(a) * 52);
        const y2 = r(60 + Math.sin(a) * 52);
        return (
          <line
            key={i}
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            stroke={i % 2 ? 'var(--neon)' : '#3a5a45'}
            strokeWidth="2"
            opacity={i % 2 ? 0.9 : 0.5}
          />
        );
      })}
      <circle cx="60" cy="60" r="18" fill="#0a120d" stroke="var(--neon)" strokeWidth="2" />
      <circle cx="60" cy="60" r="5" fill="var(--gold)" />
    </svg>
  );
}

// Ícone do Mines: tile de cassino com uma bomba.
function MinesIcon() {
  return (
    <svg viewBox="0 0 120 120" className="wheel" aria-hidden="true">
      <defs>
        <radialGradient id="mines-rim" cx="50%" cy="40%" r="70%">
          <stop offset="0%" stopColor="#1c2f22" />
          <stop offset="100%" stopColor="#0a120d" />
        </radialGradient>
      </defs>
      <rect x="14" y="14" width="92" height="92" rx="16" fill="url(#mines-rim)" stroke="var(--gold)" strokeWidth="2" />
      {[38, 60, 82].map((x) =>
        [38, 60, 82].map((y) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r="2.2" fill="#3a5a45" />
        )),
      )}
      {/* bomba */}
      <circle cx="60" cy="64" r="20" fill="#0a120d" stroke="var(--neon)" strokeWidth="2.5" />
      <line x1="60" y1="44" x2="60" y2="34" stroke="var(--neon)" strokeWidth="2.5" />
      <path d="M60 34 q7 -6 13 -2" fill="none" stroke="var(--gold)" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="75" cy="30" r="3.2" fill="var(--gold)" />
      <circle cx="53" cy="57" r="4" fill="rgba(255,255,255,0.5)" />
    </svg>
  );
}

export default function RouletteGrid({
  games,
  casinoGames = [],
  house,
}: {
  games: RouletteGame[];
  casinoGames?: CasinoGame[];
  house: string;
}) {
  const router = useRouter();
  const [loadingId, setLoadingId] = useState<string | null>(null);

  function play(gameId: string) {
    setLoadingId(gameId);
    router.push(`/play/${gameId}`);
  }

  return (
    <div className="games-grid">
      {games.map((g) => {
        const available = isGameAvailable(g, house);
        if (!available) {
          return (
            <div key={g.gameId} className="game-card unavailable" aria-disabled="true">
              <div className="game-thumb">
                <RouletteWheel />
                <span className="game-badge">Roleta</span>
              </div>
              <div className="game-info">
                <span className="game-name">{g.name}</span>
                <span className="game-unavailable">
                  Disponível apenas em: {availableHouseNames(g).join(', ')}
                </span>
              </div>
            </div>
          );
        }
        return (
          <button
            key={g.gameId}
            className="game-card"
            onClick={() => play(g.gameId)}
            disabled={loadingId !== null}
          >
            <div className="game-thumb">
              <RouletteWheel />
              <span className="game-badge">Roleta</span>
            </div>
            <div className="game-info">
              <span className="game-name">{g.name}</span>
              <span className="game-cta">
                {loadingId === g.gameId ? 'Abrindo...' : 'Jogar ▸'}
              </span>
            </div>
          </button>
        );
      })}

      {/* Jogos de cassino (Mines) — link real que abre em nova aba */}
      {casinoGames.map((g) => (
        <CasinoCard key={`casino-${g.gameId}`} game={g} />
      ))}
    </div>
  );
}

// Card de jogo de cassino: busca o link jogável quando o dashboard carrega e o
// renderiza como <a target="_blank"> — clique num link nativo NUNCA é bloqueado
// como popup (o window.open era barrado em alguns navegadores).
function CasinoCard({ game }: { game: CasinoGame }) {
  const [link, setLink] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const lastFetch = useRef(0);

  const fetchLink = useCallback(async () => {
    setState((s) => (s === 'ready' ? s : 'loading'));
    try {
      const res = await fetch(`/api/casino/${game.gameId}/launch`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.link) throw new Error(data.error ?? 'Falha');
      setLink(data.link);
      setState('ready');
      lastFetch.current = Date.now();
    } catch {
      setState('error');
    }
  }, [game.gameId]);

  useEffect(() => {
    fetchLink();
  }, [fetchLink]);

  // Mantém o link fresco: se o usuário voltar à aba do dashboard depois de muito
  // tempo (>4min), refaz o link (o token de launch pode expirar).
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === 'visible' && Date.now() - lastFetch.current > 240000) {
        fetchLink();
      }
    };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, [fetchLink]);

  const thumb = (
    <div className="game-thumb">
      <MinesIcon />
      <span className="game-badge">{game.provider}</span>
    </div>
  );

  if (state === 'ready' && link) {
    return (
      <a className="game-card" href={link} target="_blank" rel="noopener noreferrer">
        {thumb}
        <div className="game-info">
          <span className="game-name">{game.name}</span>
          <span className="game-cta">Jogar em nova aba ↗</span>
        </div>
      </a>
    );
  }

  return (
    <button
      className="game-card"
      onClick={state === 'error' ? fetchLink : undefined}
      disabled={state === 'loading'}
    >
      {thumb}
      <div className="game-info">
        <span className="game-name">{game.name}</span>
        <span className="game-cta">
          {state === 'error' ? 'Tentar de novo' : 'Carregando…'}
        </span>
      </div>
    </button>
  );
}
