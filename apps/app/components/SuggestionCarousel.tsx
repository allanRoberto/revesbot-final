'use client';

import { useEffect, useRef, useState } from 'react';

const REDS = new Set([
  1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36,
]);
const colorClass = (n: number) => (n === 0 ? 'g' : REDS.has(n) ? 'r' : 'b');

const POLL_MS = 8000;

interface Item {
  prev3: number[];
  suggestion: number[];
  result: number | null;
  spinsToHit: number | null;
  hitNumber: number | null;
  pending: boolean;
}

export default function SuggestionCarousel({ gameId }: { gameId: string }) {
  const [items, setItems] = useState<Item[] | null>(null);
  const track = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const res = await fetch(`/api/games/${gameId}/suggestions?count=15`, {
          cache: 'no-store',
        });
        if (!res.ok || !active) return;
        const data = await res.json();
        if (Array.isArray(data.items)) setItems(data.items);
      } catch {
        /* mantém último valor */
      }
    }
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [gameId]);

  function scroll(dir: number) {
    track.current?.scrollBy({ left: dir * 240, behavior: 'smooth' });
  }

  return (
    <div className="sugc">
      <button className="sugc-arrow" onClick={() => scroll(-1)} aria-label="Anterior">
        ‹
      </button>

      <div className="sugc-track" ref={track}>
        {items === null ? (
          <span className="sugc-loading">calculando sugestões…</span>
        ) : (
          items.map((it, k) => {
            const status = it.pending
              ? 'atual'
              : it.spinsToHit !== null
                ? 'win'
                : 'miss';
            return (
              <div key={k} className={`sugc-card ${status}`}>
                <div className="sugc-card-head">
                  <span className="sugc-when">
                    {it.pending ? 'ATUAL' : `−${k}`}
                  </span>
                  <span className="sugc-prev">
                    {it.prev3.map((n, i) => (
                      <span key={i} className={`sug-chip xs ${colorClass(n)}`}>
                        {n}
                      </span>
                    ))}
                  </span>
                  {it.pending ? (
                    <span className="sugc-status pend">aguardando</span>
                  ) : it.spinsToHit !== null ? (
                    <span className="sugc-status win">
                      bateu {it.spinsToHit}º
                    </span>
                  ) : (
                    <span className="sugc-status miss">não bateu</span>
                  )}
                </div>
                <div className="sugc-nums">
                  {it.suggestion.map((n) => (
                    <span
                      key={n}
                      className={`sug-chip ${colorClass(n)}${
                        !it.pending && n === it.hitNumber ? ' hit' : ''
                      }`}
                    >
                      {n}
                    </span>
                  ))}
                </div>
              </div>
            );
          })
        )}
      </div>

      <button className="sugc-arrow" onClick={() => scroll(1)} aria-label="Próximo">
        ›
      </button>
    </div>
  );
}
