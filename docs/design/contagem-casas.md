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
6. Mapa de calor automático e ranking: acompanham N ocorrências a partir do ponto
   de referência escolhido, com seletor de 1 a 10 giros e padrão 10. Permitem
   navegar para giros anteriores e travar uma referência, independentemente das
   seleções manuais, conforme a especificação abaixo.

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

## Mapa de calor automático — ampliação autorizada

O seletor da janela aceita uma quantidade inteira N de 1 a 10 giros, com padrão
10; zero não é válido. N é uma contagem de ocorrências, não um deslocamento ou
índice inicial: o mapa e seu ranking usam `referenceItems[0]` a
`referenceItems[N - 1]`, ou todas as disponíveis se houver menos de N. Sem recuo,
`referenceItems` é o histórico atual completo. Não são N valores diferentes nem as N
primeiras apostas com dez números distintos. Ocorrências repetidas do mesmo
número continuam independentes; setores sobrepostos conservam sua quantidade
real de números. A análise de cada ocorrência reutiliza `analyzeSelection`,
buscando a ocorrência anterior em todo o histórico disponível na referência,
derivado da janela carregada de até 1.000 resultados,
mesmo que ela esteja fora das N ocorrências que contribuem para o calor. Uma
ocorrência sem par anterior válido não contribui e deve aparecer como
indisponível no detalhamento; não é substituída por uma ocorrência mais antiga.

O contrato do modelo é
`analyzeHeatmap(items, decayPercent = 100, sourceLimit = 10, lookback = 0)`.
`sourceLimit` deve ser inteiro entre 1 e 10, inclusive; valores fora desse intervalo,
zero e frações não são válidos. A quantidade efetiva de fontes é
`min(sourceLimit, referenceItems.length)`. Alterar a janela recalcula imediatamente o mapa,
ranking e detalhamento, sem nova consulta ou alteração no limite de 1.000 resultados
carregados. A preferência usa a chave localStorage
`revesbot-wheel-heatmap-source-limit` e é restaurada ao reabrir a página; uma
preferência ausente ou inválida mantém o padrão 10. Essa escolha não altera a
quantidade de casas do par, os pesos espaciais, a redução por acerto, as seleções
manuais ou seus snapshots.

Cada setor de cinco números usa pesos espaciais `[0,3; 0,7; 1; 0,7; 0,3]`, na
ordem dos dois vizinhos de um lado, centro e dois vizinhos do outro lado. O centro
vale 1; os vizinhos imediatos, a uma casa do centro (v1), valem 0,7; os vizinhos
externos, a duas casas (v2), valem 0,3. Essa ponderação vale igualmente para os
setores esquerdo e direito.

Quando um número aparece nos dois setores da mesma aposta, seu peso espacial é
o maior dos dois pesos, sem somá-los. Por exemplo, um número com peso 0,3 em um
setor e 0,7 no outro contribui com 0,7 por essa aposta. Mesmo com sobreposição,
cada aposta fornece uma única contribuição para cada número. A união crescente
dos números da aposta e suas contagens de presença permanecem as mesmas.

Cada aposta válida começa com fator temporal 1. Um controle de redução por acerto
permite escolher de 0% a 100%, em passos de 1%, com padrão de 100%. Para redução
`p` e `k` acertos posteriores à ativação, o fator temporal remanescente é:

```text
fator_temporal = (1 - p / 100) ^ k
contribuicao(aposta, numero) = peso_espacial(aposta, numero) * fator_temporal(aposta)
calor(numero) = soma das contribuicoes das apostas validas
```

Sem acertos, o fator temporal permanece 1, inclusive quando a redução é 100%.
Redução 0% mantém esse fator; 50% deixa 1, 0,5, 0,25… após zero, um, dois… acertos;
100% zera a aposta inteira no primeiro acerto. Um acerto é qualquer resultado
posterior contido na aposta, inclusive um vizinho externo de peso espacial 0,3,
e cada giro conta uma única vez. O peso espacial não reduz o efeito do acerto:
a redução temporal afeta todos os números daquela aposta, não somente o número
sorteado. A alteração do controle recalcula os pesos imediatamente usando o
mesmo histórico, sem nova consulta.

O cálculo é causal: a ocorrência selecionada é o giro que ativa a aposta, e a
primeira tentativa é o giro seguinte. Para a ocorrência de índice `i`, somente
os índices `i - 1` até `0` do histórico de referência podem reduzir seu peso.
O próprio giro de ativação não
é acerto da aposta que acabou de formar, mesmo quando seu número está nela.
O novo resultado pode reduzir apostas anteriores e formar sua própria aposta
com fator temporal inicial 1; essas contribuições são independentes.

