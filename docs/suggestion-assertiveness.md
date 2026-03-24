# Suggestion Assertiveness - API

Data: 2026-03-08
Escopo: mapeamento da lógica real de sugestão da API e hipóteses de perda de assertividade, sem refatoração.

## Status de consolidação (2026-03-08)

- O caminho de produção de `POST /api/patterns/final-suggestion` foi consolidado com preservação de ranking por score (baseline B).
- A hipótese de perda por reordenação numérica prematura foi mitigada no endpoint single de `final-suggestion`.
- A comparação A/B/C permanece em script experimental; não é branch ativa do caminho de produção.
- O endpoint antigo `final-suggestion-batch` foi removido; `final-suggestion` passou a ser o caminho único para leitura operacional.

## 1. Endpoints de sugestão e medição

### Sugestão (produção)
- `POST /api/patterns/optimized-suggestion` (`apps/api/routes/patterns.py:151`)
- `POST /api/patterns/final-suggestion` (`apps/api/routes/patterns.py:566`)

### Medição / tuning (suporte à assertividade)
- `POST /api/patterns/metrics/backtest` (`apps/api/routes/patterns.py:240`)
- `POST /api/patterns/backtest/full` (`apps/api/routes/patterns.py:868`)
- `GET /api/patterns/metrics/events` (`apps/api/routes/patterns.py:314`)
- `POST /api/patterns/metrics/apply-multipliers` (`apps/api/routes/patterns.py:330`)
- `POST /api/patterns/metrics/auto-tune` (`apps/api/routes/patterns.py:441`)
- `GET /api/patterns/filters/config` (`apps/api/routes/patterns.py:908`)

## 2. Pipeline real da sugestão final (`/api/patterns/final-suggestion`)

1. Normalização de entrada e contexto de foco
- Normaliza `history`, `focus_number`, `from_index`, pesos e parâmetros de inversão/cerco.
- Evidência: `apps/api/routes/patterns.py:580-623`.

2. Sugestão base (frontend-like)
- Usa `build_focus_context`, `compute_confidence` e `build_base_suggestion`.
- Evidência: `apps/api/routes/patterns.py:616-633`, `apps/api/services/final_suggestion_frontend.py:109`, `:161`, `:412`.

3. Sugestão otimizada (PatternEngine)
- Chama `pattern_engine.evaluate(...)` com histórico + base_suggestion + overrides.
- Evidência: `apps/api/routes/patterns.py:644-650`, `apps/api/services/pattern_engine.py:217`.

4. Fusão final
- Usa `build_final_suggestion(...)` com listas base/otimizada, score detalhado e contexto de inversão.
- Evidência: `apps/api/routes/patterns.py:664-678`, `apps/api/services/final_suggestion_frontend.py:597`.

## 3. Componentes que influenciam a decisão

### 3.1 PatternEngine (núcleo otimizado)
- Carrega definições ativas (`44` ativas de `45`) e ordena por prioridade.
- Evidência: `apps/api/services/pattern_engine.py:1202+`, `apps/api/patterns/definitions/*.json`.
- Fórmula por número: `effective_weight = weight * adaptive_multiplier * correlation_boost * decay_multiplier`.
- Evidência: `apps/api/services/pattern_engine.py:394-400`, `:449-455`.
- Score líquido: `positive - negative`.
- Evidência: `apps/api/services/pattern_engine.py:541-552`.
- Confiança API: `_build_confidence` + `_build_confidence_context` + `_rebalance_api_confidence` + `_merge_confidence`.
- Evidência: `apps/api/services/pattern_engine.py:878`, `:979`, `:1059`, `:908`.
- Filtro de qualidade pode bloquear saída (`available=False`).
- Evidência: `apps/api/services/pattern_engine.py:754-806`.

### 3.2 Filtros de qualidade
- `min_patterns >= 3`
- `min_confidence >= 55`
- `max_negative_pressure <= 0.45`
- `min_overlap_ratio >= 0.25`
- Evidência: `apps/api/config/suggestion_filters.json`, `apps/api/services/suggestion_filter.py:47-50`.

### 3.3 Decay e correlação
- Decay padrão: inicia após 3 misses, desabilita em 8, max 50%.
- Evidência: `apps/api/services/pattern_decay.py:23-27`.
- Correlação por matriz existe como módulo e endpoint operacional.
- Evidência: `apps/api/services/pattern_correlation.py`, `apps/api/routes/patterns.py:820+`.

### 3.4 Fusão final
- Combina rank base + rank otimizado + `opt_net` + bônus de interseção + bônus de puxados + penalidade de inversão.
- Evidência: `apps/api/services/final_suggestion_frontend.py:665-704`.

## 4. Hipóteses prioritárias de perda de assertividade

### H1) Perda de ordenação por score na base
- Observação: a base é ranqueada por score, mas o retorno final é ordenado numericamente.
- Evidência: `apps/api/services/final_suggestion_frontend.py:533-535` (`return sorted(ranked[:12])`).
- Impacto provável: o sinal de ranking da base pode ser perdido antes da fusão.

### H2) Perda de ordenação por score no otimizado
- Observação: o engine seleciona por score, mas transforma a saída em lista ordenada numericamente.
- Evidência: `apps/api/services/pattern_engine.py:703` (`suggestion = sorted([...])`).
- Impacto provável: perda de informação de prioridade dos números no pipeline final.

