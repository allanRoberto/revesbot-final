# Pares do ranking por similaridade contextual

Página `/ranking-similaridade-pares`, no mesmo layout de `/ranking-similaridade-contextual`
(`docs/design/ranking-similaridade-contextual.md`). O worker `contextual-pairs-worker`
(`apps/contextual_pairs`) gera o mesmo ranking de 7 números da página de ranking, mas a aposta
deixa de ser esses 7 números: ela é montada a partir do par de números de 0 a 9 do ranking.

## Regra

Mesa fixa: `pragmatic-brazilian-roulette`. A cada resultado, o ranking é calculado pelo motor do
ranking (`contextual_ranking.engine`, importado, sem cópia): busca do resultado, 4 primeiras
ocorrências de cada uma das buscas dos 5 últimos giros e soma das 3 colunas, com o top 7. Depois:

1. **Par:** os números de 0 a 9 do top 7 são as bases. Com exatamente 2, formam o par. Com
   menos de 2 não há par, e com 3 ou mais o ranking é ignorado. O par 6 e 9 é uma exceção da
   estratégia e também é ignorado (`IGNORED_PAIRS` em `apps/contextual_pairs/rules.py`).
2. **Grupo de cada base:** terminais (mesmo último dígito), espelho da própria base (lista fixa
   1-10, 2-20, 3-30, 6-9, 12-21, 13-31, 14-34, 16-19, 23-32, 26-29) e números cuja soma dos
   dígitos, reduzida a um dígito, é a base.
3. **Interseção:** fica o número de um grupo que é vizinho, na roda, de um número do outro grupo
   (um número que está nos dois grupos também fica).
4. **Aposta:** os números que ficaram mais 1 vizinho de cada lado, mais os dois números do par,
   sem os vizinhos deles (`INCLUDE_PAIR_NUMBERS`). Dos 45 pares possíveis, só 0 e 7, e 0 e 9, não
   formam aposta (não há interseção); esses rankings também são ignorados.
5. **Conferência:** a aposta fica congelada e é conferida nos 7 resultados seguintes. O primeiro
   número dentro dela encerra o sinal como acerto (registrando a rodada). Sete rodadas sem acerto
   encerram como erro. O acerto é pela aposta do par, não pelos 7 números do ranking.
6. **Par ativo:** enquanto um sinal de um par está aberto, o mesmo par (3 e 7 é igual a 7 e 3)
   não abre outro sinal; só um par diferente abre. Quando o sinal encerra, o par é liberado, e o
   ranking calculado logo depois do resultado que o encerrou já pode abri-lo de novo.

Exemplo (3 e 7): grupo do 3 = 3, 13, 23, 33, 30, 12, 21; grupo do 7 = 7, 17, 27, 16, 25, 34. Ficam
13 (vizinho do 27), 33 (vizinho do 16), 27 (vizinho do 13) e 16 (vizinho do 33). Aposta: 6, 27, 13,
36 e 24, 16, 33, 1, mais o 3 e o 7 sozinhos (10 números).

A página mostra a aposta em trechos de casas vizinhas na roda: os números cheios são a interseção,
os mais claros são os vizinhos e o contorno dourado marca os dois números do par.

## Estados do ranking na tela

| Estado | Significado |
| --- | --- |
| `opened` | o par estava livre e abriu um sinal |
| `active` | o par já tem um sinal em andamento; nada novo abre |
| `ignored` | par listado como exceção (hoje, 6 e 9); nada abre |
| `no_pair` | menos de 2 números de 0 a 9 |
| `too_many` | 3 ou mais números de 0 a 9 (ignorado) |
| `no_intersection` | par sem interseção (0 e 7, ou 0 e 9) |

O ✓/✗ dos 3 últimos resultados diz se o número estava na aposta do par que estava na tela; `–`
quando não havia aposta na tela.

## Armazenamento

| Onde | O quê |
| --- | --- |
| MongoDB `history` | leitura dos resultados com a credencial somente leitura da API |
| Redis `contextual_pairs:v1:state:*` | estado do motor (inclui os sinais abertos) |
| Redis `contextual_pairs:v1:view:*` | o que a página mostra |
| Redis `contextual_pairs:v1:heartbeat:*` | saúde do worker e da fila do MongoDB |
| Redis `contextual_pairs:v1:history:*` | últimos 500 sinais encerrados (a página mostra 50, com os abertos no topo) |
| Redis `contextual_pairs:v1:summary:*` | totais de sinais encerrados e contadores dos rankings por estado |
| Redis `contextual_pairs:v1:mongo-outbox:*` | fila de sinais encerrados a gravar no MongoDB (até 20 mil) |
| MongoDB `contextual_ranking_signals_v1` | histórico permanente, um documento por sinal encerrado |

