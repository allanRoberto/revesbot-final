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
  dirigidas a partir do último número e do último par, envia 37 perguntas Noul, duas Choice e até
  12 perguntas Score na mesma chamada, e devolve os rankings originais e meta-rankings completos
  incluindo o zero.
- `POST /api/jev/avaliar`: recebe os três resultados que chegaram depois de um ranking salvo,
  calcula métricas fora da amostra e grava uma avaliação separada. Não chama o OpenRouter.

As cinco rotas exigem HTTP Basic. Os três POSTs também exigem o token CSRF emitido ao abrir a página.
Configuração de acesso ausente bloqueia somente essas rotas. A chave OpenRouter ausente bloqueia
somente a análise; página e histórico continuam disponíveis.

## Ranking e relações A → B

Uma relação `A → B` significa apenas que, nas ocorrências históricas de `A` com três resultados
posteriores disponíveis, `B` apareceu ao menos uma vez nesse horizonte. A última ocorrência sem
três resultados futuros completos nunca entra no suporte. Repetições de `B` dentro do mesmo
horizonte contam como um único acerto da relação.

O backend calcula suporte, acertos, taxa bruta, taxa suavizada, referência independente e lift nos
horizontes de uma, duas e três rodadas, além de janelas recentes, relação do último par, frequências
em cinco janelas e percentil histórico do atraso. Relações com suporte baixo ou comportamento
instável são identificadas antes da chamada. O Jev não calcula contagens nem inventa categorias:
ele recebe estruturas versionadas, estima ocorrências e gradua os candidatos catalogados.

O histórico completo é usado nos agregados e salvo no registro privado. Para manter o contexto
abaixo do limite do modelo, o `state` enviado contém no máximo os 200 resultados mais recentes,
além da quantidade total, do hash SHA-256 e das estatísticas calculadas sobre todo o histórico.
Perfis e relações são enviados como tabelas compactas com colunas declaradas, sem repetir nomes de
campos em cada número. A redução é declarada em `history_context.raw_history_scope`.

Como vários números podem aparecer nas três rodadas seguintes, as 37 perguntas são Noul
independentes. As probabilidades não são normalizadas para somarem 100%. O ranking ordena a
estimativa bruta do Jev em ordem decrescente, com desempate pelo número crescente.

Para a rodada imediatamente seguinte há uma pergunta Choice única com as 37 opções. Essa saída é
uma distribuição normalizada e produz um segundo ranking, separado do ranking Noul. Outra Choice
classifica o contexto como neutro, concentrado em frequência, orientado por transições, orientado
por atrasos ou instável. As relações candidatas usam Score de 0 a 3 e exibem também a confiança;
confiança representa concentração da resposta, não garantia de acerto.

## Meta-ranking e validação walk-forward

Antes da chamada ao Jev, o backend reproduz cronologicamente as previsões que estariam disponíveis
em cada ocorrência anterior do número de origem. Uma ocorrência só entra no treino depois que todo
o seu horizonte futuro já seria conhecido naquele ponto, evitando vazamento de resultados. São
avaliadas três famílias determinísticas: relação do último número, relação do último par e frequência
em janela recente, nos horizontes de uma e três rodadas.

Para cada número e família são calculados quantidade de amostras, Brier fora da amostra, ganho sobre
a referência uniforme, erro de calibração, deriva recente e uma probabilidade corrigida. O Jev recebe
uma tabela compacta desses resultados e continua respondendo às perguntas tipadas existentes. Depois
da resposta, o backend combina de forma conservadora a estimativa do Jev, a estimativa determinística
calibrada, a qualidade Score da relação e o regime atual. Quanto menor a confiabilidade histórica,
mais o resultado final é retraído para a probabilidade-base.

A API preserva `ranking` e `ranking_proxima_rodada` para compatibilidade e acrescenta:

- `ranking_meta`: meta-ranking para as próximas três rodadas;
- `ranking_meta_proxima_rodada`: distribuição normalizada para a próxima rodada;
- `sinal_meta`: estado `validated`, `experimental` ou `no_reliable_signal`, justificativa e cobertura;
- `validacao_walk_forward`: versão e parâmetros do protocolo sem vazamento.

O painel abre na visão meta, permite filtrar números validados, experimentais, degradados ou sem
evidência e mantém as visões originais do Jev para comparação. “Validado” significa apenas que os
critérios definidos foram atendidos neste recorte histórico; não representa garantia futura.

Depois que três resultados reais estiverem disponíveis, o painel permite avaliar o ranking salvo.
A avaliação calcula Brier médio e log loss binário médio para os 37 eventos Noul, acerto em Top
1/3/5/10 e o desempenho da Choice na primeira rodada. Para registros novos, calcula as mesmas
métricas para o meta-ranking e informa o ganho ou perda em relação ao Jev original. O registro de
avaliação é separado do registro original e nenhuma inferência paga é repetida.

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

O contrato implementado é `POST https://openrouter.ai/api/alpha/decisions`, com `model`, `state` e
`questions`. Não são usados chat completions, mensagens, temperatura, fallback ou retry. Antes da
chamada, o cliente serializa o JSON compacto e bloqueia localmente payloads acima de 65.536 bytes;
assim, uma entrada fora do limite não gera inferência paga nem uma tentativa sabidamente inválida.

Referências oficiais:

- <https://openrouter.ai/docs/guides/community/typesafe-sdk>
- <https://openrouter.ai/docs/guides/community/jev>
- <https://docs.typesafe.ai/primitives/noul>
- <https://docs.typesafe.ai/primitives/choice>
- <https://docs.typesafe.ai/primitives/score>
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
  apps/api/tests/test_jev_evaluation.py \
  apps/api/tests/test_jev_meta_ranking.py \
  apps/api/tests/test_jev_ranking.py \
  apps/api/tests/test_jev_routes.py

node apps/api/tests/browser/test_jev_page.mjs
```

O teste de navegador usa o Playwright já declarado em `apps/bot_automatico` e o Google Chrome
instalado no macOS. Todas as rotas são interceptadas localmente; nenhuma chamada real é feita ao
MongoDB ou ao OpenRouter.
