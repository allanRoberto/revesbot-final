# Ranking por similaridade contextual

Página `/ranking-similaridade-contextual`, derivada de
`/analise-similaridade-contextual`. O cálculo sai do navegador e passa para o
worker `contextual-ranking-worker` (`apps/contextual_ranking`), para que o
ranking esteja pronto a qualquer hora e cada resultado seja conferido.

## Regra

Mesa fixa: `pragmatic-brazilian-roulette`. A cada resultado X:

1. **Conferência:** X é comparado com o top 7 que estava no ar (1 sinal por
   giro, 1 tentativa; acerto = número exato no top 7).
2. **Busca de X:** os 9 resultados até X viram contexto (5) e sequência (4).
   A consulta à busca vetorial interna (`POST /search`) usa exatamente os
   parâmetros da página original, mais `cutoff` igual ao horário de X, para que
   nenhuma busca enxergue dados posteriores.
3. **Janela:** ficam as buscas dos 5 últimos resultados. As ocorrências de cada
   busca são ordenadas pela ordem da tabela da página original
   (`occurrenceOrder`), mesmo abaixo do corte de 30%. Os resultados que saíram
   depois da busca contam como "ao vivo", e o critério dos números clicados
   não existe no worker. Entram as 4 primeiras de cada busca.
4. **Ranking:** os 5 posteriores das 20 ocorrências (até 100 números) dão
   10 pontos ao próprio número e 8 a cada vizinho físico. O top 7 vai para a
   página.

**Tratamento de falhas:**
- Uma busca que falha fica fora do ranking e é refeita no giro seguinte (até 3
  tentativas no total).
- Se o worker ficar mais de 5 resultados atrasado, a janela é reconstruída sem
  gerar sinais para o intervalo, porque não havia ranking no ar.

**Paridade:** `rules.py` é uma tradução literal de
`static/js/core/contextual-similarity-model.js` e das funções de ordenação de
`static/js/pages/contextual-similarity.js`. O teste
`tests/test_contextual_rules_parity.py` executa o JavaScript da página com
Node e exige resultados idênticos em 300 tabelas aleatórias e numa tabela
real de produção.

## Armazenamento

| Onde | O quê |
| --- | --- |
| MongoDB `history` | leitura dos resultados com a credencial somente leitura da API |
| Redis `contextual_ranking:v1:state:*` | estado do motor (cursor, 13 resultados, 5 buscas) |
| Redis `contextual_ranking:v1:view:*` | o que a página mostra |
| Redis `contextual_ranking:v1:heartbeat:*` | saúde do worker e da fila do MongoDB |
| Redis `contextual_ranking:v1:history:*` | últimos 500 sinais (a página mostra 50) |
| Redis `contextual_ranking:v1:summary:*` | totais de sinais, acertos e erros |
| Redis `contextual_ranking:v1:mongo-outbox:*` | fila de sinais a gravar no MongoDB (até 20 mil) |
| MongoDB `contextual_ranking_signals_v1` | histórico permanente, um documento por resultado |

O documento permanente guarda:
- o resultado;
- o giro que gerou o ranking;
- o top 7, se acertou e a posição;
- o ranking dos 37 com pontos;
- as ocorrências usadas de cada busca.

A gravação usa `_id` igual ao id do resultado, o que a torna idempotente.

## Operação

- **Processo PM2:** `contextual-ranking-worker`, definido em
  `infra/pm2/api-minimal.config.js` e iniciado pelo deploy da API. O
  healthcheck do deploy não depende dele, e o rollback o remove quando o
  release anterior não o tinha.
- **Variáveis:**
  - `VECTOR_API_TOKEN`, sem a qual o worker fica em "configuração pendente";
  - `VECTOR_SEARCH_URL`, com padrão `http://127.0.0.1:8037`;
  - `CONTEXTUAL_RANKING_MONGO_URL`, sem a qual os sinais esperam na fila do Redis;
  - `CONTEXTUAL_RANKING_POLL_SECONDS`.
- **Configuração inicial, como root e uma vez:**
  `sudo bash /var/www/revesbot/api-current/infra/deploy/api/provision-contextual-ranking.sh`.
  O script cria o usuário `revesbot_api_contextual_prod`, que só grava na
  coleção do histórico, copia `VECTOR_API_TOKEN` de
  `/etc/revesbot-vector/staging.env` e recarrega o worker.
- **API:**
  - `GET /api/ranking-similaridade-contextual?limit=50` lê só o Redis.
  - Status do worker: `online` (heartbeat até 20 s), `atrasado` (até 90 s),
    `offline` ou `configuracao_pendente`.
