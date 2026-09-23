# Monitor live de trios top 6

O worker `apps/monitoring/scripts/triple_context_live_worker.py` acompanha apenas a
`pragmatic-auto-roulette` e usa o catálogo publicado de trios.

## Regra

- coleta três resultados sem sobreposição;
- consulta o trio em ordem exata e na direção à frente;
- registra uma entrada virtual nos seis primeiros números;
- confere somente o giro seguinte;
- depois do resultado, inicia um novo bloco de três números;
- trios com números repetidos ou sem evidência são catalogados como ignorados.

O worker não envia apostas para uma casa. A entrada é prospectiva e fica registrada
no MongoDB para aferição live sem viés retrospectivo.

## Persistência

- `triple_context_live_signals_v1`: entradas, rankings e resultados;
- `triple_context_live_state_v1`: cursor, bloco parcial e heartbeat.

O estado persistido impede duplicação após reinício. O identificador do último giro
do trio também possui índice único por roleta.

## Dashboard

- página: `/patterns/triple-context-live`;
- dados: `/api/patterns/triple-context-live`;
- autenticação: header `X-Live-Dashboard-Token`;
- variável obrigatória: `TRIPLE_CONTEXT_LIVE_DASHBOARD_TOKEN`.

O navegador guarda o token apenas em `sessionStorage`, portanto ele é removido ao
fechar a aba.
