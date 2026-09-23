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

- MongoDB: leitura dos resultados e do catálogo publicado;
- Redis `triple_context_live:v1:state:*`: cursor, bloco parcial e heartbeat;
- Redis `triple_context_live:v1:history:*`: entradas e resultados prospectivos;
- Redis `triple_context_live:v1:summary:*`: totais acumulados.

O estado persistido impede duplicação após reinício sem exigir escrita no MongoDB
histórico, cuja credencial da API permanece somente leitura.

## Dashboard

- página: `/patterns/triple-context-live`;
- dados: `/api/patterns/triple-context-live`;
- autenticação: header `X-Live-Dashboard-Token`;
- variável obrigatória: `TRIPLE_CONTEXT_LIVE_DASHBOARD_TOKEN`.

O navegador guarda o token apenas em `sessionStorage`, portanto ele é removido ao
fechar a aba.