O calor de um número soma o produto do seu peso espacial pelo fator temporal
de cada aposta válida que o contém. As contagens não passam a ser ponderadas:
`rawCount` continua contando apostas válidas que contêm o número, antes da
redução; `activeCount` conta as que conservam contribuição positiva; frequência
e repetições entre seleções manuais continuam contando presença uma vez por
aposta. Não existe redução por idade, passagem de tempo ou giro sem acerto.
Ao chegar um novo resultado, a ocorrência que sai da janela das N mais
recentes deixa de contribuir por sair da janela, não por uma redução temporal.
Os pesos são reconstruídos do histórico atual em vez de acumulados em memória,
preservando o mesmo resultado após atualizar, reconectar ou receber um evento
duplicado.

A escala visual é absoluta, de 0 a 10, e mantém as mesmas referências de cor
entre atualizações e tamanhos da janela, inclusive quando N é menor que 10.
Não dividir pelo maior peso do instante nem por N: reduzir um peso
deve esfriar sua representação mesmo que ele continue sendo o maior. Cor,
intensidade e peso numérico devem tornar essa redução perceptível; a legenda
identifica a progressão de frio a quente. Os pesos descrevem a composição das
apostas e não são percentuais de assertividade.

A race automática fica como primeiro filho de `.result-grid-viewport`, antes
de `#result-grid`, nunca dentro da grade, cujos filhos representam resultados.
Ela rola junto do histórico, sem reservar uma área fixa que esconda a grade ou
a barra lateral. O detalhamento das ocorrências da janela escolhida é expansível e começa
fechado. O desenho se adapta ao desktop e celular e aos temas claro/escuro.
Reutiliza `RouletteRacetrack` sem modificar o plugin global, com uma instância
própria e IDs SVG distintos das races das seleções manuais.

O mapa não adiciona, remove ou modifica seleções manuais nem seus snapshots e
resumos. Destravado, atualiza junto da janela de resultados já validada pelo fluxo
existente de carregamento/sincronização; travado, preserva sua referência conforme
a especificação abaixo. Trocar de mesa limpa o mapa anterior imediatamente;
respostas antigas e eventos de outra geração não podem alterar o mapa atual.
Pausa, retomada e falhas seguem o comportamento existente da página. Não cria
endpoints, dependências, processos ou alterações em banco, Nginx e PM2.

## Navegação histórica e trava do mapa — ampliação autorizada

`lookback` é a quantidade inteira de giros que o mapa recua em relação ao giro
mais recente do histórico que está usando: 0 representa o atual; 1 representa
um giro antes. Para histórico não vazio, o intervalo válido vai de 0 até
`items.length - 1`; valores negativos, fracionários ou além da janela disponível
não são válidos. A janela N continua sendo a quantidade de ocorrências a analisar,
sem confundir essa contagem com o recuo. Se não houver resultados, não existe
âncora de referência e o mapa fica indisponível.

O cálculo histórico usa o sufixo `referenceItems = items.slice(lookback)`. As
fontes, os pares e os acertos são calculados exclusivamente nesse sufixo. Assim,
nenhum giro mais recente que a referência pode formar pares ou reduzir pesos
na análise daquele instante. Os índices de fontes e acertos são relativos ao
histórico de referência; horários, IDs, posição e linhas da tabela devem consultar
esse mesmo histórico, sem buscar a ocorrência pelo índice na grade ao vivo.

Destravado, o recuo representa um atraso móvel. Por exemplo, com recuo 3, cada
novo giro mantém o mapa três giros atrás do resultado mais recente; a ocorrência
de referência muda junto da grade. Carregamentos e sincronizações podem atualizar
esse histórico, mantendo o recuo dentro do intervalo disponível. Navegar no
histórico recalcula o mapa, ranking e tabela sem nova consulta.

Travar captura uma cópia do histórico completo carregado, o recuo escolhido e
a identidade e o horário da ocorrência de referência. A cópia precisa incluir
o contexto anterior à janela N para permitir reconstruir os pares. O mapa usa
o sufixo dessa cópia a partir do recuo capturado, sem depender de índices da grade
ao vivo nem de IDs que possam sair da janela corrente. A grade, o WebSocket e
o status da conexão continuam funcionando normalmente.

Enquanto travado, novos giros, consultas, reconexões e o botão Atualizar histórico
podem mudar a grade, mas não mudam os dados do ranking, race, referência ou tabela
do mapa. Alterações manuais de N ou da redução por acerto continuam permitidas e
recalculam usando o mesmo histórico fixo; os pesos espaciais permanecem iguais.
Os controles de navegação histórica ficam desabilitados enquanto a trava estiver
ativa. A interface identifica o estado travado e a ocorrência de referência por
ID e horário quando esses campos estiverem disponíveis.

Destravar descarta a cópia e retoma o histórico ao vivo com o recuo que foi
capturado, agora como atraso móvel; não tenta reencontrar a antiga âncora por ID.
Voltar ao atual remove a trava e define recuo 0. Trocar de mesa também remove
a trava, limpa o histórico fixo e reinicia o recuo em 0. Recarregar a página
começa destravado no atual: trava, cópia e recuo não são persistidos. A preferência
da janela de 1 a 10 giros e a redução por acerto conservam suas regras existentes.

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

