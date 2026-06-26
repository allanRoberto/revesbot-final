'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import type { RouletteGame } from '@/lib/games';

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

export default function RouletteGrid({ games }: { games: RouletteGame[] }) {
  const router = useRouter();
  const [loadingId, setLoadingId] = useState<string | null>(null);

  function play(gameId: string) {
    setLoadingId(gameId);
    // A página /play inicia o jogo no servidor e embute o iframe.
    router.push(`/play/${gameId}`);
  }

  return (
    <div className="games-grid">
      {games.map((g) => (
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
      ))}
    </div>
  );
}
