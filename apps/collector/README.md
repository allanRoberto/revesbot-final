# Collector Pragmatic

Worker continuo que recebe resultados via WebSocket da Pragmatic, grava no
MongoDB e publica o contrato `new_result` no Redis.

## Execucao

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python main.py
```

As variaveis `MONGO_URL` e `REDIS_CONNECT` sao obrigatorias. Para validacao no
novo servidor use `MONGO_DATABASE=roleta_db_collector_test`, mantendo os dados
de teste isolados do futuro banco de producao.

## Observabilidade

- `GET /health/live`: processo HTTP ativo.
- `GET /health/ready`: dependencias, WebSocket e resultados recentes.
- `GET /metrics`: metricas Prometheus.

## Multiplicadores

Resultados de mesas como Mega Roulette preservam o mapa `slots` recebido da
Pragmatic. `winning_multiplier` recebe o valor associado ao numero sorteado ou
`null` quando nenhum multiplicador pagou naquela rodada.

```json
{
  "value": 2,
  "slots": {"1": 100, "16": 100, "2": 100},
  "winning_multiplier": 100
}
```

## Recuperacao apos interrupcao

Durante a operacao normal somente `last20Results[0]` e tratado. Na primeira
mensagem de cada mesa apos iniciar ou reconectar, o collector compara os
`gameId` recebidos com os 20 registros mais recentes do MongoDB:

- com um ID em comum, insere somente a lacuna posterior a ele;
- sem registros anteriores, salva apenas o resultado mais recente;
- sem nenhum ID em comum, preserva os 20 disponiveis e registra um alerta de
  janela de recuperacao esgotada.

Os resultados recuperados sao ordenados do mais antigo para o mais novo e usam
o horario original informado no campo `time` de cada item do WebSocket. Eles
recebem `recovered=true`, `timestamp_source=provider` e `captured_at` com o
instante da recuperacao. Se o provedor excepcionalmente omitir ou invalidar o
horario, o collector registra um alerta e usa o instante da captura com
`timestamp_source=captured_fallback`; nenhuma estimativa por mediana e feita.
Resultados recuperados nao sao publicados no canal de eventos ao vivo.

O watchdog interno encerra o processo quando a captura fica obsoleta. O PM2
reinicia a aplicacao e um timer externo fornece uma segunda camada de defesa.
