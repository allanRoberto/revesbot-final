# Gatilhos orbitais prospectivos

O monitor de gatilhos consome as previsoes imutaveis de `orbit_prediction_trials` e
registra entradas em `orbit_trigger_trials`. Ele opera em shadow mode: nao publica
sinais no Redis e nao envia apostas.

## Garantias de medicao

- O primeiro inicio apenas grava a baseline atual; previsoes anteriores nao sao
  reconstruidas.
- A entrada e congelada no giro de ativacao e os resultados comecam no giro seguinte.
- Toda estrategia usa cinco tentativas.
- Uma entrada somente entra no denominador depois que os cinco giros foram observados.
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
- `/orbit/triggers`
- `/orbit/triggers/{strategy_slug}`

As paginas exibem janelas de 1, 3, 6, 12 e 24 horas, acumulado geral, curva da primeira
a quinta tentativa, cobertura media, melhor horario e o historico congelado por roleta.
