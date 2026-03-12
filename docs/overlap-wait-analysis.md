# Overlap Wait Analysis

## Escopo
Análise focada em decisão de estratégia (entrar, cancelar, esperar), sem refatoração estrutural.

## Fonte e Dataset
- fonte utilizada: `redis:redis://127.0.0.1:6379/0`
- sinais lidos: `1594`
- sinais válidos para o padrão `API_FINAL_SUGGESTION_10`: `1594`
- tentativas simuladas: até `4`
- janelas testadas: `1, 2, 3, 4, 5, 6, 8, 10`

## Aviso Metodológico (Contrafactual)
Esta análise de esperar/cancelar é **contrafactual** e baseada em **reconstrução do histórico** (`snapshot` + `history`).
Nos casos observados com status real `win/lost`, a reconstrução reproduziu o desfecho em aproximadamente:
- aderência: `96.39%`
- base de validação: `1330` sinais

## Schema Real Utilizado de /signals
- `triggers[0]`: gatilho (100%)
- `bets`: números da aposta (100%)
- `snapshot`: histórico da formação do padrão (100%)
- `history`: histórico ampliado pós-emissão (100%)
- `gales`, `attempts`, `status` (100%)
- `temp_state.confidence_score`, `temp_state.confidence_label` (100%)
- `spins_required`: presença histórica baixa (quase nula no legado)
- `paid_waiting`: ausente no legado histórico atual

## Campos Úteis para Reconstrução
- gatilho: `triggers[0]` e validação com `snapshot[0]`
- aposta: `bets`
- contexto anterior ao gatilho: `snapshot[1:1+lookback]`
- tentativas máximas: `gales` (cap em 4 para simulação)
- confidence: `temp_state.confidence_score` e `temp_state.confidence_label`
- desfecho observado: `status`
- desfecho reconstruído: primeiros spins pós-gatilho inferidos de `history` vs `snapshot`

## Limitações do Dataset
- `paid_waiting` não existe historicamente no legado atual, então taxa de "pagou na espera" é inferida contrafactualmente.
- `spins_required` quase não aparece no histórico legado.
- parte das perguntas de espera/cancelamento depende de simulação de política (não de observação direta em produção).

## Perguntas Diretas vs Inferência
Perguntas respondidas diretamente pelos dados observados:
- distribuição de confidence
- frequência de overlap por janela
- desempenho observado do fluxo sem política contrafactual adicional

Perguntas que exigem inferência/reconstrução:
- "esperar melhora ou piora" vs "cancelar" (comparativo contrafactual)
- "pagou na espera"
- "teria ganho se não esperasse"
- "espera evitou entrada ruim"

## Variáveis de Overlap
Para cada janela de lookback:
- `overlap_unique = |set(bets) ∩ set(contexto_pre_gatilho)|`
- `overlap_hits = contagem de ocorrências de números de bets no contexto`
- `overlap_ratio = overlap_unique / len(bets)`
- registro detalhado por sinal/janela em: `docs/overlap-wait-analysis-overlap-features.csv`

## Buckets de Confidence
Buckets originais avaliados: `<40`, `40-49`, `50-59`, `60-69`, `70+`.
Tratamento de baixa massa:
- bucket original `40-49` tem baixa massa (`n=1`), tratado por merge para análise.

Buckets efetivos usados na análise:
- `<= 59`: 110 sinais
- `60-69`: 626 sinais
- `70+`: 858 sinais

## Estratégias Comparadas
- A: sem filtro (entra direto)
- B: cancela com `overlap >= 1`
- C: espera 1 spin com `overlap >= 1` (se pagar na espera, cancela)
- D: espera 2 spins com `overlap >= 1` (se pagar na espera, cancela)
- E: espera proporcional (`1->1`, `2->2`, `3+->3`)
- F1/F2/F3: cancela com `overlap >= N` (`N=1,2,3`)

## Top Resultados (geral)
- janela `3` | F3 `Cancelar overlap>=3` | coverage `93.10%` | win_rate_entered `86.19%` | cancel_rate `6.90%` | net_wl `1075`
- janela `1` | C `Esperar 1 spin` | coverage `83.50%` | win_rate_entered `86.55%` | cancel_rate `16.50%` | net_wl `974`
- janela `1` | E `Espera proporcional` | coverage `83.50%` | win_rate_entered `86.55%` | cancel_rate `16.50%` | net_wl `974`
- janela `2` | F2 `Cancelar overlap>=2` | coverage `81.68%` | win_rate_entered `86.18%` | cancel_rate `18.32%` | net_wl `943`
- janela `4` | F3 `Cancelar overlap>=3` | coverage `77.92%` | win_rate_entered `85.83%` | cancel_rate `22.08%` | net_wl `891`
- janela `1` | D `Esperar 2 spins` | coverage `73.34%` | win_rate_entered `87.00%` | cancel_rate `26.66%` | net_wl `866`
- janela `2` | C `Esperar 1 spin` | coverage `73.02%` | win_rate_entered `86.25%` | cancel_rate `26.98%` | net_wl `845`
- janela `3` | C `Esperar 1 spin` | coverage `67.63%` | win_rate_entered `86.36%` | cancel_rate `32.37%` | net_wl `785`

## Recomendação Prática (Regra)
Janela recomendada para olhar para trás:
- **`3` casas**

Regra proposta por overlap e confidence:
- confidence de corte: `>= 60` = alta, `< 60` = baixa/média
- overlap `1` -> baixa/média: `enter` | alta: `enter`
- overlap `2` -> baixa/média: `wait1` | alta: `enter`
- overlap `3+` -> baixa/média: `wait2` | alta: `enter`
- overlap `0` -> `enter` (sempre)
- métricas da regra buscada (janela 3): coverage `99.31%`, win_rate_entered `86.10%`, cancel_rate `0.69%`, net_wl `1144`

## Resposta Objetiva da Etapa
- Com os dados históricos disponíveis, é possível comparar entrar vs cancelar vs esperar.
- O efeito de confidence foi estratificado com merge de buckets de baixa massa.
- A recomendação acima já traduz o resultado em política operacional por `overlap (1/2/3+)` e confidence.

## Arquivos Gerados
- CSV geral: `docs/overlap-wait-analysis.csv`
- CSV confidence: `docs/overlap-wait-analysis-confidence.csv`
- CSV overlap: `docs/overlap-wait-analysis-overlap.csv`
- CSV features overlap: `docs/overlap-wait-analysis-overlap-features.csv`
- HTML: `docs/overlap-wait-analysis.html`
