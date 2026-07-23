# Gatilhos orbitais prospectivos

O monitor de gatilhos consome as previsoes imutaveis de `orbit_prediction_trials` e
registra entradas em `orbit_trigger_trials`. Ele opera em shadow mode: nao publica
sinais no Redis e nao envia apostas.

## Garantias de medicao

- O primeiro inicio apenas grava a baseline atual; previsoes anteriores nao sao
  reconstruidas.
- A entrada e congelada no giro de ativacao e os resultados comecam no giro seguinte.
- As oito estrategias originais usam cinco tentativas; `soma-ultimos-3` usa dez.
- Uma entrada somente entra no denominador depois que todos os giros da estrategia
  foram observados.
- O primeiro acerto define o resultado estatistico e financeiro. Os giros restantes
  continuam armazenados somente para observacao.
- As chaves `event_id` e `candidate_id` possuem indices unicos para impedir duplicacao
  depois de reinicios.
- A linha de base aleatoria usa a cobertura real de cada entrada, pois estrategias com
  vizinhos possuem quantidades diferentes de numeros.

## Estrategias v1

1. `green-primeira`: a sugestao anterior acerta no primeiro giro, um giro adicional e
   aguardado e o Top 9 entao vigente e congelado.
2. `allan`: toda sugestao e expandida com um vizinho fisico de cada lado.
3. `inception`: exige pivo mais recente igual a zero e seis ausencias do Top 9 original.
4. `inception-primeiros-4`: acompanha os quatro primeiros alvos durante seis giros e
   entra neles com um vizinho de cada lado.
5. `interrompimento`: exige tres pagamentos com intervalos de no maximo quatro giros;
   depois de qualificada, ativa quando completa cinco ausencias e usa o Top 9 atual.
6. `distancia`: observa o primeiro pagamento na distancia `D`, aguarda `D-1` giros e
   reutiliza o Top 9 original. A descoberta da distancia expira em 36 giros.
7. `ryan`: exige exatamente uma confluencia entre os tres pivos e o Top 9. Os outros
   pivos geram vizinhos, suas familias por ultimo digito sao cruzadas com o Top 9 e os
   centros resultantes recebem dois vizinhos fisicos de cada lado.
8. `ryan-2`: exige que os tres primeiros numeros da sugestao alternem entre vermelho,
   preto e vermelho, ou entre preto, vermelho e preto. Todos os alvos da cor repetida
   presentes no Top 9 recebem um vizinho fisico de cada lado. O zero nos tres primeiros
   lugares nao ativa a estrategia.
9. `soma-ultimos-3`: soma os digitos dos tres resultados mais recentes, sem reduzir
   novamente o total. O total ou um de seus vizinhos fisicos precisa aparecer entre os
   quatro primeiros numeros da sugestao. Repeticoes exatas, qualquer par de espelhos e
   um trio formado somente por numeros de um digito invalidam o gatilho. A entrada usa
   o Top 9 sem expansao, acompanha dez giros e espera mais um giro antes de voltar a
   validar uma entrada naquela roleta.

## Execucao

```bash
ORBIT_TRIGGER_ENABLED=1 \
ORBIT_TRIGGER_MAX_ATTEMPTS=5 \
.venv/bin/python apps/monitoring/orbit_triggers/worker.py
```

No PM2, o processo e `orbit-trigger-monitor-<ambiente>`.

## API e interface

- `GET /api/orbit-triggers/catalog?roulette_ids=...`
- `GET /api/orbit-triggers/{strategy_slug}?roulette_ids=...&history_limit=20`
- `POST /api/orbit-triggers/profitability`
- `/orbit/triggers`
- `/orbit/triggers/{strategy_slug}`

As paginas exibem janelas de 1, 3, 6, 12 e 24 horas, acumulado geral, curva ate a ultima
tentativa de cada estrategia, quantidade exata de sinais cujo primeiro acerto ocorreu
em cada tentativa, cobertura media, melhor horario e o historico congelado por roleta.

## Calculadora de lucratividade

A calculadora usa somente entradas prospectivas encerradas e respeita a janela de tempo
selecionada na pagina. A banca e simulada em ordem cronologica, separadamente para cada
combinacao de estrategia e roleta. Nao existe banca ou sequencia financeira acumulada
entre mesas.

- A banca inicial e as fichas inteiras por numero sao configuradas pelo usuario. Cada
  estrategia utiliza apenas as fichas correspondentes ao seu total de tentativas.
- Cada roleta inicia uma simulacao independente com a mesma banca configurada.
- O custo de cada tentativa e `ficha por numero * quantidade de alvos`.
- No acerto, o retorno bruto e `ficha por numero * 36`.
- Depois do primeiro acerto daquele sinal, as tentativas restantes nao sao executadas.
- Sem acerto, todos os investimentos previstos para aquela estrategia sao debitados.
- Se a banca nao cobrir a proxima tentativa, a simulacao para naquele ponto e informa o
  sinal e a tentativa interrompidos.
- O ROI exibido e `lucro liquido / total investido`; o grafico representa o saldo da
  banca depois de cada sinal historico.

O endpoint recebe `initial_bank`, de cinco a dez fichas inteiras por numero em
`attempt_stakes`,
`window`, os IDs das
roletas e, opcionalmente, uma lista de `strategy_slugs`. A resposta agrupa os resultados
em `roulettes[]`, cada uma com suas proprias `strategies[]`. A camada Next.js injeta os
IDs das roletas autorizadas no servidor, sem aceitar esse escopo diretamente do
navegador.
