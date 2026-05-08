# Análise de 3.000 Sugestões de Roleta

## Descrição
Este documento apresenta uma análise completa de 3.000 sugestões das roletas **pragmatic-auto-roulette** e **pragmatic-brazilian-roulette**, correlacionando as sugestões com os resultados reais (números que saíram).

## Dados Coletados
- **Total de sugestões analisadas**: 3.000 por roleta
- **Período**: Sugestões dos últimos snapshots registrados
- **Correlação**: Cada sugestão é correlacionada com o próximo número que saiu após sua criação

## Estrutura dos Dados

Cada sugestão analisada contém:
- `snapshot_id`: ID único da sugestão
- `roulette_id`: Identificador da roleta
- `anchor_number`: Número que serviu como âncora para a sugestão
- `anchor_timestamp_utc`: Timestamp da sugestão
- `next_number`: Número que efetivamente saiu
- `next_timestamp_utc`: Timestamp do resultado
- `hit_rank`: **POSIÇÃO NO RANKING ONDE A SUGESTÃO BATEU** (1 = primeira sugestão, 2 = segunda, etc.)
- `ranking_full`: Lista completa do ranking sugerido
- `ranking_size`: Quantidade de números no ranking

## Métricas Principais

### Hit Rank
O "hit_rank" é a métrica central desta análise:
- **Rank 1**: Sugestão acertou na primeira posição do ranking
- **Rank 2-5**: Sugestão estava entre os top 5
- **Rank 6-10**: Sugestão estava entre os top 10
- **Rank 11-20**: Sugestão estava entre os top 20
- E assim por diante...

### Estatísticas de Desempenho
- **Média de Ranking**: Posição média em que o número saiu
- **Mediana de Ranking**: Posição mediana
- **Taxa Top 5**: Percentual de acertos nos top 5
- **Taxa Top 10**: Percentual de acertos nos top 10
- **Taxa Top 20**: Percentual de acertos nos top 20

## Arquivos Gerados

1. **suggestion_hits_3000_analysis.json**
   - Arquivo principal com todos os dados e análises
   - Contém: resumo, análise por roleta, análise geral e lista completa de items

2. **suggestion_ranking_detailed_report.txt**
   - Relatório formatado com as principais métricas
   - Execução: `python analyze_ranking_detailed.py`

3. **suggestion_ranking_distribution_visualization.txt**
   - Visualização gráfica da distribuição de rankings
   - Execução: `python visualize_ranking_distribution.py`

## Como Usar

### Gerar análise:
```bash
python fetch_3000_suggestions_analysis.py
```

### Visualizar relatório detalhado:
```bash
python analyze_ranking_detailed.py
```

### Visualizar distribuição:
```bash
python visualize_ranking_distribution.py
```

## Interpretação dos Resultados

- **Distribuição uniforme** nos rankings: Sugestões têm igual probabilidade em qualquer posição
- **Distribuição concentrada nos top rankings**: Sugestões são boas preditores
- **Distribuição concentrada nos últimos rankings**: Sugestões podem estar incorretas

## Próximos Passos

1. Analisar a distribuição dos rankings
2. Comparar performance entre as duas roletas
3. Avaliar se há padrões por hora, dia ou configuração
4. Otimizar o algoritmo de sugestão baseado nos insights