### H3) Fusão final usa posição da lista como rank após reordenação numérica
- Observação: a fusão calcula rank por posição (`base_pos` / `opt_pos`) das listas recebidas.
- Evidência: `apps/api/services/final_suggestion_frontend.py:641-642`.
- Impacto provável: ranks deixam de refletir score real quando listas já vieram reordenadas por número.

### H4) Histórico: o batch final simplificava demais e descartava ranking
- Observação: a versão antiga do batch juntava sets (`optimized ∪ legacy`) e cortava por ordenação numérica.
- Impacto observado: confiança e lista batch podiam divergir do comportamento do endpoint final single.

### H5) Diferença entre o backtest atual e o pipeline real de `/final-suggestion`
- Observação: rotinas de backtest usam majoritariamente `pattern_engine.evaluate`, não a fusão completa de `/final-suggestion`.
- Evidência: `apps/api/routes/patterns.py:257`, `:348`, `:470`, `apps/api/services/backtesting.py:140`.
- Impacto provável: métrica de assertividade atual pode não representar fielmente o comportamento em produção do endpoint final.

### H6) `legacy_processing_bridge` como fonte de variabilidade
- Observação: há bridge ativa para padrões legados em `apps/signals/patterns` (fallback `src/signals/patterns`).
- Evidência: `apps/api/patterns/definitions/legacy_processing_bridge.json` (ativa), `apps/api/services/pattern_engine.py:1283+`.
- Impacto provável: variabilidade adicional por dependência externa ao núcleo da API e por grande superfície de padrões legados.

### H7) Correlação por matriz aparentemente fora do caminho real de score
- Observação: scoring usa `get_pattern_correlation_boost` (hit-rate interno por padrão), enquanto `compute_correlation_boost` (matriz) não aparece no fluxo principal de `evaluate`.
- Evidência: uso no scoring em `apps/api/services/pattern_engine.py:392`, `:446`, método em `:3999`; método de matriz existe em `:4141`.
- Impacto provável: parte da arquitetura de correlação pode não estar contribuindo no score final por número como esperado.

## 5. Partes do pipeline mais críticas para assertividade

1. Ordenação/ranking preservado até a fusão (base + otimizado).
2. Thresholds dos filtros de qualidade (`min_confidence`, `negative_pressure`, `overlap`).
3. Multiplicadores adaptativos + decay (sensíveis a janela e amostra).
4. Participação do legado (`legacy_base_suggestion` + `legacy_processing_bridge`).
5. Consistência entre endpoint medido e endpoint usado em produção.

## 6. Plano prático de medição (sem alterar lógica)

### 6.1 Replay histórico do endpoint `/final-suggestion`
Objetivo: medir assertividade do pipeline real de produção.

Procedimento:
1. Fixar um histórico canônico por roleta (mesmo formato usado hoje pela API).
2. Para cada posição `idx` elegível, chamar `/api/patterns/final-suggestion` com:
- `history` completo
- `from_index = idx`
- `focus_number = history[idx]` (quando aplicável)
- parâmetros padrão da rota
3. Registrar saída completa: `available`, `list`, `confidence.score`, `breakdown`, `optimized_*`, `base_*`.
4. Avaliar hit por janelas de tentativas usando a mesma convenção temporal já usada em telemetry/backtest.

### 6.2 Hit rate por janela de tentativas
Calcular, no mínimo:
- Hit@1
- Hit@2
- Hit@3
- Hit@5
- Hit@12

Também reportar:
- cobertura de sinais (`available=true` / total)
- tamanho médio da lista sugerida
- distribuição de confiança

### 6.3 Calibração por buckets de confiança
- Buckets de 10 pontos: 0-9, 10-19, ..., 90-100.
- Para cada bucket: `signals`, `hits`, `hit_rate`.
- Comparar confiança declarada vs taxa real observada.

### 6.4 Ablação controlada por componente
Executar replay com variações, mantendo dataset e janela iguais:

1. Base-only
- `base_weight=1.0`, `optimized_weight=0.0`.

2. Optimized-only
- `base_weight=0.0`, `optimized_weight=1.0`.

3. Default atual
- `base_weight=0.4`, `optimized_weight=0.6`.

4. Sem inversão
- `inversion_enabled=false`.

5. Filtros ON/OFF
- usar endpoints de filtro (`disable-all`, `enable-all`) em ambiente controlado.

6. Com/sem `legacy_processing_bridge`
- teste controlado alterando apenas o `active` da definição do padrão legado, com rollback explícito após experimento.

7. Com/sem auto-tune recente
- comparar pesos originais vs pesos ajustados por `apply-multipliers/auto-tune` em janela fixa.

## 7. Observações de maturidade da medição

- O projeto já possui infraestrutura útil de medição (`pattern_telemetry`, `backtesting`, endpoints de métricas).
- A lacuna principal é alinhar a medição ao endpoint final real (`/final-suggestion`) para evitar viés de avaliação.
- A prioridade operacional é fechar essa lacuna antes de novas complexidades no fluxo de sinais.

## 8. Próximos ajustes candidatos (futuros, sem aplicar agora)

1. Medir continuamente no pipeline real de produção (replay padronizado).
2. Revisar papel do `legacy_processing_bridge` com experimento controlado.
3. Validar se a correlação por matriz deve entrar no score por número (ou documentar claramente seu papel real).
