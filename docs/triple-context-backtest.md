# Backtest retrospectivo de trios

Interface: `https://api.revesbot.com.br/backtest-trios`, também acessível pela página de ranking. API: `POST /api/triple-context-backtest`.

```json
{
  "history_limit": 5000,
  "top_k": 13,
  "attempts": 3,
  "ordered": true,
  "direction": "forward",
  "prevent_overlapping_bets": false
}
```

- `history_limit`: de 6 a 50.000 resultados mais recentes da `pragmatic-auto-roulette`.
- `top_k`: primeiros 1 a 37 candidatos do ranking; padrão 13.
- `attempts`: de 1 a 100 giros após a entrada; padrão 3.
- `ordered`: ordem exata (`true`) ou qualquer ordem (`false`).
- `direction`: ranking à frente (`forward`, profundidade 20) ou atrás (`backward`, profundidade 10). A conferência do acerto sempre ocorre nos giros **posteriores** à entrada, inclusive usando o ranking de trás.
- `prevent_overlapping_bets`: quando `true`, uma nova aposta só pode começar depois que a anterior acertar ou consumir todas as tentativas; padrão `false`.

Os valores inteiros não aceitam texto, decimais ou booleanos. Campos desconhecidos são rejeitados.

## Execução e contagem

A consulta congela a versão ativa do catálogo e um limite superior de IDs do histórico. Lê os últimos N registros ordenando por `timestamp DESC, _id DESC`, inverte a sequência e passa a trabalhar cronologicamente. Em caso de menos resultados disponíveis, informa a quantidade efetivamente lida. Registros inválidos ou duplicados interrompem a execução; não há remoção silenciosa nem compressão do histórico.

Os gatilhos são os blocos **1–2–3, 4–5–6, 7–8–9…**. Um sinal começa depois do terceiro resultado de cada bloco. Sobras de um ou dois números no final ainda podem resolver sinais anteriores, mas não formam outro trio. Trios com números repetidos mantêm seu lugar na sequência e são identificados como não suportados pelo catálogo de combinações distintas.

O ranking é consultado em lote, preservando os pontos e o desempate já publicados. Para cada sinal, os primeiros K candidatos ficam congelados. Não se recalcula o ranking durante as tentativas ou no acompanhamento posterior. Um acerto exige o número exato entre esses K; vizinhos não ampliam o conjunto selecionado.

- **Vitória:** primeiro acerto observado entre a 1ª e a Tª tentativa. Mesmo perto do fim da amostra, um acerto já observado encerra o sinal.
- **Derrota:** T resultados observados sem nenhum dos K candidatos.
- **Sem desfecho:** o histórico terminou antes de T e ainda não houve acerto; não conta como derrota.
- **Trio repetido:** não há essa combinação no universo do catálogo.
- **Sem evidência:** a direção escolhida tem zero eventos de contexto. Não se usam os números em ordem de desempate de um ranking todo zerado como previsão.
- **Ignorado por sobreposição:** o trio formou um ranking válido, mas ainda havia uma aposta anterior ativa. Não inicia apostas e fica fora da assertividade e do financeiro.

A assertividade exibida é `vitórias / (vitórias + derrotas) × 100`. Sem entradas encerradas, fica indisponível, não 0%. Os demais estados são contados separadamente; nenhuma regra de superaquecimento, repetição de candidatos ou seleção de gatilhos é aplicada.

## Catálogo de qualidade dos rankings

Cada sinal com um trio válido recebe métricas derivadas exclusivamente dos dados já gravados no catálogo. Elas são diagnósticas: nesta etapa não excluem nem alteram nenhuma entrada.

- **Suporte:** ocorrências históricas do trio.
- **Cobertura completa:** `complete_occurrences / occurrences`.
- **Cobertura do contexto:** `context_events / (occurrences × depth)`.
- **Taxa direta do top K:** soma de `direct_hits` dos selecionados dividida pelos eventos de contexto.
- **Lift direto:** taxa direta do top K dividida por `K / 37`.
- **Concentração do score:** score do top K dividido pelo score dos 37 números.
- **Concentração relativa:** concentração do score dividida por `K / 37`.
- **Margem do corte:** diferença entre o score do candidato K e o K+1, dividida pelos eventos de contexto. Não existe no top 37.
- **Força do líder:** diferença entre primeiro e segundo colocados, também normalizada pelos eventos.
- **Dominância da ordem:** no modo sem ordem, maior contagem entre as seis permutações dividida pelas ocorrências totais.

