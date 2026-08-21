'use client';

// Wrapper React do pano de apostas (RouletteBetTable, no mesmo plugin do
// racetrack). Compartilha o estado `placed` — as fichas aparecem aqui e na
// pista ao mesmo tempo, e um clique aqui reflete lá (via commit no pai).

import { useEffect, useRef } from 'react';
import { RouletteBetTable } from '@/lib/roulette-racetrack';

interface Props {
  placed: Record<number, number>;
  lastResult: number | null;
  disabled: boolean;
  onNumber: (n: number) => void;
  onSection: (numbers: number[]) => void;
}

export default function BetTable({ placed, lastResult, disabled, onNumber, onSection }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const ftRef = useRef<InstanceType<typeof RouletteBetTable> | null>(null);
  const liveRef = useRef({ onNumber, onSection, disabled });

  useEffect(() => {
    liveRef.current = { onNumber, onSection, disabled };
  }, [onNumber, onSection, disabled]);

  useEffect(() => {
    if (!boxRef.current) return;
    const ft = new RouletteBetTable(boxRef.current, {
      onNumberClick: ({ number }: { number: number }) => {
        if (!liveRef.current.disabled) liveRef.current.onNumber(number);
      },
      onSectionClick: ({ numbers }: { numbers: number[] }) => {
        if (!liveRef.current.disabled) liveRef.current.onSection(numbers);
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

  useEffect(() => {
    const ft = ftRef.current;
    if (!ft) return;
    if (lastResult === null) ft.clearResult();
    else ft.setResult(lastResult);
  }, [lastResult]);

  return <div ref={boxRef} className={`ft-box${disabled ? ' ft-off' : ''}`} />;
}
