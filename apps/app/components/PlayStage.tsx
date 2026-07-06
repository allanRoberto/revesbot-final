'use client';

import { useState } from 'react';
import TableVideo from './TableVideo';
import RouletteBoard from './RouletteBoard';
import GameIframe from './GameIframe';

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
