# Deploy da API e Auth API

Esta etapa cobre apenas:

- `apps/api`
- `apps/auth_api`

Os workers Python (`signals`, `monitoring`, `collector`) continuam fora do deploy automatizado nesta fase.

## Ambientes

### Branch `develop`
- `dev.revesbot.com.br` -> `apps/api`
- `auth-dev.revesbot.com.br` -> `apps/auth_api`

### Branch `main`
- `api.revesbot.com.br` -> `apps/api`
- `auth.revesbot.com.br` -> `apps/auth_api`

## Layout no servidor

Diretórios esperados no servidor:

- `/var/www/revesbot-final/develop`
- `/var/www/revesbot-final/main`

Arquivos de ambiente fora do repositório:

- `/etc/revesbot/develop.env`
- `/etc/revesbot/main.env`

## PM2

Processos gerenciados:

- `api-dev`
- `auth-api-dev`
- `api-prod`
- `auth-api-prod`

Portas locais usadas pelo Nginx:

- `api-dev` -> `127.0.0.1:8081`
- `api-prod` -> `127.0.0.1:8080`
- `auth-api-dev` -> `127.0.0.1:3091`
- `auth-api-prod` -> `127.0.0.1:3090`

## Bootstrap inicial no servidor

No servidor:

```bash
ssh root@45.179.88.173
cd /root
git clone https://github.com/allanRoberto/revesbot-final.git revesbot-bootstrap
bash /root/revesbot-bootstrap/infra/deploy/bootstrap-server.sh
```

Se preferir outro método de acesso ao repositório no servidor, ajuste `REPO_URL` antes de executar o script. O bootstrap faz:

- instala `git`, `nginx`, `python3`, `python3-venv`, `python3-pip`
- instala `nodejs` e `pm2` se faltarem
- cria os checkouts `develop` e `main`
- instala a configuração do Nginx

## Variáveis de ambiente

Exemplo mínimo para `/etc/revesbot/develop.env`:

```bash
API_PORT=8081
AUTH_API_PORT=3091
MONGO_URL=
REDIS_CONNECT=
BOOKMAKER_BASE_URL=
BOOKMAKER_ORIGIN=
BOOKMAKER_REFERER_BASE=
BOT_AUTOMATION_ENABLED=false
BOT_API_URL=
BOT_HEALTH_URL=
```

Exemplo mínimo para `/etc/revesbot/main.env`:

```bash
API_PORT=8080
AUTH_API_PORT=3090
MONGO_URL=
REDIS_CONNECT=
BOOKMAKER_BASE_URL=
BOOKMAKER_ORIGIN=
BOOKMAKER_REFERER_BASE=
BOT_AUTOMATION_ENABLED=false
BOT_API_URL=
BOT_HEALTH_URL=
```

Adicione também qualquer outra env já exigida por `apps/api` e `apps/auth_api`.

Variáveis opcionais úteis para o deploy:

```bash
NPM_CACHE_DIR=/var/cache/npm/revesbot-auth-api
PUPPETEER_CACHE_DIR=/var/cache/puppeteer
```

## Deploy manual

```bash
/var/www/revesbot-final/develop/infra/deploy/deploy.sh develop
/var/www/revesbot-final/main/infra/deploy/deploy.sh main
```

## Autodeploy via GitHub Actions

Workflows criados:

- `.github/workflows/deploy-develop.yml`
- `.github/workflows/deploy-main.yml`

Secret obrigatório no GitHub:

- `DEPLOY_SSH_KEY`: chave privada com acesso SSH ao servidor

Fluxo:

- push em `develop` atualiza `dev.revesbot.com.br` e `auth-dev.revesbot.com.br`
- push em `main` atualiza `api.revesbot.com.br` e `auth.revesbot.com.br`

## Nginx

Arquivo versionado:

- `infra/nginx/revesbot.conf`

Depois de instalar a configuração, valide:

```bash
nginx -t
systemctl reload nginx
```

## Observações

- O deploy usa `npm ci` e `npm run build` em `apps/auth_api`.
- O deploy reaproveita cache de npm e Puppeteer quando `NPM_CACHE_DIR` e `PUPPETEER_CACHE_DIR` estiverem disponíveis no servidor.
- O deploy cria ou reaproveita `.venv` na raiz de cada checkout para `apps/api`.
- O `ecosystem` do PM2 depende de `DEPLOY_STAGE=develop|main`.
- Certificados TLS podem ser adicionados depois com Certbot sobre os `server_name` já configurados.
