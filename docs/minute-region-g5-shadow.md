# Validação do cenário sombra G5

## Objetivo

Reduzir a janela operacional de 10 para 5 tentativas, manter assertividade acima de 95% e preservar pelo menos 50% dos sinais cadastrados.

## Metodologia

- Roleta: `pragmatic-auto-roulette`.
- Período reconstruído: 30 dias.
- Sinais reconstruídos minuto a minuto: 43.200.
- Cada sinal usa somente os 10 dias anteriores no intervalo de ±3 minutos.
- Centros analisados com 3 vizinhos e os 2 centros mais fortes.
- O centro alternativo é recalculado para cada quantidade de vizinhos.
- O resultado do próprio sinal usa somente os cinco giros posteriores.
- Nenhuma informação futura participa da formação do sinal.

## Resultado

| Cenário | Assertividade G5 | Limite inferior 95% | Retenção | Cobertura média |
|---|---:|---:|---:|---:|
| 3 vizinhos | 92,62% | 92,37% | 100% | 15,25 |
| 4 vizinhos | 97,22% | 97,07% | 100% | 19,32 |
| 5 vizinhos | 99,23% | 99,14% | 100% | 23,48 |

O cenário escolhido para observação ao vivo é `g5_n4_v1`: quatro vizinhos, dois centros, centro alternativo recalculado e horizonte de cinco tentativas.

## Interpretação

O ganho de assertividade vem principalmente do aumento da cobertura. Para quatro vizinhos, a expectativa matemática baseada somente na cobertura foi 97,37%, próxima dos 97,22% observados. O resultado não deve ser interpretado como evidência de vantagem preditiva ou de lucratividade.

## Reproduzir

Execute no ambiente que possui acesso somente leitura ao MongoDB:

```bash
PYTHONPATH=. .venv/bin/python apps/api/scripts/minute_region_g5_shadow_backtest.py --days 30 --step-minutes 1
```

O script imprime JSON com a configuração, quantidade de sinais, assertividade acumulada por tentativa, retenção, cobertura média e intervalo de confiança.

## Promoção

O modo sombra não promove a estratégia automaticamente. A página exige pelo menos 1.000 sinais concluídos e apresenta separadamente:

- assertividade acima de 95% em G5;
- retenção mínima de 50%;
- comparação com a configuração atual;
- cobertura média;
- percentuais acumulados de G1 a G5.
