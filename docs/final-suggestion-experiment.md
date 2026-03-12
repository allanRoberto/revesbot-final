# Final Suggestion Experiment (A/B histórico)

Data: 2026-03-08  
Objetivo: validar impacto da preservação de ranking por score no pipeline de `/api/patterns/final-suggestion` com foco em 11 fichas e 4 tentativas.

## Status atual (consolidado)

- A variante **B (rank_preserved)** foi consolidada como baseline oficial de produção em `/api/patterns/final-suggestion`.
- A comparação **A/B/C** permanece disponível apenas no script de experimento, para reprodutibilidade histórica e análises futuras.
- O caminho de produção não mantém mais branch experimental A/B.

## 1. Escopo e desenho do experimento

- Pipeline medido: lógica real de `final-suggestion` (base + optimized + fusão).
- Métrica de negócio: acerto com **até 11 números** em **até 4 tentativas**.
- Replay: histórico real carregado de `apps/signals/helpers/results.json`.
- Casos usados: `200` (de `630` históricos carregados).

Variantes:
- **A (current)**: comportamento antigo de ranking (reordenação numérica).
- **B (rank_preserved)**: preservação de ranking por score no caminho de `/final-suggestion`.

Restrições mantidas:
- Mesmo limite de fichas em ambas as variantes: `max_numbers=11` e `optimized_max_numbers=11`.
- Sem alteração de `/optimized-suggestion` e demais endpoints.
- Sem alterar pesos, decay, filtros e correlação para este experimento.

## 2. Definições de métrica

- `coverage`: `% de casos elegíveis com sugestão disponível`.
- `average_list_size`: tamanho médio da lista onde houve sugestão disponível.
- `confidence_distribution`: distribuição por buckets de score.
- `conditional_hit@k`: acerto até `k` tentativas considerando apenas casos com sugestão disponível.
- `effective_hit@k`: acerto até `k` tentativas considerando todos os casos elegíveis (incorpora cobertura).

## 3. Resultados A/B

### 3.1 Cenário principal (fusion_default: base=0.4, optimized=0.6)

Variante A:
- coverage: `0.945`
- average_list_size: `11.0`
- conditional_hit@4: `0.746032`
- effective_hit@4: `0.705`
- confidence_distribution: `50-59:112`, `60-69:75`, `70-79:2`

Variante B:
- coverage: `0.975`
- average_list_size: `11.0`
- conditional_hit@4: `0.733333`
- effective_hit@4: `0.715`
- confidence_distribution: `40-49:1`, `50-59:116`, `60-69:76`, `70-79:2`

Delta (B - A):
- coverage: `+0.03`
- average_list_size: `+0.0`
- conditional_hit@4: `-0.012699`
- effective_hit@4: `+0.01`

### 3.2 Base-only (base=1.0, optimized=0.0)

Delta (B - A):
- coverage: `+0.03`
- average_list_size: `+0.0`
- conditional_hit@4: `+0.003174`
- effective_hit@4: `+0.025`

### 3.3 Optimized-only (base=0.0, optimized=1.0)

Delta (B - A):
- coverage: `+0.03`
- average_list_size: `+0.0`
- conditional_hit@4: `-0.017827`
- effective_hit@4: `+0.005`

## 4. Ganho líquido no objetivo de negócio

Foco: `fusion_default` com 11 fichas e 4 tentativas.

- **effective_hit@4**: `0.705 -> 0.715` (**+1.0 p.p.**)
- **conditional_hit@4**: `0.746032 -> 0.733333` (**-1.27 p.p.**)
- **cobertura**: `0.945 -> 0.975` (**+3.0 p.p.**)
- **tamanho médio da sugestão**: `11.0 -> 11.0` (sem mudança)

Leitura operacional:
- A variante B melhorou o resultado **efetivo** do objetivo de negócio (acerto em até 4 tentativas considerando cobertura), sem inflar lista de aposta.
- Houve pequena queda no `conditional_hit@4`, compensada por aumento de cobertura.

## 5. Interpretação técnica

1. Preservar ranking por score no caminho final reduz perda de informação antes da fusão.
2. O ganho líquido observado veio majoritariamente por maior cobertura, mantendo lista no limite de 11.
3. O efeito não foi uniforme em todos os cenários (base-only, optimized-only, fusion), reforçando necessidade de medir pipeline real.

## 6. Alterações aplicadas nesta etapa

1. `apps/api/services/final_suggestion_frontend.py`
- `build_base_suggestion(..., preserve_ranking=False)` agora permite preservar ordem por score quando necessário.

2. `apps/api/routes/patterns.py`
- O helper de produção de `final-suggestion` foi simplificado e fixado no comportamento da variante B.
- A branch experimental A/B foi removida do caminho de produção.
- Mudança restrita ao endpoint `final-suggestion`.

3. `apps/api/scripts/final_suggestion_experiment.py`
- Script de replay A/B/C com lógica comparativa própria (independente do helper de produção) e métricas:
  - Hit@1/2/3/4 (conditional e effective)
  - coverage
  - average list size
  - distribuição de confiança
  - cenários fusion_default / base_only / optimized_only

Artefato gerado (rodada ampliada):
- `docs/final-suggestion-confidence-analysis.json`

## 7. Reprodutibilidade

Com o venv do projeto:

```bash
/Users/allanroberto/projetos/roleta-automatica/venv/bin/python \
  apps/api/scripts/final_suggestion_experiment.py \
  --disable-full \
  --max-numbers 11 \
  --output docs/final-suggestion-confidence-analysis.json
```
