# Dynamic Pattern Weighting (Shadow First)

Data: 2026-03-10  
Escopo: estratégia de ajuste dinâmico de pesos por padrão para aumentar assertividade da API com controle de risco.  
Status desta etapa: desenho e plano de experimento. Sem alteração no runtime de produção.

## 1. Objetivo e princípio de segurança

Objetivo:
- melhorar assertividade da sugestão final ajustando peso de padrões com base em performance recente, sem destruir calibragem atual.

Princípios obrigatórios:
- manter `base_weight` como referência estável.
- calcular `dynamic_weight` separadamente.
- aplicar no score apenas como `effective_weight = base_weight * dynamic_weight`.
- não ligar auto-ajuste em produção nesta fase.
- executar em shadow/replay, com snapshot versionado e promoção manual por critério objetivo.

## 2. Estado atual do pipeline (código real)

Referências principais:
- engine e score: [apps/api/patterns/engine.py](/Users/allanroberto/projetos/roleta-automatica/revesbot-final/apps/api/patterns/engine.py)
- fusão final: [apps/api/patterns/final_suggestion.py](/Users/allanroberto/projetos/roleta-automatica/revesbot-final/apps/api/patterns/final_suggestion.py)
- telemetria: [apps/api/services/pattern_telemetry.py](/Users/allanroberto/projetos/roleta-automatica/revesbot-final/apps/api/services/pattern_telemetry.py)
- decay: [apps/api/services/pattern_decay.py](/Users/allanroberto/projetos/roleta-automatica/revesbot-final/apps/api/services/pattern_decay.py)
- correlação: [apps/api/services/pattern_correlation.py](/Users/allanroberto/projetos/roleta-automatica/revesbot-final/apps/api/services/pattern_correlation.py)
- endpoints de métricas/tuning: [apps/api/routes/patterns.py](/Users/allanroberto/projetos/roleta-automatica/revesbot-final/apps/api/routes/patterns.py)

Fórmula atual de peso efetivo por número (engine):
- `effective_weight = weight * adaptive_multiplier * correlation_boost * decay_multiplier`

Pontos críticos já identificados:
- telemetria aprende pouco com erro porque parte relevante dos casos permanece em `pending` e não vira `miss` operacional para atualização.
- crédito de resultado ainda tende a ser coletivo para todos os padrões ativos do sinal, reduzindo precisão de causalidade por padrão.

## 3. Separação explícita de métricas

### 3.1 Desempenho bruto do padrão

Esta camada mede o padrão isoladamente em termos estatísticos diretos.

Métricas mínimas por padrão:
- `sample_size`: quantidade de sinais emitidos pelo padrão.
- `coverage`: fração de casos elegíveis em que o padrão contribuiu.
- `hit_rate`: taxa de acerto no horizonte definido.
- `hit@1`, `hit@2`, `hit@3`, `hit@4`: acerto por número de tentativas.

Observação:
- desempenho bruto alto não implica contribuição real alta no ensemble.

### 3.2 Contribuição marginal real no ensemble

Esta camada mede impacto causal aproximado no resultado final do ensemble.

Métrica principal:
- `delta_effective_hit@4_remove_pattern = effective_hit@4(ensemble_completo) - effective_hit@4(ensemble_sem_padrao_X)`

Como medir:
- replay controlado com mesmo dataset e mesmas posições.
- executar baseline (todos padrões) e cenário ablado (remove 1 padrão por vez).
- calcular delta por padrão.

Interpretação:
- delta positivo alto: padrão agrega valor real.
- delta próximo de zero: padrão possivelmente redundante.
- delta negativo: padrão pode estar degradando resultado.

## 4. Proposta de dynamic_weight (conservadora)

Estrutura:
- `base_weight`: permanece no JSON de definição.
- `dynamic_weight`: calculado externamente (snapshot).
- `effective_weight = base_weight * dynamic_weight`.