Os sinais dos pares usam a mesma coleção dos sinais do ranking, com `strategy: "pairs"`,
`strategy_version: "pairs-1"` e `_id` `pairs-1-<id do giro>`. Assim o usuário do Mongo que já existe
(`revesbot_api_contextual_prod`) basta, e nada muda no servidor. O documento guarda o giro que gerou o
ranking, o top 7, o par, os números mantidos, a aposta, cada rodada conferida, a rodada do acerto e o
ranking completo com as ocorrências usadas.

## Operação

- **Processo PM2:** `contextual-pairs-worker`, em `infra/pm2/api-minimal.config.js`. Usa as mesmas
  variáveis do worker do ranking: `VECTOR_API_TOKEN`, `VECTOR_SEARCH_URL`,
  `CONTEXTUAL_RANKING_MONGO_URL`. Também lê `CONTEXTUAL_PAIRS_POLL_SECONDS` (padrão 1 s).
- **Dois workers, duas buscas por giro:** cada worker faz a sua própria busca vetorial por resultado.
- **Versão da regra:** `PAIRS_VERSION` em `apps/contextual_pairs/__init__.py` entra nas chaves do Redis;
  mudar a regra e subir a versão faz os totais recomeçarem do zero. A mudança de 16/11/2026 (abaixo)
  foi feita de propósito dentro da versão 1, para manter o histórico na página.
- **API:** `GET /api/ranking-similaridade-pares?limit=50` lê só o Redis. Status do worker: `online`
  (heartbeat até 20 s), `atrasado` (até 90 s), `offline` ou `configuracao_pendente`.
- **Falhas:** igual ao worker do ranking. Uma busca que falha é refeita nos giros seguintes; se o worker
  ficar mais de 5 resultados atrasado, os sinais abertos são conferidos com os resultados do intervalo
  (até 100) e a janela é reconstruída; sem Mongo configurado ou com ele fora do ar, os sinais esperam
  na fila do Redis.

## Mudança de regra de 16/11/2026 e correção dos dados

Duas decisões do usuário, aplicadas dentro da versão 1 (o histórico continua na página):

1. Os dois números do par entram na aposta, sem os vizinhos deles.
2. O par 6 e 9 é uma exceção da estratégia: não abre sinal e não é contado.

Os dados já gravados foram corrigidos à mão, sem refazer o histórico:

- **Par 4 e 8** (`pairs-1-6afa81f19bbdd4d1f600b25a`, gatilho 04:09:21 UTC): o 8 saiu na 2ª rodada e
  não estava na aposta antiga. O sinal passou de erro para acerto na 2ª rodada, com a aposta nova
  (4, 6, 8, 9, 17, 18, 22, 25, 29, 34) e a conferência encerrada nessa rodada. Os valores antigos
  ficam no próprio documento, em `correction.previous`.
- **Par 0 e 4** (`pairs-1-6afa87ed9bbdd4d1f600b465`, gatilho 04:34:53 UTC): o 4 saiu na 1ª rodada e
  não estava na aposta antiga. Mesmo tratamento do 4 e 8: acerto na 1ª rodada, com a aposta nova
  (0, 1, 4, 14, 20, 31). O sinal do par 0 e 1 (`pairs-1-6afa892b9bbdd4d1f600b4d2`) já tinha
  fechado como acerto (36, na 4ª rodada) e não foi alterado.
- **Par 6 e 9** (`pairs-1-6afa815b9bbdd4d1f600b229`): o documento continua no MongoDB com
  `excluded: true` e `excluded_reason` (o usuário de escrita não tem permissão de apagar). Ele saiu
  do histórico e dos contadores no Redis. Análises feitas direto no Mongo devem filtrar
  `excluded != true`.

Os demais sinais não foram recalculados: os já encerrados mantêm a aposta e o resultado com que
fecharam (o erro do par 7 e 9, por exemplo, continua: nem o 7 nem o 9 saíram nas 7 rodadas), e os
abertos no momento do deploy seguem com a aposta com que abriram. Também não foi simulado o efeito
de liberar o par 4 e 8 (e o 0 e 4) algumas rodadas mais cedo.
