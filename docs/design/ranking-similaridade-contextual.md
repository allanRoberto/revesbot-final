# Ranking por similaridade contextual

Página `/ranking-similaridade-contextual`, derivada de
`/analise-similaridade-contextual`. O cálculo sai do navegador e passa para o
worker `contextual-ranking-worker` (`apps/contextual_ranking`), para que o
ranking esteja pronto a qualquer hora e cada resultado seja conferido.

## Regra

Mesa fixa: `pragmatic-brazilian-roulette`. A cada resultado X:

1. **Conferência:** X é comparado com cada sinal aberto. Cada ranking abre um
   sinal com seu top 7 congelado, conferido nos 7 resultados seguintes. O
   primeiro acerto (número exato no top 7) encerra o sinal e registra a rodada;
   7 rodadas sem acerto encerram como erro. Como nasce um sinal por giro, até 7
   sinais correm ao mesmo tempo. O ✓/✗ da tela principal continua dizendo se X
   estava entre os 7 números da tela.
2. **Busca de X:** os 9 resultados até X viram contexto (5) e sequência (4).
   A consulta à busca vetorial interna (`POST /search`) usa exatamente os
   parâmetros da página original, mais `cutoff` igual ao horário de X, para que
   nenhuma busca enxergue dados posteriores.
3. **Janela:** ficam as buscas dos 5 últimos resultados. As ocorrências de cada
   busca são ordenadas pela ordem da tabela da página original
   (`occurrenceOrder`), mesmo abaixo do corte de 30%. Os resultados que saíram
   depois da busca contam como "ao vivo", e o critério dos números clicados
   não existe no worker. Entram as 4 primeiras de cada busca.
4. **Ranking:** todos os números das 3 colunas das 20 ocorrências entram na
   conta: Anterior (5), Sequência (4) e Posterior (5), até 280 números.
   - Repetições contam de novo.
   - Também contam os números iguais ao contexto atual e à sequência buscada.
   - Uma coluna inválida fica de fora, por exemplo um Anterior incompleto.
   - Cada número dá 10 pontos a si e 8 a cada vizinho físico, com o mesmo
     desempate da página.
   - O top 7 vai para a página e vira o sinal novo.

**Tratamento de falhas:**
- Uma busca que falha fica fora do ranking e é refeita no giro seguinte (até 3
  tentativas no total).
- Se o worker ficar mais de 5 resultados atrasado, os sinais abertos são
  conferidos com os resultados do intervalo (até 100). Depois a janela é
  reconstruída, sem abrir sinais para o intervalo, porque não havia ranking
  no ar.

**Versões da regra** (cada uma usa as chaves Redis
`contextual_ranking:v<versão>:*`, então seus totais começam do zero):

| `strategy_version` | Colunas do ranking | Conferência do sinal |
| --- | --- | --- |
| 1 | só Posterior | 1 resultado |
| 2 | só Posterior | até 7 resultados |
| 3 (atual) | Anterior, Sequência e Posterior | até 7 resultados |

**Paridade:** `rules.py` é uma tradução literal de
`static/js/core/contextual-similarity-model.js` e das funções de ordenação de
`static/js/pages/contextual-similarity.js`. O teste
`tests/test_contextual_rules_parity.py` executa o JavaScript da página com
Node e exige resultados idênticos em 300 tabelas aleatórias e numa tabela
real de produção. Ele compara a ordem e o `rankFollowing` da página.
`rank_columns`, que soma as 3 colunas, é uma regra do worker e não existe
na página.

## Armazenamento

| Onde | O quê |
| --- | --- |
| MongoDB `history` | leitura dos resultados com a credencial somente leitura da API |
| Redis `contextual_ranking:v3:state:*` | estado do motor (cursor, 13 resultados, 5 buscas, sinais abertos) |
| Redis `contextual_ranking:v3:view:*` | o que a página mostra, incluindo os sinais em andamento |
| Redis `contextual_ranking:v3:heartbeat:*` | saúde do worker e da fila do MongoDB |
| Redis `contextual_ranking:v3:history:*` | últimos 500 sinais encerrados (a página mostra 50, com os abertos no topo) |
| Redis `contextual_ranking:v3:summary:*` | totais de sinais encerrados, acertos e erros |
| Redis `contextual_ranking:v3:mongo-outbox:*` | fila de sinais encerrados a gravar no MongoDB (até 20 mil) |
| MongoDB `contextual_ranking_signals_v1` | histórico permanente, um documento por sinal encerrado |

O documento permanente das versões 2 e 3 é gravado quando o sinal encerra e guarda:
- o giro que gerou o ranking (`built_after`);
- o top 7 congelado;
- cada rodada conferida;
- se acertou, em qual rodada e em qual posição;
- o ranking dos 37 com pontos;
- as ocorrências usadas de cada busca.

A gravação usa `_id` `v<versão>-<id do giro>`, o que a torna idempotente e não colide
com os documentos da versão 1 (cujo `_id` é o id do resultado).

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
