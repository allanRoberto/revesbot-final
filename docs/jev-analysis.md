# Análise manual de roleta com Jev

## Escopo

A API serve um painel administrativo em `/jev` para consultar um snapshot da mesa fixa
`pragmatic-auto-roulette`, editar o histórico, gerar um ranking de 0 a 36 com relações dirigidas
`A → B` e, como modo complementar, analisar seis grupos. Cada operação envia manualmente uma
única requisição ao Jev pelo OpenRouter.

Abrir a página, abrir/cancelar o modal e concluir a busca não chamam o OpenRouter. A rota de
análise usa somente `historico_texto` recebido no POST e não consulta o histórico novamente.

## Rotas

- `GET /jev`: página HTML protegida, inicialmente sem histórico e sem resultado.
- `GET /api/jev/historico?quantidade=300`: seleciona os últimos resultados no MongoDB e os
  devolve do mais antigo para o mais recente.
- `POST /api/jev/analisar`: valida o texto e os seis grupos, calcula as estatísticas, envia seis
  perguntas Noul em uma única chamada e devolve o resultado na própria resposta HTTP.
- `POST /api/jev/ranking`: valida o texto, calcula perfis dos 37 números e relações históricas
  dirigidas a partir do último número, envia 37 perguntas Noul e até 12 perguntas de relevância
  de padrão na mesma chamada, e devolve o ranking completo incluindo o zero.

As quatro rotas exigem HTTP Basic. Os dois POSTs também exigem o token CSRF emitido ao abrir a página.
Configuração de acesso ausente bloqueia somente essas rotas. A chave OpenRouter ausente bloqueia
somente a análise; página e histórico continuam disponíveis.

## Ranking e relações A → B

Uma relação `A → B` significa apenas que, nas ocorrências históricas de `A` com três resultados
posteriores disponíveis, `B` apareceu ao menos uma vez nesse horizonte. A última ocorrência sem
três resultados futuros completos nunca entra no suporte. Repetições de `B` dentro do mesmo
horizonte contam como um único acerto da relação.

O backend calcula suporte, acertos, taxa bruta, taxa suavizada, referência independente, lift e
janelas recentes. Relações com suporte baixo ou comportamento instável são identificadas antes da
chamada. O Jev não calcula contagens nem inventa categorias: ele recebe estruturas versionadas,
estima separadamente a ocorrência de cada número e avalia a relevância dos candidatos catalogados.

O histórico completo é usado nos agregados e salvo no registro privado. Para manter o contexto
abaixo do limite do modelo, o `state` enviado contém no máximo os 500 resultados mais recentes,
além da quantidade total, do hash SHA-256 e das estatísticas calculadas sobre todo o histórico. A
redução é declarada em `history_context.raw_history_scope`.

Como vários números podem aparecer nas três rodadas seguintes, as 37 perguntas são Noul
independentes. As probabilidades não são normalizadas para somarem 100%. O ranking ordena a
estimativa bruta do Jev em ordem decrescente, com desempate pelo número crescente.

## Configuração

```dotenv
OPENROUTER_API_KEY=
OPENROUTER_MODEL=typesafe/jev-1.13
JEV_MAX_HISTORY=10000
JEV_MAX_BODY_BYTES=262144
JEV_RESULTS_DIR=resultados/jev
JEV_PANEL_USER=
JEV_PANEL_PASSWORD=
```

Não há credenciais padrão. Em produção, use uma senha exclusiva e mantenha o painel sob HTTPS.
Os registros em `JEV_RESULTS_DIR` são privados, não possuem rota de arquivos estáticos e estão
ignorados pelo Git no caminho padrão.

O contrato implementado é `POST https://openrouter.ai/api/v1/systemone`, com `model`, `state` e
`questions`. Não são usados chat completions, mensagens, temperatura, fallback ou retry.

Referências oficiais:

- <https://openrouter.ai/docs/guides/community/typesafe-sdk>
- <https://openrouter.ai/docs/guides/community/jev>
- <https://docs.typesafe.ai/primitives/noul>
- <https://docs.typesafe.ai/concepts/state>

## Execução local

A API mínima usada pelo deploy é iniciada a partir da raiz do repositório:

```bash
PYTHONPATH=apps ./.venv/bin/python apps/api/start_minimal.py
```

Por padrão ela escuta em `127.0.0.1:8082`. A aplicação completa existente continua disponível
com:

```bash
PYTHONPATH=apps ./.venv/bin/python apps/api/start.py
```

## Testes sem rede ou inferência paga

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=apps ./.venv/bin/python -m pytest -q \
  -p no:cacheprovider \
  apps/api/tests/test_jev_core.py \
  apps/api/tests/test_jev_history_service.py \
  apps/api/tests/test_jev_openrouter.py \
  apps/api/tests/test_jev_persistence.py \
  apps/api/tests/test_jev_ranking.py \
  apps/api/tests/test_jev_routes.py

node apps/api/tests/browser/test_jev_page.mjs
```

O teste de navegador usa o Playwright já declarado em `apps/bot_automatico` e o Google Chrome
instalado no macOS. Todas as rotas são interceptadas localmente; nenhuma chamada real é feita ao
MongoDB ou ao OpenRouter.
