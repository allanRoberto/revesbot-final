#!/usr/bin/env bash
# Wrapper do serviço: gera um GAME_LINK fresco e roda o ingest sob xvfb.
# Credenciais vêm do EnvironmentFile do systemd (.env), nunca hardcoded aqui.
set -e
cd /home/ubuntu/video_ingest
GID="${GAME_ID:-373}"
HLS_DIR="/home/ubuntu/video_ingest/hls/${GID}"
rm -rf "$HLS_DIR" && mkdir -p "$HLS_DIR"
LINK=$(EXPRESS_URL="${EXPRESS_URL:-https://auth.revesbot.com.br}" GAME_ID="${GID}" node get-link.js)
echo "run.sh: game=${GID} link_len=${#LINK}"
exec env GAME_LINK="$LINK" CHROME_BIN=/usr/bin/chromium NET_KBPS="${NET_KBPS:-2500}" HLS_DIR="$HLS_DIR" \
  WS_PORT="${WS_PORT:-$((20000 + GID))}" \
  xvfb-run -a -s "-screen 0 1280x720x24" node ingest.js