Requisitos de `dynamic_weight`:
- piso e teto: evitar explosão ou colapso de peso.
- suavização temporal: evitar oscilação de curto prazo.
- proteção de baixa amostra: shrink para neutro quando `sample_size` baixo.
- decaimento recente por erro: penalizar sequência recente ruim sem zerar abruptamente.

Modelo sugerido:
- `posterior_rate` com prior (shrinkage).
- `lift` relativo ao baseline global.
- `sample_gate` para reduzir impacto com pouca amostra.
- `recent_decay` por miss streak recente.
- `target_weight` limitado por `floor/ceil`.
- `dynamic_weight_t` via EMA (suavização).

Faixa inicial recomendada:
- `floor=0.75`
- `ceil=1.30`
- `neutral=1.0`

## 5. Janela de avaliação e anti-overfitting

Candidatas:
- 100: responsiva, mais ruidosa.
- 200: equilíbrio.
- 500: mais estável, menos responsiva.

Recomendação inicial:
- usar 200 como janela primária.
- validar robustez em paralelo com 100 e 500.
- opcional: blend multi-janela para reduzir overfitting de curtíssimo prazo.

Regras anti-overfitting:
- não ajustar peso com amostra abaixo de mínimo.
- limitar variação máxima por ciclo.
- exigir consistência de ganho em múltiplas janelas e roletas.
- validar calibração de confiança (não só hit rate bruto).

## 6. Plano técnico do experimento (shadow)

### 6.1 Objetivo experimental

Comparar baseline atual vs candidate dynamic weighting sem tocar produção.

### 6.2 Entradas

- histórico replay por roleta.
- pipeline real de sugestão (mesma lógica de `final-suggestion`).
- conjunto de snapshots candidatos de `dynamic_weight`.

### 6.3 Cenários

- baseline: `dynamic_weight=1.0` para todos.
- candidate A/B/C: diferentes hiperparâmetros de cálculo de `dynamic_weight`.
- ablação por padrão em cada cenário.

### 6.4 Métricas de saída

Globais:
- `coverage`
- `effective_hit@1..4`
- `avg_list_size`
- calibração por bucket de confiança

Por padrão (duas camadas):
- camada bruta: `sample_size`, `coverage`, `hit_rate`, `hit@1..4`
- camada marginal: `delta_effective_hit@4_remove_pattern`

### 6.5 Artefatos

Sugestão de arquivos:
- `apps/api/data/dynamic_weight_snapshots/<timestamp>.json`
- `docs/dynamic-weighting-shadow-report-<timestamp>.md`
- `docs/dynamic-weighting-shadow-report-<timestamp>.json`

Snapshot sugerido:
- versão do esquema
- janela usada
- hiperparâmetros
- pesos dinâmicos por padrão
- métricas base por padrão
- data/hora de geração

## 7. Critério objetivo para promoção manual

Promover snapshot somente se:
- `effective_hit@4` não piorar versus baseline.
- `coverage` não cair além do limite acordado.
- calibração não piorar (bucket-level / erro de calibração).
- ganhos repetidos em múltiplas janelas (100/200/500) e múltiplas roletas.
- sem concentração excessiva de peso em poucos padrões.

Sem atender tudo acima:
- não promover.
- revisar hiperparâmetros e repetir shadow.

## 8. Política operacional desta etapa

Não fazer agora:
- auto-ajuste em produção.
- escrita automática em `definitions/*.json` por job de runtime.
- alteração silenciosa de pesos ativos.

Fazer agora:
- análise, replay e documentação.
- geração de snapshots candidatos fora do caminho crítico.
- decisão manual baseada em relatório objetivo.

## 9. Próximos passos (implementação futura, após aprovação)

1. Criar módulo de cálculo offline de `dynamic_weight` (sem acoplamento direto no runtime crítico).
2. Criar script de shadow replay com ablação por padrão.
3. Gerar snapshots versionados e relatório comparativo baseline vs candidatos.
4. Definir processo formal de promoção manual de snapshot.
5. Só depois considerar leitura opcional de snapshot no runtime, com feature flag desligada por padrão.

