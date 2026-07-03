#!/usr/bin/env bash
# Setup do servidor de mídia dedicado (Ubuntu 22.04/24.04) para o protótipo de ingest.
# Instala: ffmpeg, xvfb, Google Chrome (com H264/AAC), libs e deps node.
set -euo pipefail

echo "==> apt update + pacotes base"
apt-get update
apt-get install -y --no-install-recommends \
  ffmpeg xvfb wget ca-certificates gnupg \
  fonts-liberation libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
  libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
  libgbm1 libasound2t64 libpangocairo-1.0-0 libpango-1.0-0 libcairo2 libx11-xcb1

echo "==> Google Chrome stable (tem codecs H264/AAC — necessário p/ o vídeo WebRTC)"
if ! command -v google-chrome >/dev/null 2>&1; then
  wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  apt-get install -y /tmp/chrome.deb
  rm -f /tmp/chrome.deb
fi
google-chrome --version || true

echo "==> deps node (usa o Chrome do sistema, sem baixar Chromium)"
export PUPPETEER_SKIP_DOWNLOAD=true
npm install

echo "==> pronto. Chrome em: $(command -v google-chrome)"
echo "    Rode:  npm run get-link   (gera GAME_LINK)"
echo "    Depois: GAME_LINK='...' npm run ingest"
