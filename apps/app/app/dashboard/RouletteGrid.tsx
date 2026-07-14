'use client';

import { useState } from 'react';
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

  // Jogo de cassino (Mines): abre em NOVA ABA. A aba é aberta já no clique
  // (gesto do usuário) p/ não ser bloqueada como popup; depois navega no link.
  // Abrimos SEM a flag 'noopener' (senão window.open devolve null e perdemos a
  // referência p/ navegar) e cortamos o opener manualmente por segurança.
  async function launchCasino(gameId: string) {
    const win = window.open('about:blank', '_blank');
    if (win) {
      try { win.opener = null; } catch { /* ok */ }
      win.document.write('<p style="font:16px sans-serif;color:#888;padding:24px">Abrindo o jogo…</p>');
    }
    setLoadingId(gameId);
    try {
      const res = await fetch(`/api/casino/${gameId}/launch`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.link) throw new Error(data.error ?? 'Falha ao abrir o jogo.');
      if (win) win.location.href = data.link;
      else window.location.href = data.link; // popup bloqueado: navega na própria aba
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Erro ao abrir o jogo.';
      if (win) win.document.body.innerHTML = `<p style="font:16px sans-serif;color:#c33;padding:24px">${msg}</p>`;
      else alert(msg);
    } finally {
      setLoadingId(null);
    }
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

      {/* Jogos de cassino (Mines) — abrem em nova aba na conta do usuário */}
      {casinoGames.map((g) => (
        <button
          key={`casino-${g.gameId}`}
          className="game-card"
          onClick={() => launchCasino(g.gameId)}
          disabled={loadingId !== null}
        >
          <div className="game-thumb">
            <MinesIcon />
            <span className="game-badge">{g.provider}</span>
          </div>
          <div className="game-info">
            <span className="game-name">{g.name}</span>
            <span className="game-cta">
              {loadingId === g.gameId ? 'Abrindo...' : 'Jogar em nova aba ↗'}
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}
