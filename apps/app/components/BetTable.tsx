'use client';

// Wrapper React do pano de apostas (RouletteBetTable, no mesmo plugin do
// racetrack). Compartilha o estado `placed` — as fichas aparecem aqui e na
// pista ao mesmo tempo, e um clique aqui reflete lá (via commit no pai).

import { useEffect, useRef } from 'react';
import { RouletteBetTable } from '@/lib/roulette-racetrack';

interface Props {
  placed: Record<number, number>;
  disabled: boolean;
  onNumber: (n: number) => void;
}

export default function BetTable({ placed, disabled, onNumber }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const ftRef = useRef<InstanceType<typeof RouletteBetTable> | null>(null);
  const liveRef = useRef({ onNumber, disabled });

  useEffect(() => {
    liveRef.current = { onNumber, disabled };
  }, [onNumber, disabled]);

  useEffect(() => {
    if (!boxRef.current) return;
    const ft = new RouletteBetTable(boxRef.current, {
      onNumberClick: ({ number }: { number: number }) => {
        if (!liveRef.current.disabled) liveRef.current.onNumber(number);
      },
    });
    ftRef.current = ft;
    return () => {
      ft.destroy();
      ftRef.current = null;
    };
  }, []);

  useEffect(() => {
    ftRef.current?.setBets(placed);
  }, [placed]);

  return <div ref={boxRef} className={`ft-box${disabled ? ' ft-off' : ''}`} />;
}
