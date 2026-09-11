# Behavior Lab v1

O Behavior Lab observa uma única mesa, mantém o estado causal das formações e
publica um retrato auditável para a API mínima. Ele é um laboratório de análise:
os sinais representam hipóteses mensuráveis, não garantia de resultado ou de
retorno financeiro.

## Escopo fixo da v1

A configuração versionada fica em
`apps/behavior_lab/config/default_v1.json` e fixa:

- mesa `pragmatic-auto-roulette`;
- contexto inicial de 500 resultados;
- horizonte máximo de 10 jogadas;
- namespace Redis `behavior_lab:v1`.

O worker aceita `BEHAVIOR_LAB_CONFIG` como caminho para um documento de
configuração completo e validado. A v1 rejeita outra mesa ou horizonte, evitando
que API, worker e healthcheck operem com contratos diferentes.

## Arquitetura

O processo `revesbot-api` continua servindo o histórico, o WebSocket e as rotas
HTTP. Um segundo processo PM2, com uma única instância chamada
`revesbot-behavior-lab`, executa `apps/behavior_lab/__main__.py worker` no mesmo
release e no mesmo `.venv` da API.

O fluxo em produção é:

1. o worker carrega o contexto pela API local;
2. usa o WebSocket local como notificação de baixa latência;
3. a cada notificação (e também periodicamente), reconcilia o histórico
   persistido e processa somente o sufixo novo em ordem cronológica;
4. persiste estado, sinais, snapshot e heartbeat no Redis local;
5. a API lê essas projeções, sem executar o motor analítico dentro das
   requisições HTTP.

As chaves da mesa são:

```text
behavior_lab:v1:pragmatic-auto-roulette:health
behavior_lab:v1:pragmatic-auto-roulette:snapshot
behavior_lab:v1:pragmatic-auto-roulette:signals
behavior_lab:v1:pragmatic-auto-roulette:state
```

O documento `health` contém, entre outros campos, `status`, `heartbeat_at`,
`last_event_at`, `ws_connected`, `release_id`, `worker_instance_id` e eventuais
erros. O estado persistido permite
retomar o processamento sem transformar resultados anteriores em previsões
retroativas.

As projeções `state`, `snapshot` e `signals` são atualizadas numa única
transação Redis e usam a mesma revisão. O worker mantém 500 sinais resolvidos
detalhados; os anteriores são compactados em contadores cumulativos, preservando
as métricas sem crescimento ilimitado do estado.

## Rotas

- `GET /patterns/behavior-lab`: painel operacional;
- `GET /api/patterns/behavior-lab/live`: snapshot atual;
- `GET /api/patterns/behavior-lab/signals`: sinais registrados;
- `GET /api/patterns/behavior-lab/health`: saúde e heartbeat do worker;
- `POST /api/patterns/behavior-lab/backtest`: replay causal sob demanda.

O backtest HTTP aceita no máximo 2.000 resultados, devolve apenas o resumo e
aplica exclusão mútua mais um intervalo global de 30 segundos entre execuções.
Esses limites protegem CPU e MongoDB; a CLI continua disponível para análises
administrativas maiores.

A API pode responder enquanto o worker está iniciando. Os estados públicos são
`starting`, `healthy`, `degraded`, `stale`, `stale_release`, `stopped` e
`unavailable`; a automação de deploy exige `healthy`, WebSocket conectado,
heartbeat recente e o identificador exato do release ativo.

O painel só libera `ENTRAR` quando o estado é `healthy` e o heartbeat tem no
máximo 90 segundos, pertence ao release da API e tem a mesma revisão do
snapshot. Nos demais estados, inclusive durante uma reconciliação sem
WebSocket, a sugestão pública é suprimida e aparece como `AGUARDANDO`.

## Execução local

Crie um ambiente Python compartilhado pela API e pelo laboratório:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install \
  -r apps/api/requirements-minimal.txt \
  -r apps/behavior_lab/requirements.txt \
  pytest
```

Com API e Redis locais disponíveis, execute o worker a partir da raiz:

```bash
export PYTHONPATH="$PWD:$PWD/apps"
export BEHAVIOR_LAB_CONFIG="$PWD/apps/behavior_lab/config/default_v1.json"
export BEHAVIOR_LAB_API_BASE_URL="http://127.0.0.1:8082"
export BEHAVIOR_LAB_WS_URL="ws://127.0.0.1:8082/ws?slug=pragmatic-auto-roulette"
export BEHAVIOR_LAB_REDIS_URL="redis://127.0.0.1:6380/0"
.venv/bin/python apps/behavior_lab/__main__.py worker
```

Para replay sem publicar estado no Redis, use uma fonte por vez:

```bash
PYTHONPATH="$PWD:$PWD/apps" .venv/bin/python -m behavior_lab backtest \
  --api --limit 5000
