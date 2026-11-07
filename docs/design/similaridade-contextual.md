# Similaridade contextual

## Escopo e regras

Página independente em `/analise-similaridade-contextual`, integrada à API
FastAPI/Jinja existente. Mesa fixa: `pragmatic-brazilian-roulette`. O histórico
é consultado em `/history/{slug}?limit=9`; como a API entrega do mais recente ao
mais antigo, os nove valores são invertidos para separar os cinco resultados
anteriores e a sequência cronológica dos quatro mais recentes. A busca usa
`POST /busca-vetorial/api/search`, com os parâmetros definidos no pedido.

A similaridade contextual usa matching máximo um-para-um entre os dois arrays de
cinco resultados: 10 pontos por número exato e 8 por vizinho imediato na roda
europeia, pontuação máxima de 50 e corte contextual atual de 30%. No
empate, a contagem exata decide antes da ordem original. Até seis ocorrências
selecionadas contribuem igualmente para o ranking final neste experimento.
Cada ocorrência contém até cinco resultados posteriores, totalizando até 30
resultados analisados; o denominador percentual acompanha os dados válidos.

Cada valor válido de `following` distribui 10 pontos para si e 8 para cada
vizinho físico. O ranking contém todos os 37 números, incluindo zeros. As
contagens exatas e de contribuições vizinhas são distintas. O denominador é o
número de resultados posteriores válidos multiplicado por 10; o percentual não
é probabilidade. Contextos anteriores incompletos são ignorados sem estimativa.

## Elementos e sistema visual

- Cabeçalho com ação explícita para recarregar os nove resultados e refazer a busca.
- Painel de contexto atual, sequência vetorial e contadores de cobertura.
- Tabela auditável de ocorrências, com correspondências detalhadas e realce das
  seis selecionadas.
- Na tabela de ocorrências, contornos verde fluorescente identificam os números
  iguais ao contexto atual na coluna **Anterior** e à sequência da busca na
  coluna **Sequência**.
- Ranking de 37 números e cartões de rastreabilidade das ocorrências selecionadas.
  Cada cartão também expõe a distribuição de pontos de cada posterior e as
  correspondências escolhidas no matching contextual.
- Tema, tipografia, superfícies e foco usam `static/css/tokens.css` e `base.css`.
  Sem fotografia: a tarefa é inspeção de resultados numéricos. Movimento limitado
  ao estado de carregamento e respeitando movimento reduzido.

## Arquivos e operação

Modelo sem dependência de DOM em `apps/api/static/js/core/contextual-similarity-model.js`;
interface em `apps/api/static/js/pages/contextual-similarity.js`; markup e estilos
em `apps/api/templates/contextual_similarity.html` e
`apps/api/static/css/pages/contextual-similarity.css`. A rota FastAPI está em
`apps/api/routes/contextual_similarity.py`; `infra/nginx/api-revesbot.conf`
encaminha a rota à API.
O endpoint vetorial continua protegido e publicado pelo location já existente
`/busca-vetorial/api/search`. O fluxo só lê o histórico e o índice vetorial.
Os URLs dos assets da página recebem uma versão explícita porque o CDN aplica
cache de longa duração a `/static/`; atualizar a versão invalida código antigo.

## Verificação

Testes do modelo cobrem a ordem circular, matching contextual máximo e sem
reutilização, corte e seleção, arrays incompletos, distribuição da pontuação
posterior, 37 linhas e denominador proporcional. Um teste de navegador confere
ordem da sequência, contrato de busca, renderização e layout responsivo. A rota
é verificada sem conexão ao banco. A configuração Nginx foi atualizada no
repositório; isso não publica nem recarrega a configuração de produção.
