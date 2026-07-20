# Protocolo de validacao orbital

## Regra central

Toda previsao deve ser reconstruida como se estivesse no instante da decisao.
Nenhuma janela, frequencia, transicao, calibrador ou peso pode acessar o alvo ou
um registro posterior. O pipeline divide cada snapshot, sem embaralhar, em 60%
treino, 20% validacao e 20% teste.

O treino ajusta modelos e baselines. A validacao escolhe temperatura e conjunto
conformal. O teste fica intocado ate a avaliacao final. Alvos de horizonte que
cruzariam uma fronteira temporal sao descartados daquele bloco.

## Comparadores obrigatorios

- uniforme: `1/37` para cada numero;
- frequencia marginal calculada apenas no treino;
- transicao condicionada ao pivo calculada apenas no treino;
- baseline orbital explicavel;
- ranker e ensemble calibrado.

Para o proximo giro, um top 9 aleatorio acerta em `9/37 = 24,32%`; top 12, em
`12/37 = 32,43%`. Para varios giros, o relatorio tambem mostra o baseline
correspondente ao horizonte.

## Metricas

- `top9_at_1` e `top12_at_1`;
- acerto em qualquer giro do horizonte;
- log loss multiclasse e Brier score;
- massa de probabilidade do ranking;
- cobertura e tamanho do conjunto conformal;
- `exclusion_leak_rate` e quantidade de alegacoes de exclusao;
- taxa de abstencao;
- intervalos por bootstrap em blocos e Wilson para proporcoes.

Acerto dentro de tres tentativas deve ser reportado separadamente de acerto no
proximo giro. Misturar os dois infla artificialmente a avaliacao.

## Ablacao e estabilidade

O comando de ablacacao remove, uma por vez, as relacoes exata, sequencia
numerica, vizinho fisico, espelho, soma, familia terminal e setor. Uma relacao so
e considerada util quando sua retirada piora a metrica fora da amostra de forma
estavel. Devem ser repetidos testes em mesas e periodos diferentes, com correcao
para a quantidade de hipoteses examinadas.

## Criterio para promocao

O shadow mode nao deve ser promovido por um unico backtest. Sao necessarios:

1. ganho fora da amostra sobre uniforme e baselines simples;
2. log loss sem degradacao relevante;
3. exclusoes com vazamento baixo e intervalo de confianca aceitavel;
4. estabilidade em blocos temporais posteriores e mais de uma mesa;
5. periodo prospectivo shadow sem recalibracao retroativa;
6. revisao explicita antes de qualquer integracao com apostas.

Se esses criterios falharem, o resultado correto e manter abstencao ou concluir
que a evidencia historica nao sustenta previsibilidade.
