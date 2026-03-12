# Final Suggestion Confidence Analysis

Data: 2026-03-08  
Foco: validar estabilidade do ganho de ranking preservado e utilidade operacional da confidence para o objetivo de negócio (11 fichas, até 4 tentativas).

## 1. Escopo e regras fixas do experimento

- Pipeline avaliado: `POST /api/patterns/final-suggestion`.
- Limite fixo em todas as variantes e amostras:
  - `max_numbers = 11`
  - `optimized_max_numbers = 11`
- Métricas principais:
  - `Hit@1/2/3/4`
  - `coverage`
  - `average_list_size`
  - `effective_hit@4`
  - `conditional_hit@4`
- Variantes:
  - **A_current**
  - **B_rank_preserved** (baseline oficial de produção)
  - **C_experimental_engine_rank** (isolada, experimental)

Artefato bruto: `docs/final-suggestion-confidence-analysis.json`.

## 2. Amostras executadas

- Executadas: `200`, `500`, `1000`.
- Full dataset:
  - casos disponíveis: `52.911`
  - estimativa: `6.568s` (~109 min)
  - orçamento de execução: `1.500s` (~25 min)
  - status: **não viável nesta rodada**

## 3. Estabilidade do ganho (A vs B)

### Amostra 200
- A: coverage `0.925`, effective_hit@4 `0.720`, conditional_hit@4 `0.778378`, avg_size `11.0`, casos disponíveis `185`.
- B: coverage `0.965`, effective_hit@4 `0.745`, conditional_hit@4 `0.772021`, avg_size `10.958549`, casos disponíveis `193`.
- Delta (B-A): coverage `+0.040`, effective_hit@4 `+0.025`, conditional_hit@4 `-0.006357`.

### Amostra 500
- A: coverage `0.942`, effective_hit@4 `0.708`, conditional_hit@4 `0.751592`, avg_size `10.953291`, casos disponíveis `471`.
- B: coverage `0.974`, effective_hit@4 `0.724`, conditional_hit@4 `0.743326`, avg_size `10.926078`, casos disponíveis `487`.
- Delta (B-A): coverage `+0.032`, effective_hit@4 `+0.016`, conditional_hit@4 `-0.008266`.

### Amostra 1000
- A: coverage `0.937`, effective_hit@4 `0.705`, conditional_hit@4 `0.752401`, avg_size `10.983991`, casos disponíveis `937`.
- B: coverage `0.968`, effective_hit@4 `0.724`, conditional_hit@4 `0.747934`, avg_size `10.922521`, casos disponíveis `968`.
- Delta (B-A): coverage `+0.031`, effective_hit@4 `+0.019`, conditional_hit@4 `-0.004467`.

Leitura:
- O ganho em `effective_hit@4` da variante B se manteve positivo em todas as amostras (`+1.6` a `+2.5 p.p.`).
- O ganho continua vindo principalmente de maior cobertura, sem inflar tamanho de lista.

## 4. Variante C (experimental, isolada)

- Resultado observado: C ficou **idêntica à B** nas amostras `200/500/1000`.
- Interpretação: preservar ranking de base também na entrada do engine (além da fusão) não trouxe ganho adicional neste recorte.
- Importante: C permanece isolada e **não altera** o comportamento padrão de produção.
- A comparação A/B/C segue no script de experimento; o endpoint de produção permanece fixo em B.

## 5. Confidence por bucket (amostra 1000, variante B)

| Bucket | Casos absolutos | Coverage total | Conditional Hit@4 | Effective Hit@4 |
|---|---:|---:|---:|---:|
| 20-29 | 1 | 0.001 | 0.000000 | 0.000 |
| 30-39 | 1 | 0.001 | 0.000000 | 0.000 |
| 40-49 | 9 | 0.009 | 0.555556 | 0.005 |
| 50-59 | 551 | 0.551 | 0.751361 | 0.414 |
| 60-69 | 374 | 0.374 | 0.751337 | 0.281 |
| 70-79 | 32 | 0.032 | 0.750000 | 0.024 |

Observações:
- A massa real está em `50-69` (`925` casos de `1000` elegíveis).
- Acerto condicional em `50-59`, `60-69` e `70-79` ficou praticamente igual (~`0.75`).
- Faixas muito baixas (`<40`) têm pouquíssimos casos (2), mas ambos foram miss em Hit@4.

## 6. Thresholds operacionais (amostra 1000, variante B)

| Threshold | Casos absolutos | Coverage | Conditional Hit@4 | Effective Hit@4 |
|---|---:|---:|---:|---:|
| >=40 | 966 | 0.966 | 0.749482 | 0.724 |
| >=50 | 957 | 0.957 | 0.751306 | 0.719 |
| >=60 | 406 | 0.406 | 0.751232 | 0.305 |
| >=70 | 32 | 0.032 | 0.750000 | 0.024 |
| >=80 | 0 | 0.000 | 0.000000 | 0.000 |

Tradeoff:
- Subir de `>=50` para `>=60` derruba cobertura de `95.7%` para `40.6%` sem ganho real em `conditional_hit@4`.
- `>=70` é seletivo demais (apenas 32 casos), inviável como política principal.

## 7. Calibração da confidence

Variante B:
- ECE Hit@4:
  - amostra 200: `0.183575`
  - amostra 500: `0.160082`
  - amostra 1000: `0.162118`
- Monotonicidade (Hit@4 por bucket):
  - 200: `0.333333`
  - 500: `0.500000`
  - 1000: `0.600000`

Leitura:
- A confidence **não está bem calibrada** como probabilidade.
- Faixas mais altas não aumentaram de forma consistente o Hit@4 condicional neste recorte.

## 8. Recomendação operacional (objetivo 11 fichas / 4 tentativas)

### Faixa recomendada para entrar
- **Confidence >= 50**
- Justificativa (amostra 1000, B):
  - casos absolutos: `957`
  - coverage: `0.957`
  - conditional_hit@4: `0.751306`
  - effective_hit@4: `0.719`
- Mantém alta cobertura com desempenho estável.

### Faixa recomendada para não entrar
- **Confidence < 40**
- Justificativa:
  - casos absolutos muito baixos neste recorte (`2`)
  - ambos sem acerto em Hit@4
- É um bloqueio conservador e barato em cobertura.

### Faixa cinzenta / cautela
- **40 <= confidence < 50**
- Justificativa:
  - poucos casos (`9`) e `conditional_hit@4 = 0.555556`
  - amostra ainda pequena para regra rígida, mas sinaliza cautela.

## 9. Conclusões práticas desta etapa

1. O ganho de ranking preservado (B vs A) se sustentou em amostra maior para `effective_hit@4`.
2. A confidence, hoje, parece mais útil como filtro de bloqueio de baixa confiança do que como escala confiável de agressividade.
3. Para operação imediata:
   - manter B em produção
   - usar `confidence >= 50` como regra de entrada padrão
   - bloquear `<40`
   - tratar `40-49` com cautela.
