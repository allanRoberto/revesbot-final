'use client';

import { useEffect, useRef, useState } from 'react';

// Base pública do servidor de mídia. Ex.: https://video.revesbot.com.br
// Em dev, via túnel SSH: http://localhost:8099
const VIDEO_BASE = process.env.NEXT_PUBLIC_VIDEO_BASE || '';

// Player da mesa. Caminho principal: fMP4 ao vivo por WebSocket alimentando o
// MSE (latência ~1-2s). Fallback: HLS — Safari iOS (sem MSE) e falha do WS.
export default function TableVideo({ gameId }: { gameId: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<'loading' | 'playing' | 'error'>('loading');
  // Travou/caiu? Mostra o poster borrado da mesa por cima (nada de tela preta).
  const [stalled, setStalled] = useState(false);
  const posterUrl = VIDEO_BASE ? `${VIDEO_BASE}/hls/${gameId}/poster.jpg` : '';

  // Detecção de travamento (revela o poster): eventos do vídeo (buffer vazio,
  // stall, erro) + um watchdog de currentTime como rede de segurança.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const onStall = () => setStalled(true);
    const onOk = () => setStalled(false);
    video.addEventListener('waiting', onStall);
    video.addEventListener('stalled', onStall);
    video.addEventListener('error', onStall);
    video.addEventListener('emptied', onStall);
    video.addEventListener('playing', onOk);
    video.addEventListener('canplay', onOk);

    let lastT = -1;
    let same = 0;
    const id = setInterval(() => {
      if (video.paused) return;
      if (Math.abs(video.currentTime - lastT) < 0.02) {
        if (++same >= 2) setStalled(true);
      } else {
        same = 0;
        setStalled(false);
      }
      lastT = video.currentTime;
    }, 1200);
    return () => {
      clearInterval(id);
      video.removeEventListener('waiting', onStall);
      video.removeEventListener('stalled', onStall);
      video.removeEventListener('error', onStall);
      video.removeEventListener('emptied', onStall);
      video.removeEventListener('playing', onOk);
      video.removeEventListener('canplay', onOk);
    };
  }, [gameId]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !VIDEO_BASE) {
      setStatus('error');
      return;
    }
    let cancelled = false;
    let cleanup: (() => void) | null = null;
    let wsFailures = 0;

    const onPlaying = () => setStatus('playing');
    video.addEventListener('playing', onPlaying);

    const startHls = async () => {
      const src = `${VIDEO_BASE}/hls/${gameId}/stream.m3u8`;
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = src;
        video.addEventListener('error', () => setStatus('error'), { once: true });
        return;
      }
      const Hls = (await import('hls.js')).default;
      if (cancelled) return;
      if (!Hls.isSupported()) {
        setStatus('error');
        return;
      }
      const inst = new Hls({
        liveSyncDurationCount: 2,
        maxLiveSyncPlaybackRate: 1.5,
        lowLatencyMode: true,
      });
      inst.loadSource(src);
      inst.attachMedia(video);
      inst.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => {});
      });
      inst.on(Hls.Events.ERROR, (_e, data) => {
        if (data.fatal) setStatus('error');
      });
      cleanup = () => inst.destroy();
    };

    const startWs = () => {
      const wsUrl = `${VIDEO_BASE.replace(/^http/, 'ws')}/ws/${gameId}`;
      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';
      let sb: SourceBuffer | null = null;
      let objUrl = '';
      let dead = false;
      const queue: ArrayBuffer[] = [];

      const teardown = () => {
        dead = true;
        clearTimeout(watchdog);
        clearInterval(chaser);
        try { ws.close(); } catch { /* já fechado */ }
        if (objUrl) URL.revokeObjectURL(objUrl);
      };
      const fail = () => {
        if (dead || cancelled) return;
        teardown();
        wsFailures += 1;
        if (wsFailures >= 3) startHls();
        else setTimeout(() => { if (!cancelled) startWs(); }, 1500);
      };

      // Sem init em 8s = relay fora do ar → tenta de novo / cai pro HLS.
      const watchdog = setTimeout(() => { if (!sb) fail(); }, 8000);

      const pump = () => {
        if (!sb || sb.updating || queue.length === 0) return;
        try {
          sb.appendBuffer(queue.shift()!);
        } catch {
          fail();
        }
      };

      ws.onmessage = (ev) => {
        if (dead) return;
        if (typeof ev.data === 'string') {
          let mime = '';
          try { mime = JSON.parse(ev.data).mime || ''; } catch { /* ignora */ }
          if (!('MediaSource' in window) || !mime || !MediaSource.isTypeSupported(mime)) {
            wsFailures = 99; // sem MSE não adianta insistir no WS
            fail();
            return;
          }
          const ms = new MediaSource();
          objUrl = URL.createObjectURL(ms);
          video.src = objUrl;
          ms.addEventListener('sourceopen', () => {
            if (dead) return;
            sb = ms.addSourceBuffer(mime);
            sb.addEventListener('updateend', pump);
            pump();
          });
          return;
        }
        queue.push(ev.data as ArrayBuffer);
        pump();
      };
      ws.onerror = () => fail();
      ws.onclose = () => fail();

      // Persegue a borda ao vivo: atrasou → acelera; atrasou muito → pula.
      const chaser = setInterval(() => {
        if (!sb || dead) return;
        try {
          const b = sb.buffered;
          if (!b.length) return;
          const start = b.start(b.length - 1);
          const end = b.end(b.length - 1);
          if (video.currentTime < start) video.currentTime = Math.max(start, end - 0.7);
          const lag = end - video.currentTime;
          if (lag > 3) video.currentTime = end - 0.5;
          else if (lag > 1.5) video.playbackRate = 1.12;
          else video.playbackRate = 1;
          if (video.paused) video.play().catch(() => {});
          if (!sb.updating && video.currentTime - b.start(0) > 30) {
            sb.remove(b.start(0), video.currentTime - 10);
          }
        } catch { /* buffered indisponível durante transições */ }
      }, 1000);

      cleanup = teardown;
    };

    if (typeof window !== 'undefined' && 'MediaSource' in window) startWs();
    else startHls();

    return () => {
      cancelled = true;
      video.removeEventListener('playing', onPlaying);
      if (cleanup) cleanup();
    };
  }, [gameId]);

  const showPoster = status !== 'playing' || stalled;

  return (
    <div className="table-video-wrap">
      <video
        ref={videoRef}
        className="table-video"
        autoPlay
        muted
        playsInline
      />
      {/* fallback: poster borrado da mesa (sem tela preta quando trava/cai) */}
      {showPoster && posterUrl && (
        <div
          className="table-video-poster"
          style={{ backgroundImage: `url(${posterUrl})` }}
        />
      )}
      {status === 'loading' && (
        <div className="table-video-status">Conectando ao vídeo da mesa…</div>
      )}
    </div>
  );
}
