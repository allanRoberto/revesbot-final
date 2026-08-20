'use client';

// Wrapper React do plugin RouletteRacetrack (vendorizado de
// apps/api/static/js/roulette-racetrack_3.js → lib/roulette-racetrack.js).
// O plugin monta o SVG da pista (curvas [32,0,26,3,35] e [30,8,23,10,5,24],
// rótulos centralizados) e expõe callbacks de clique + APIs de destaque.

import { useEffect, useRef } from 'react';
import RouletteRacetrack from '@/lib/roulette-racetrack';

interface Props {
  placed: Record<number, number>;
  lastResult: number | null;
  disabled: boolean;
  onNumber: (n: number) => void;
  onSection: (numbers: number[]) => void;
}

export default function RaceTrack({
  placed,
  lastResult,
  disabled,
  onNumber,
  onSection,
}: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const rtRef = useRef<InstanceType<typeof RouletteRacetrack> | null>(null);
  // callbacks/estado mais recentes sem recriar o plugin a cada render
  const liveRef = useRef({ onNumber, onSection, disabled });

  useEffect(() => {
    liveRef.current = { onNumber, onSection, disabled };
  }, [onNumber, onSection, disabled]);

  useEffect(() => {
    if (!boxRef.current) return;
    const rt = new RouletteRacetrack(boxRef.current, {
      responsive: true,
      onNumberClick: ({ number }: { number: number }) => {
        if (!liveRef.current.disabled) liveRef.current.onNumber(number);
      },
      onSectionClick: ({ numbers }: { numbers: number[] }) => {
        if (!liveRef.current.disabled) liveRef.current.onSection(numbers);
      },
    });
    rtRef.current = rt;
    if (process.env.NODE_ENV !== 'production') {
      // handle de depuração (só em dev): permite inspecionar/testar o plugin
      (window as unknown as Record<string, unknown>).__rt = rt;
    }
    return () => {
      rt.destroy();
      rtRef.current = null;
    };
  }, []);

  // Fichas com a quantidade apostada aparecem sobre os números.
  useEffect(() => {
    const rt = rtRef.current;
    if (!rt) return;
    rt.setBets(placed);
  }, [placed]);

  // Número sorteado brilha por alguns segundos (heatmap do plugin).
  useEffect(() => {
    const rt = rtRef.current;
    if (!rt || lastResult === null) return;
    rt.applyHeatmap({ [lastResult]: 1 });
    const t = setTimeout(() => rtRef.current?.clearHeatmap(), 6000);
    return () => clearTimeout(t);
  }, [lastResult]);

  return (
    <div
      ref={boxRef}
      className={`rt-box${disabled ? ' rt-off' : ''}`}
      style={{ '--rt-highlight': '#ffd15a' } as React.CSSProperties}
    />
  );
}