### Validação da ampliação com mapa de calor

Os resultados de verificação acima pertencem à versão anterior da página,
publicada sem o mapa automático. Os resultados desta seção pertencem à primeira
versão do mapa, com contribuições espaciais uniformes, antes da ponderação por
centro e vizinhos. Nessa versão, passaram 23 testes do modelo e 10 testes de
rota/regressão. O teste de navegador com dados controlados também passou, com
30 consultas de histórico, em desktop e celular. As capturas de tela foram
inspecionadas nos dois layouts.

A verificação cobre reduções 0%, 50% e 100% e valores intermediários; exclusão do
próprio gatilho; acertos afetando a aposta inteira; ausência de redução por idade;
janela de dez ocorrências, incluindo valores repetidos e setores sobrepostos;
falta de par anterior; transição da janela; deduplicação e sincronização ao vivo;
troca de mesa; alteração imediata do controle; isolamento das seleções manuais;
escala que esfria sem normalização relativa; temas e acesso à grade e barra
lateral em desktop e celular.

A revisão independente não encontrou bloqueadores de causalidade, integração
ao vivo ou isolamento dos IDs SVG. O ajuste de contraste escolhe preto ou branco
pela luminância da cor, mantendo a cor de texto do tema para peso zero; o limiar
adotado garante contraste mínimo superior a 4,5:1 nas cores positivas. A
reexecução final passou após esse ajuste, com contraste mínimo observado de
4,829:1, incluindo o cenário de peso 10. Esta seção registra validações locais;
a verificação dos resultados reais em produção é feita após o deploy.

### Validação da ponderação espacial

Passaram 28 testes do modelo e 10 testes de rota/regressão da página. A cobertura
inclui os pesos `[0,3; 0,7; 1; 0,7; 0,3]` em ambos os setores, a escolha do maior
peso em sobreposições (inclusive casas zero), o produto espacial × temporal,
sua soma entre apostas independentes e as contagens de presença sem ponderação.
Um caso verifica que o acerto em um número de peso 0,3 reduz a aposta inteira.

O teste de navegador com dados controlados passou em desktop e celular, mantendo
o carregamento de 1.000 resultados por mesa. Verificou pesos nos setores e na
aposta crescente, sobreposição por máximo, reduções e recomputação ao vivo,
reconexão, troca de mesa, deduplicação, snapshots manuais e escala absoluta.
As capturas foram inspecionadas; o contraste mínimo observado nos números com
calor positivo foi 4,636:1. A revisão independente do modelo e da integração
não encontrou problemas acionáveis. Estes resultados são locais; a publicação
segue o fluxo existente de CI, deploy por SHA e verificação dos dados reais.

### Validação da janela configurável do ranking e mapa

Passaram 34 testes do modelo e 10 testes de rota/regressão da página. Os novos
casos verificam os limites 1 e 10, o padrão 10, a rejeição de zero e valores
inválidos, os pares encontrados além da janela, o histórico curto, a causalidade
dos acertos e a recomputação sem mutação ou acúmulo de pesos.

O teste de navegador passou com 37 consultas de histórico e 1.000 resultados
por mesa. Verificou opções 1 a 10 e mudanças entre 1, 3 e 10, atualização do
ranking, race e detalhamento sem consulta extra, preservação dos pesos espaciais
e redução, snapshots manuais intactos e preferência mantida em reconexão,
troca de mesa e recarga. Capturas desktop/celular foram inspecionadas, sem
transbordamento horizontal; o contraste mínimo observado no mapa foi 4,636:1.
A revisão independente não encontrou bloqueadores funcionais. Estes resultados
são locais; a publicação segue o fluxo existente de CI, deploy e verificação real.

### Validação da navegação histórica e trava

Passaram 41 testes do modelo e 10 testes de rota/regressão. Os novos casos cobrem
recuos válidos e inválidos, referência no limite do histórico, contexto mais
antigo preservado, exclusão de giros futuros dos acertos e dos dados inválidos,
pureza e índices relativos ao sufixo. A fixture no recuo 7, com janela 3 e
redução 100%, conserva peso 2,4 no número 26: o giro 26 posterior à referência
não pode pagar aquelas apostas na visão histórica.

O navegador passou com saída 0, 54 consultas de histórico e 1.000 resultados
por mesa. Verificou IDs/horários históricos, navegação, trava mantendo a grade
viva, eventos duplicados, ajustes de janela/redução na cópia, reconexão, refresh,
pausa/retomada, histórico vivo vazio, controles durante carregamento, destrava,
retorno ao atual e reset em troca de mesa/recarga. Capturas desktop/celular foram
inspecionadas sem transbordamento horizontal; contraste mínimo observado de
4,636:1. A revisão independente confirmou causalidade, estabilidade da cópia e
os ajustes dos controles durante carregamento. Estes resultados são locais;
a publicação segue o fluxo existente de CI, deploy e verificação real.
