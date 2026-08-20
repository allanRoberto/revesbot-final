# App e Auth — operação e migração

## Topologia de produção

- `app.revesbot.com.br` → Nginx → `127.0.0.1:3002` (`revesbot-app`)
- `auth.revesbot.com.br` → Nginx → `127.0.0.1:3090` (`revesbot-auth`)
- app → `127.0.0.1:4060` (`revesbot-bet-ws`)
- app → `127.0.0.1:4080` (`revesbot-house-agent`)
- app → MongoDB de produção em `127.0.0.1:27018`

Todos os processos Node são executados pelo usuário `revesbot`. Somente Nginx e SSH
devem estar expostos pelo firewall.

## Arquivos de ambiente

- `/etc/revesbot/app.env`, modo `0640`, proprietário `root:revesbot`
- `/etc/revesbot/auth.env`, modo `0640`, proprietário `root:revesbot`

O `JWT_SECRET` e o `ENCRYPTION_KEY` devem ser os mesmos do servidor anterior durante
a migração. Alterá-los invalida sessões e senhas criptografadas existentes.

O provisionamento inicial recebe uma cópia temporária do ambiente antigo em
`/etc/revesbot/app-legacy.env` e executa `revesbot-app-provision-env`. O script cria
um usuário Mongo dedicado, preserva os segredos de sessão e substitui os endereços
dos serviços por conexões locais.

## Releases e rollback

- releases do app: `/var/www/revesbot/app-releases/<sha>`
- release ativa do app: `/var/www/revesbot/app-current`
- releases do auth: `/var/www/revesbot/auth-releases/<sha>`
- release ativa do auth: `/var/www/revesbot/auth-current`

Os scripts trocam o link `current` somente após instalação, testes e build. Se o
healthcheck falhar depois da troca, o link anterior é restaurado e o processo é
recarregado.

## Healthchecks

- auth: `http://127.0.0.1:3090/health`
- app: `http://127.0.0.1:3002/api/health`
- bet_ws: `http://127.0.0.1:4060/health`
- house-agent: `http://127.0.0.1:4080/health`

O healthcheck do app exige MongoDB e auth saudáveis.

## Migração das collections do app

O script `apps/app/scripts/migrate-app-data.mjs` copia somente:

- `app_users`
- `app_subscriptions`
- `automation_runs`
- `automation_bets`
- `automation_billing_accounts`
- `commission_payment_orders`
- `automation_invoices`
- `payment_webhook_events`

Ele nunca copia `history`. A cópia usa collections temporárias, replica índices,
confere as contagens e então faz a troca atômica do nome. Um destino não vazio é
recusado, a menos que `--replace` seja informado explicitamente.

## Ordem de corte

1. Implantar e validar auth pela porta interna.
2. Fazer a primeira cópia das collections do app.
3. Implantar e validar app pela porta interna.
4. Validar login, saldo, mesa, vídeo, bet_ws, house-agent e PixGo.
5. Interromper brevemente novas escritas no app antigo.
6. Repetir a cópia com `--replace` e validar contagens/índices.
7. Trocar primeiro `auth.revesbot.com.br` e depois `app.revesbot.com.br`.
8. Manter o servidor anterior disponível para rollback durante a observação.