PYTHONPATH="$PWD:$PWD/apps" .venv/bin/python -m behavior_lab backtest \
  --file resultados.json --input-order newest-first --output relatorio.json
```

O bootstrap ao vivo consulta
`/history/pragmatic-auto-roulette?limit=500`, utiliza os identificadores dos
itens para eliminar somente retransmissões reais e inverte a resposta
`newest-first` antes de entregá-la ao motor cronológico.

Variáveis operacionais opcionais:

- `BEHAVIOR_LAB_RECONCILE_INTERVAL_SECONDS`, padrão 30;
- `BEHAVIOR_LAB_LOG_LEVEL`, padrão `INFO`.

Execute os testes e a compilação estática com:

```bash
PYTHONPATH="$PWD:$PWD/apps" .venv/bin/python -m pytest -q \
  apps/behavior_lab/tests \
  apps/api/tests/test_behavior_lab_routes.py
PYTHONPATH="$PWD:$PWD/apps" .venv/bin/python -m compileall -q \
  apps/behavior_lab apps/api/minimal_main.py apps/api/routes/behavior_lab.py
```

## Deploy e rollback

O workflow da API instala os dois arquivos de dependências, compila os módulos e
executa os testes do laboratório, das rotas e da API mínima. O driver estável
mantém um repositório bare privado de root, valida que o SHA pertence a
`origin/main` e executa o `deploy.sh` extraído do próprio commit solicitado;
assim, as garantias novas de validação e rollback já valem na mesma publicação
que as introduz. Cada release é extraído desse repositório para uma área de
staging, validado e então selado como `root:root`, sem permissão de escrita para
o usuário da aplicação. Somente depois disso o link `api-current` é trocado e o
PM2 recebe `startOrReload`.

O contrato `infra/deploy/api/DRIVER_CONTRACT` impede que o driver privilegiado
execute versões antigas do mecanismo de deploy. Se workflows terminarem fora
de ordem, um SHA ancestral é ignorado quando um descendente selado já está
ativo, evitando downgrade acidental. A primeira adoção do driver exige a
instalação administrativa única de `driver.sh`, `watchdog.sh` e da unit
atualizada antes do primeiro rollout automatizado.

O worker usa exclusivamente endpoints de loopback e o Redis indicado por
`REDIS_CONNECT` no ambiente da API. O PM2 aplica reinício automático com backoff
exponencial e concede até 15 segundos para encerramento gracioso.

O healthcheck de deploy faz, em uma única sequência de tentativas limitada:

- leitura real da rota de histórico da mesa;
- leitura de `/api/patterns/behavior-lab/health`;
- confirmação de que o processo PM2 possui PID ativo;
- confirmação de que API e Redis publicam o fingerprint da configuração ativa;
- confirmação direta de que o heartbeat Redis tem no máximo 90 segundos.

Se a carga do PM2 ou a saúde conjunta falhar, `api-current` volta ao release
anterior. Como `startOrReload` não remove processos ausentes do arquivo antigo, o
rollback também apaga `revesbot-behavior-lab` quando o release anterior ainda não
possuía esse worker, evitando um processo órfão. O dump do PM2 é salvo novamente
depois da restauração.

O watchdog externo é instalado em `/usr/local/sbin` e pertence a root. Ele não
executa scripts do release como root: em releases selados, pode reaplicar a
configuração PM2 imutável como usuário `revesbot`, inclusive para recriar um
worker removido, e salva novamente a lista do PM2. Em releases legados, limita-se
a reiniciar processos já registrados. Ele faz uma verificação por minuto e,
após duas falhas consecutivas, aplica um intervalo mínimo de 15 minutos entre
recuperações para não amplificar uma indisponibilidade externa de MongoDB ou
Redis. O backoff interno do PM2 continua sendo a primeira proteção contra queda
do processo. Os logs de ambos são rotacionados diariamente por
`infra/logrotate/revesbot-api`.

## Verificação operacional

No host da aplicação:

```bash
curl -fsS http://127.0.0.1:8082/api/patterns/behavior-lab/health
sudo -u revesbot env PM2_HOME=/home/revesbot/.pm2 pm2 status
sudo -u revesbot env PM2_HOME=/home/revesbot/.pm2 \
  pm2 logs revesbot-behavior-lab --lines 100
```

Um processo `online` sem heartbeat recente não é considerado saudável. Em caso
de `degraded`, examine primeiro `error`, `last_event_at` e `ws_connected`; a
reconciliação HTTP pode manter o estado consistente durante uma reconexão breve
do WebSocket.
