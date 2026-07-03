# video_ingest (PROTÓTIPO)

Prova de viabilidade da **Opção 2**: puxar o vídeo WebRTC da mesa e reempacotar em **HLS**
na nossa infra — sem depender de terceiros, servindo N espectadores a partir de 1 ingest.

> Roda num **servidor de mídia dedicado** (Ubuntu 22.04/24.04, ~4 vCPU / 8 GB RAM).
> NÃO rodar no servidor de prod (browser + encode = pesado demais lá).

## Como funciona

1. `get-link.js` loga no Express da casa e gera um `GAME_LINK` fresco.
2. `ingest.js` abre a mesa no **Google Chrome headed sob xvfb**, acha o `<video>` que
   está tocando, captura o `MediaStream` (`captureStream`) e manda os chunks
   (`MediaRecorder`) por um WS local para o **ffmpeg**, que gera `hls/stream.m3u8`.

O ponto que este protótipo prova: **o vídeo sobe no Chrome sob xvfb e sai como HLS.**

## Passo a passo

```bash
cd apps/video_ingest
sudo bash setup.sh                     # instala ffmpeg, xvfb, Google Chrome, deps

# 1) gerar um link fresco da mesa (373 = Auto Roulette)
export EXPRESS_URL=https://auth.revesbot.com.br
export EMAIL='allan.rsti@gmail.com'
export PASSWORD='SUA_SENHA'
export GAME_ID=373
LINK=$(npm run --silent get-link); echo "link len=${#LINK}"

# 2) rodar o ingest (usa xvfb-run automaticamente)
GAME_LINK="$LINK" npm run ingest
```

Deve aparecer: `[browser] vídeo encontrado 1280x720`, `MediaRecorder iniciado`,
`[ffmpeg] gravando HLS`. Em ~5s surgem segmentos em `hls/`.

## Verificar o resultado

```bash
# opção a: tocar direto
ffplay hls/stream.m3u8

# opção b: servir e abrir no navegador (hls.js)
python3 -m http.server 8080 --directory hls
# depois: http://SEU_IP:8080/stream.m3u8 num player HLS
```

## Se falhar

O log imprime um diagnóstico dos `<video>` encontrados (dimensão, readyState, paused).
Casos comuns:
- **Nenhum vídeo tocando** → o player não iniciou sob xvfb; testar `--use-gl=angle`,
  aumentar `VIDEO_WAIT_MS`, ou conferir se o Chrome tem H264 (`google-chrome://gpu`).
- **captureStream indisponível** → o vídeo pode estar em canvas/DRM; partir p/ captura
  de tela (xvfb + `ffmpeg x11grab`) como fallback.

## Variáveis

- `GAME_LINK` (obrigatório no ingest)
- `CHROME_BIN` (default `/usr/bin/google-chrome`)
- `HLS_DIR` (default `./hls`), `CHUNK_PORT` (default 4071), `VIDEO_WAIT_MS` (default 45000)

## Próximos passos (pós-viabilidade)

- Supervisão (pm2/systemd) + reconexão automática.
- 1 worker por mesa; player hls.js no `apps/app` apontando pro `.m3u8`.
- CDN (nginx/CloudFront) na frente do HLS para escalar espectadores.
