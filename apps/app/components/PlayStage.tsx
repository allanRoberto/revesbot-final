'use client';

import { useState } from 'react';
import TableVideo from './TableVideo';
import RouletteBoard from './RouletteBoard';
import GameIframe from './GameIframe';

function AutoRouletteFrame() {
  const opening = 'M 548 20 C 670 -8 930 -8 1052 20 C 1164 46 1226 146 1238 292 C 1253 476 1186 646 1072 760 C 984 848 616 848 528 760 C 414 646 347 476 362 292 C 374 146 436 46 548 20 Z';
  return (
    <div className="auto-wheel-frame" aria-hidden="true">
      <svg viewBox="0 0 1600 900" preserveAspectRatio="none">
        <defs>
          <linearGradient id="awf-blue" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#315986" />
            <stop offset="52%" stopColor="#183e6a" />
            <stop offset="100%" stopColor="#0b294c" />
          </linearGradient>
          <linearGradient id="awf-metal" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#746a61" />
            <stop offset="28%" stopColor="#2e2d2e" />
            <stop offset="64%" stopColor="#17191b" />
            <stop offset="100%" stopColor="#655846" />
          </linearGradient>
          <linearGradient id="awf-gold" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#fff0a0" />
            <stop offset="38%" stopColor="#dca843" />
            <stop offset="100%" stopColor="#85520b" />
          </linearGradient>
          <filter id="awf-fabric" x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency="0.012 0.065" numOctaves="2" seed="8" result="noise" />
            <feColorMatrix in="noise" type="saturate" values="0" result="gray" />
            <feBlend in="SourceGraphic" in2="gray" mode="soft-light" />
          </filter>
        </defs>
        <path
          d={`M 0 0 H 1600 V 900 H 0 Z ${opening}`}
          fill="url(#awf-blue)"
          fillRule="evenodd"
          filter="url(#awf-fabric)"
        />
        <path d="M 0 30 Q 800 -2 1600 30" fill="none" stroke="#282727" strokeWidth="38" />
        <path d="M 0 26 Q 800 -6 1600 26" fill="none" stroke="url(#awf-gold)" strokeWidth="5" />
        <path d={opening} fill="none" stroke="#111214" strokeWidth="52" strokeLinejoin="round" />
        <path d={opening} fill="none" stroke="url(#awf-metal)" strokeWidth="40" strokeLinejoin="round" />
        <path d={opening} fill="none" stroke="url(#awf-gold)" strokeWidth="7" strokeLinejoin="round" />
        <path d={opening} fill="none" stroke="rgba(255,240,180,.52)" strokeWidth="1.5" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

// Alterna entre a NOSSA transmissão (vídeo relay + tabuleiro/overlay próprios)
// e o JOGO ORIGINAL (iframe da Pragmatic na conta do usuário). No modo iframe o
// RouletteBoard é desmontado — assim o bet_ws não briga pela sessão da conta.
export default function PlayStage({
  gameId,
  initialBalance,
}: {
  gameId: string;
  initialBalance: number | null;
}) {
  const [mode, setMode] = useState<'transmission' | 'iframe'>('transmission');
  const iframe = mode === 'iframe';

  return (
    <>
      {iframe ? (
        <GameIframe gameId={gameId} />
      ) : (
        <>
          <TableVideo gameId={gameId} />
          {gameId === '373' && <AutoRouletteFrame />}
          <RouletteBoard gameId={gameId} initialBalance={initialBalance} />
        </>
      )}

      <button
        className={`stage-modebtn${iframe ? ' on' : ''}`}
        onClick={() => setMode((m) => (m === 'iframe' ? 'transmission' : 'iframe'))}
        title={iframe ? 'Voltar para a transmissão' : 'Abrir o jogo original (iframe) e apostar direto nele'}
      >
        {iframe ? '📺 Transmissão' : '🎮 Jogo original'}
      </button>
    </>
  );
}
