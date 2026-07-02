'use client';

import { useEffect, useRef, useState } from 'react';

// Base pública do servidor de mídia (HLS). Ex.: https://video.revesbot.com.br
// Em dev, via túnel SSH: http://localhost:8099
const VIDEO_BASE = process.env.NEXT_PUBLIC_VIDEO_BASE || '';

// Player HLS da mesa (substitui o iframe da LotoGreen). O vídeo vem do nosso
// servidor de mídia (ingest próprio), não da Pragmatic — então não dá kick.
export default function TableVideo({ gameId }: { gameId: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<'loading' | 'playing' | 'error'>('loading');

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !VIDEO_BASE) {
      setStatus('error');
      return;
    }
    const src = `${VIDEO_BASE}/hls/${gameId}/stream.m3u8`;
    let hls: { destroy: () => void } | null = null;
    let cancelled = false;

    (async () => {
      // Safari/iOS tocam HLS nativamente.
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = src;
        video.addEventListener('loadeddata', () => setStatus('playing'));
        video.addEventListener('error', () => setStatus('error'));
        return;
      }
      const Hls = (await import('hls.js')).default;
      if (cancelled) return;
      if (!Hls.isSupported()) {
        setStatus('error');
        return;
      }
      const inst = new Hls({ liveSyncDurationCount: 3, lowLatencyMode: true });
      hls = inst;
      inst.loadSource(src);
      inst.attachMedia(video);
      inst.on(Hls.Events.MANIFEST_PARSED, () => {
        setStatus('playing');
        video.play().catch(() => {});
      });
      inst.on(Hls.Events.ERROR, (_e, data) => {
        if (data.fatal) setStatus('error');
      });
    })();

    return () => {
      cancelled = true;
      if (hls) hls.destroy();
    };
  }, [gameId]);

  return (
    <div className="table-video-wrap">
      <video
        ref={videoRef}
        className="table-video"
        autoPlay
        muted
        playsInline
        controls
      />
      {status !== 'playing' && (
        <div className="table-video-status">
          {status === 'loading'
            ? 'Conectando ao vídeo da mesa…'
            : 'Vídeo desta mesa indisponível no momento.'}
        </div>
      )}
    </div>
  );
}
