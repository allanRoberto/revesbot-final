# Consulta HTTP dos rankings de trios

```text
GET https://api.revesbot.com.br/api/triple-context-ranking
```

A rota consulta o catálogo publicado no MongoDB e retorna **os 37 candidatos somente da direção escolhida**, na ordem e com os pontos já gravados. Não recalcula o histórico.

## Parâmetros

| Parâmetro | Obrigatório | Valores / significado |
|---|---|---|
| `numbers` | Sim | Três números distintos de 0 a 36, separados por vírgula. Exemplo: `34,14,18` |
| `direction` | Sim | `forward`: até 20 giros à frente; `backward`: até 10 giros para trás |
| `ordered` | Sim | `true`: ordem exata; `false`: reúne as seis ordens |
| `input_order` | Não | `latest_first` por padrão: o primeiro informado é o mais recente. `chronological`: primeiro informado é o mais antigo |
| `roulette_id` | Não | Padrão: `pragmatic-auto-roulette` |

`input_order` só altera a consulta quando `ordered=true`. Com `numbers=34,14,18` e os padrões, a sequência buscada é **18 → 14 → 34**. A direção à frente começa após o terceiro número da ocorrência; para trás começa antes do primeiro.

## Exemplos

Ordem exata, à frente, com o **34 como último resultado**:

```bash
curl --get 'https://api.revesbot.com.br/api/triple-context-ranking' \
  --data-urlencode 'numbers=34,14,18' \
  --data-urlencode 'direction=forward' \
  --data-urlencode 'ordered=true'
```

As quatro combinações de opções para o mesmo trio:

```text
/api/triple-context-ranking?numbers=34,14,18&direction=forward&ordered=true
/api/triple-context-ranking?numbers=34,14,18&direction=backward&ordered=true
/api/triple-context-ranking?numbers=34,14,18&direction=forward&ordered=false
/api/triple-context-ranking?numbers=34,14,18&direction=backward&ordered=false
```

Para informar a sequência **3 → 20 → 1** em ordem cronológica:

```text
/api/triple-context-ranking?numbers=3,20,1&direction=forward&ordered=true&input_order=chronological
```

## Resposta

A resposta inclui:

- `requested_numbers`, `input_order`, `ordered` e `direction`: opções da consulta;
- `combination` e `key`: chave usada no catálogo; cronológica no modo exato, numérica crescente no modo sem ordem;
- `build_id`: versão publicada que respondeu à consulta;
- `occurrences`: quantidade de ocorrências do trio;
- `has_evidence`: se existe ao menos um resultado disponível **na direção selecionada**;
- `depth`, `context_events`, `complete_occurrences` e `position_counts`: cobertura dos contextos selecionados;
- `ranking`: 37 objetos com `position`, `number`, `score` e `direct_hits`;
- `source`: quantidade e período dos resultados usados na geração do catálogo.

`score` é a pontuação histórica, incluindo os pesos dos vizinhos; `direct_hits` conta aparições diretas do número nos contextos. Nenhum desses campos é percentual de assertividade.

Combinações sem ocorrência retornam HTTP 200, `occurrences=0`, `has_evidence=false` e 37 candidatos com pontos zerados. Se houver ocorrência do trio, mas nenhum resultado disponível na direção escolhida, `has_evidence` também será falso.

## Erros

| HTTP | Significado |
|---|---|
| 422 | Opções inválidas, parâmetro obrigatório ausente ou trio fora do domínio de três números distintos |
| 404 | Não existe catálogo publicado para a roleta solicitada |
| 503 | Catálogo inconsistente, versão indisponível, falha no MongoDB ou consulta acima de cinco segundos |

A resposta não inclui o ranking da direção oposta, caminhos do servidor ou credenciais. A rota segue o acesso público das consultas de histórico existentes na API.

## Integração

Router: `apps/api/routes/triple_context_ranking.py`. Serviço de leitura assíncrona: `apps/api/services/triple_context_ranking_service.py`.

O router é registrado em `minimal_main.py` (produção) e `main.py`. Usa a conexão Motor de `api.core.runtime_db.history_db` e faz três consultas indexadas: ponteiro ativo, manifesto verificado e ranking. Uma única versão é mantida durante cada requisição, mesmo que outra seja publicada simultaneamente.

O Nginx precisa conter o `location = /api/triple-context-ranking` definido na configuração versionada. Na instalação existente, a atualização deve preservar os blocos HTTPS gerados para o domínio, validar com `nginx -t` e só então recarregar o serviço.

Teste do contrato:

```bash
PYTHONPATH=apps python -m pytest -q apps/api/tests/test_triple_context_ranking.py
```
