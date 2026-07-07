'use client';

import { useEffect, useState } from 'react';

// Modo "jogo original": embute a Pragmatic direto (iframe) na conta do próprio
// usuário. Ele marca os números DENTRO do iframe. Roda no navegador do cliente
// (IP residencial) — sem depender do nosso servidor de vídeo. O bet_ws NÃO deve
// estar ativo ao mesmo tempo (o RouletteBoard é desmontado neste modo), senão a
// Pragmatic derruba uma das sessões da conta.
export default function GameIframe({ gameId }: { gameId: string }) {
  const [link, setLink] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLink(null);
    setErr(null);
    (async () => {
      try {
        const res = await fetch(`/api/games/${gameId}/start`, { method: 'POST' });
        const data = await res.json();
        if (!alive) return;
        if (!res.ok || !data.link) throw new Error(data.error ?? 'Falha ao abrir o jogo.');
        setLink(data.link);
      } catch (e) {
        if (alive) setErr(e instanceof Error ? e.message : 'Erro ao abrir o jogo.');
      }
    })();
    return () => {
      alive = false;
    };
  }, [gameId]);

  return (
    <div className="game-iframe-wrap">
      {link ? (
        <>
          <iframe
            className="game-iframe"
            src={link}
            allow="autoplay; fullscreen; encrypted-media"
            title="Jogo original"
          />
          {/* escape hatch discreto: se algum navegador recusar o embed, abre fora */}
          <button
            className="game-iframe-newtab"
            onClick={() => window.open(link, '_blank', 'noopener')}
            title="Abrir o jogo em nova aba"
          >
            Abrir em nova aba ↗
          </button>
        </>
      ) : (
        <div className="game-iframe-status">{err ?? 'Abrindo o jogo original…'}</div>
      )}
    </div>
  );
}
