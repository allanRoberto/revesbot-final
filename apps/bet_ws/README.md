# bet_ws

Serviço que **captura o WebSocket da mesa** (Pragmatic/LotoGreen) e **envia apostas**
(`<lpbet>`) por sessão. É o backend do botão "Marcar sugeridos" do `apps/app`.

Lógica portada de `apps/bot_automatico/bot_aposta.js`, mas **multiusuário**
(uma sessão de mesa por usuário, keyed por `sessionId`).

## Como funciona

1. O `apps/app` já resolve o link jogável da mesa (`startGame`, autenticado).
2. `POST /session { gameLink, rouletteId }` → abre o link num Chrome headless,
   intercepta a URL do WS (Proxy em `window.WebSocket` + evento nativo do Puppeteer),
   fecha o browser e abre uma conexão `ws` própria com a mesa. Retorna `{ sessionId, ... }`.
3. `GET /session/:id/state` → `{ betsOpen, gameInfo, lastResult, ... }`.
4. `POST /session/:id/bet { numbers, chipValue }` → envia o `<lpbet>` real.
5. `DELETE /session/:id` → encerra a sessão.

Auth server-to-server via header `X-Bet-Token` (== `BET_WS_TOKEN`).

## Rodar

```bash
cd apps/bet_ws
cp .env.example .env   # ajuste BET_WS_TOKEN e BASE_CHIP
PUPPETEER_SKIP_DOWNLOAD=true npm install   # reusa o Chrome do cache
npm start
```

> **Disco cheio / Chromium:** o `capture.js` reaproveita o Chrome já baixado em
> `~/.cache/puppeteer/chrome-headless-shell/*` (por isso o `PUPPETEER_SKIP_DOWNLOAD`).
> Para forçar outro binário, use `PUPPETEER_EXECUTABLE_PATH`.

## Variáveis

- `BET_WS_PORT` (default 4060)
- `BASE_CHIP` (valor de ficha padrão quando o app não manda `chipValue`)
- `BET_WS_TOKEN` (token compartilhado com o app; vazio = auth off)
- `SESSION_IDLE_TTL_MS` (default 30 min)
