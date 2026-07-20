# Operacao do motor orbital

## Dependencias analiticas

As dependencias sao separadas do runtime legado:

```bash
.venv/bin/pip install -r apps/signals/orbit_engine/requirements.orbit.txt
```

O acesso ao MongoDB usa somente `MONGO_URL`/`mongo_url` do ambiente ou `.env`.
Artefatos locais ficam em `.orbit-data/`, ignorado pelo Git.

## Snapshot e avaliacao

```bash
PYTHONPATH=apps:. .venv/bin/python -m apps.signals.orbit_engine.cli \
  snapshot pragmatic-auto-roulette

# Recorte reproduzivel dos 25 mil registros mais recentes para iteracao rapida
PYTHONPATH=apps:. .venv/bin/python -m apps.signals.orbit_engine.cli \
  snapshot pragmatic-auto-roulette --maximum-records 25000

PYTHONPATH=apps:. .venv/bin/python -m apps.signals.orbit_engine.cli \
  replay .orbit-data/snapshots/ARQUIVO.jsonl.gz --maximum 5000

PYTHONPATH=apps:. .venv/bin/python -m apps.signals.orbit_engine.cli \
  ablation .orbit-data/snapshots/ARQUIVO.jsonl.gz --maximum 2000

PYTHONPATH=apps:. .venv/bin/python -m apps.signals.orbit_engine.cli \
  train .orbit-data/snapshots/ARQUIVO.jsonl.gz \
  --max-train 20000 --max-validation 5000 --max-test 5000
```

O snapshot congela a fronteira superior da consulta e grava JSONL comprimido,
manifesto, contagens, periodo e SHA-256. Replay, ablacacao e treino preservam a
ordem cronologica.

## API de inspecao

- `GET /api/orbit/number/{number}?pivot=19`: atributos e relacao com o pivo.
- `GET /api/orbit/analyze/{roulette_id}`: analisa o ultimo estado conhecido.
- `GET /api/orbit/suggestions?roulette_ids=id1,id2`: consolida os tres ultimos
  pivos de cada mesa em rankings Top 9 e Top 12. O padrao usa 6 ocorrencias por
  pivo, uma janela de consulta de 600 giros e pesos 1,00, 0,85 e 0,70.
- `GET /api/orbit/performance?roulette_ids=id1,id2`: calcula no servidor as
  curvas cumulativas da 1a ate a 10a tentativa para Top 9 e Top 12. Retorna os
  recortes de 1, 3, 6, 12 e 24 horas, o acumulado geral e o melhor horario por
  roleta no fuso `America/Sao_Paulo`.
- `GET /api/orbit/history?roulette_ids=id1,id2&limit=20`: retorna as previsoes
  prospectivas mais recentes de cada mesa, os Top 9/Top 12 congelados, as
  tentativas observadas e o horario do primeiro acerto de cada lista.
- `POST /api/orbit/analyze-history`: executa uma sequencia fornecida em ordem
  cronologica.

`persist=true` grava a resposta em `orbit_predictions`; o padrao e nao persistir.

No aplicativo web, `/orbit` apresenta uma carta por roleta e consulta a rota
autenticada `/api/orbit-suggestions`. O painel atualiza a cada 15 segundos e
mantem a rotulagem **shadow mode**, pois o resultado ainda e observacional. Cada
carta possui as abas **Atual** e **Historico**; o numero ancora de uma previsao
abre a comparacao detalhada entre o ranking congelado e os dez giros seguintes.

## Worker shadow

O worker fica desligado por padrao. Variaveis:

```dotenv
ORBIT_SHADOW_ENABLED=1
ORBIT_ROULETTE_IDS=pragmatic-auto-roulette,pragmatic-brazilian-roulette,pragmatic-immersive-roulette-deluxe
ORBIT_HISTORY_LIMIT=600
ORBIT_HORIZON=3
ORBIT_MAX_ATTEMPTS=10
ORBIT_POLL_SECONDS=2
```

Por padrao, a configuracao PM2 inclui `orbit-shadow-{dev|prod}`. O processo
observa novos giros, congela cada sugestao e registra os dez resultados
posteriores em `orbit_prediction_trials`. Somente previsoes com a janela inteira
concluida entram nas porcentagens, mantendo o mesmo denominador nas dez
tentativas. Ele grava `shadow_only=true` e `publishes_betting_signal=false`; nao
publica no Redis.

O melhor horario usa o Top 9 acumulado ate a terceira tentativa, agrupado pela
hora de Brasilia. A ordenacao usa o limite inferior de Wilson para reduzir a
preferencia artificial por horarios com poucas amostras; enquanto houver menos
de 30 janelas no horario, a interface marca a recomendacao como provisoria.

Para desativar, use `ORBIT_SHADOW_ENABLED=0` e recarregue o ecosystem PM2. A
colecao de previsoes pode ser mantida para avaliacao prospectiva sem afetar os
demais workers.

## Estrategias de gatilho

O servico `apps/monitoring/orbit_triggers/worker.py` monitora sete regras
prospectivas sobre as sugestoes congeladas. Todas usam cinco tentativas e
persistem candidatos e entradas separadamente. Consulte `docs/orbit-triggers.md`
para as regras, garantias de idempotencia, endpoints e paginas individuais.