O painel permite alternar entre suporte, cobertura, lift, concentração, margem e dominância. Para cada faixa mostra rankings formados, entradas encerradas, bloqueios por sobreposição, vitórias, derrotas, assertividade, saldo conforme a progressão financeira atual e maior sequência de derrotas. Rankings sem dados suficientes permanecem visíveis em uma faixa própria.

Cada linha da tabela de sinais também oferece os detalhes de qualidade do ranking correspondente. Rankings bloqueados por sobreposição continuam catalogados, mas não simulam uma aposta. Trios repetidos não possuem ranking e, portanto, não possuem métricas de qualidade.

## Depois da derrota

A ferramenta busca o primeiro acerto do **mesmo conjunto de K números** até o fim da amostra selecionada. A derrota original permanece derrota. O relatório mostra a tentativa total desde a entrada e quantos giros adicionais foram necessários depois de T.

Exemplo: T=3, candidatos `{4, 9}`, próximos resultados `7, 3, 12, 8, 9`. Resultado: **derrota** nas três tentativas; primeiro acerto na **5ª tentativa total**, **2 giros adicionais** depois do limite.

Sem acerto posterior observado, o relatório informa quantos giros adicionais foram acompanhados. Isso não significa que o conjunto nunca acertaria. Nenhum resultado além dos N selecionados é buscado para completar esse acompanhamento. O resumo mostra a distribuição das recuperações, perdas sem recuperação observada e a maior tentativa de recuperação encontrada.

Com `prevent_overlapping_bets=false`, as entradas são avaliadas separadamente e, se T for maior que três, seus períodos de conferência podem se sobrepor, embora os trios não se sobreponham. Com a opção ativa, um sinal aceito bloqueia os seguintes até o primeiro acerto ou a Tª tentativa. Um trio encerrado exatamente no giro que fecha a aposta anterior é aceito, pois sua aposta começa apenas no giro seguinte. Trios repetidos e sinais sem evidência não abrem apostas nem prolongam o bloqueio. Acerto tardio não altera a derrota nem entra no resultado financeiro dentro do limite configurado.

## Projeção financeira

A interface recebe um lucro líquido mínimo por sinal e monta uma progressão para o top K e o limite de tentativas escolhidos. A ficha é o valor apostado **em cada número** e sempre é arredondada para cima em múltiplos de R$ 0,50.

Para cada tentativa, considerando o pagamento de 35:1 mais a devolução da ficha vencedora:

`lucro líquido = 36 × ficha por número − exposição acumulada`

A menor ficha que satisfaz o lucro solicitado é escolhida depois de incluir todas as apostas perdidas nas tentativas anteriores. A tabela apresenta ficha por número, aposta total da tentativa, exposição acumulada e lucro líquido em caso de acerto. Cada novo sinal reinicia a progressão na primeira tentativa.

O painel posterior ao backtest aplica essa tabela somente aos sinais encerrados:

- vitória: usa o lucro da tentativa do primeiro acerto;
- derrota: desconta toda a exposição configurada;
- incompleto, trio repetido ou sem evidência: não entra no saldo.

O total apostado, saldo final, maior exposição por sinal e maior queda do saldo são calculados no navegador, sem alterar a API ou o catálogo. O gráfico acumula o resultado dos sinais em ordem cronológica. Como cada sinal é tratado separadamente, a soma não representa o capital simultaneamente necessário quando os períodos de conferência se sobrepõem.

Não existe progressão com lucro positivo para top K 36 ou 37: a aposta no conjunto consome todo ou mais que o retorno bruto de 36 vezes. Nesses casos o backtest estatístico permanece disponível, mas a projeção financeira informa a incompatibilidade. Progressões que ultrapassem o limite seguro de cálculo do navegador também são interrompidas com uma mensagem para reduzir top K, lucro ou tentativas.

## Natureza retrospectiva

Por escolha do usuário, a ferramenta usa o catálogo publicado atual. O catálogo pode conter resultados posteriores à decisão histórica. O relatório identifica a metodologia, o período/versão do catálogo e quantos sinais podem usar informação futura. Essa assertividade não é apresentada como validação preditiva fora da amostra.

Intervalos entre registros maiores que cinco minutos são informados, sem filtrar sinais. “Próximo giro” significa próximo registro disponível da mesa; giros ausentes não são reconstruídos.

## Operação

As consultas só leem as coleções de histórico e catálogo. Não gravam resultados nem alteram o catálogo. Há um limite de uma execução por processo da API e timeout de 50 segundos. Códigos de erro: 422 configuração inválida; 404 histórico/catálogo indisponível; 429 capacidade ocupada; 503 falha de banco ou integridade; 504 timeout. A interface mantém a paginação apenas na apresentação; os totais consideram todos os sinais retornados.
