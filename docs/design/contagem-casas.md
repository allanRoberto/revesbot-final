# Contagem de casas

## Escopo e decisões confirmadas

Página `/contagem-casas?slug=pragmatic-auto-roulette`, na API FastAPI/Jinja existente.
O usuário autorizou a implementação e definiu: usar até 1.000 resultados, o layout
de `/history/pragmatic-brazilian-roulette`, análise na barra lateral em lugar do
histórico de ocorrências, múltiplas seleções e resumo dos números repetidos.

Cada clique identifica uma ocorrência concreta, permitindo comparar duas
ocorrências do mesmo número. O histórico é exibido do mais recente para o mais
antigo. Para a ocorrência de índice `i`, procurar o primeiro `j > i` com o mesmo
número. A base é o número selecionado e a quantidade de casas é `items[j - 1].value`,
o resultado que saiu imediatamente depois daquela ocorrência anterior.

## Elementos e comportamento

1. Cabeçalho e seletor: reaproveitam o tema, o diálogo de mesas, status ao vivo,
   escolha de colunas, tema e cópia do histórico. Trocar de mesa limpa as seleções.
2. Grade: reaproveita cartões e cores de `/history`, com seleção múltipla por
   ocorrência, `aria-pressed`, borda e marcador. Um segundo clique retira a seleção.
3. Barra lateral: cada cartão mostra horário selecionado e anterior, par, base,
   casas, race, setores e aposta crescente. Fechar mantém seleções; Limpar retira
   todas. Desktop usa barra à direita; celular usa o painel inferior com rolagem
   existente, ampliado para acomodar a race. Escape fecha e devolve foco.
4. Race: usa `RouletteRacetrack` existente sem alterar o plugin. Azul identifica
   esquerda, amarelo direita, lilás sobreposição, borda tracejada a base. Os
   centros e o deslocamento estão identificados também em texto. Uma lista
   expansível mostra a contagem completa em cada sentido, começando pela base.
5. Resumo: repetições contam presença entre apostas, uma vez por aposta. Exibe
   frequência decrescente, com desempate pelo número, e união geral crescente.

Não existe exigência de dez números distintos nesta interface: setores
sobrepostos são apresentados com sua quantidade real, incluindo casas zero.
Sem ocorrência anterior nos 1.000, mostrar mensagem e não criar aposta.
Erros de rede têm mensagem e botão Atualizar; respostas antigas de outra mesa
são ignoradas. Resultados ao vivo mantêm a seleção por ID e o cálculo do clique
como snapshot, sem mudar o par de uma seleção quando novos resultados chegam.
Ao abrir ou reconectar o WebSocket, recarregar a janela do histórico antes de
permitir novas seleções, pois o stream não reproduz resultados perdidos durante
a queda. A conexão fica aberta durante essa consulta: eventos recebidos nesse
intervalo entram em buffer e são aplicados sem duplicar IDs após o snapshot.
Essa consulta adicional também cobre o intervalo entre a consulta inicial e a
inscrição no stream. Uma falha de sincronização suspende o stream e mantém o
snapshot anterior identificado, com opção de tentar novamente.

## Sistema visual e referência

Referência fornecida: https://api.revesbot.com.br/history/pragmatic-brazilian-roulette
Inspeção em navegador confirmou cabeçalho compacto, fundo escuro, painel de
resultados, cartões grandes com cores de roleta e ferramentas no topo.
Aplicação: manter os mesmos tokens, CSS de base, seletor, grade e composição
de histórico; ampliar somente a largura/altura da barra para leitura da race.

Fontes de verdade: `static/css/tokens.css`, `base.css` e componentes compartilhados.
Exceções locais: `static/css/pages/wheel-pair.css`, escopadas por `.wheel-pair-page`.
A página funcional é a amostra viva desses componentes, sem catálogo público.
Não usar fotografia: a tarefa exige dados e ilustração SVG precisa. Movimento
restrito à abertura do painel existente, respeitando movimento reduzido.

## Implementação e verificação

Rota isolada em `routes/wheel_pair.py`, registrada nos dois entrypoints da API.
Consultas read-only reutilizam `/api/roulettes-list`, `/history/{slug}?limit=1000`
e `/ws`. Não muda contratos, banco, robôs de aposta ou plugin global.
Modelo puro em `static/js/core/wheel-pair-model.js`; interação em
`static/js/pages/wheel-pair.js`; template `templates/wheel_pair.html`.

Exemplo: `[11, 25]` → base 25, esquerda centro 12, direita centro 10;
aposta `3, 5, 7, 8, 10, 12, 23, 24, 28, 35`.

Verificação da versão de deploy: 12 testes do modelo e os 269 testes da suite
da API em produção passaram (incluindo 10 de rota/regressão da página).
O teste de navegador com APIs controladas passou para múltiplas seleções,
resumo, atualização ao vivo, troca de mesa e respostas atrasadas, teclado,
erros e layouts desktop/celular. A fonte da race no celular tem teste de regressão.
Também passaram os cenários de giros perdidos antes da primeira inscrição,
reconexão, buffer durante consulta atrasada e deduplicação de eventos no snapshot.
O checkout original tinha uma expectativa de rotas JEV desatualizada. O deploy
foi preparado em worktree separado sobre a main atual, que já resolve essa
expectativa, preservando as alterações locais em andamento.
O entrypoint mínimo local entrega a página com HTTP 200. A consulta real ao
Mongo local não respondeu no prazo de verificação; o fluxo de dados foi validado
no navegador com respostas controladas no mesmo contrato da API de histórico.
O Nginx tem a location correspondente e preserva o include do serviço de
vetores já ativo em produção. A nova rota usa o catálogo oferecido pela versão
da API de histórico em execução, incluindo extensões quando disponíveis.
Publicação usa o fluxo atual por SHA da main, testes e rollback automático.
O release anterior verificado é `71da4b68269fd5448d7795203e3e0f4327e071c4`.
