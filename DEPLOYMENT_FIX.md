# Deployment da Correção: Penalty Leve (0.75)

## Resumo da Mudança
- **Arquivo:** `apps/api/patterns/final_suggestion.py` (linhas 938-944)
- **Mudança:** `inversion_penalty_factor 0.3 → 0.75` para números não selecionados naturalmente
- **Impacto esperado:** Melhoria de ~10 posições em Cenário C (1.373 casos), ~0.5 pos geral

## Passos de Deployment

### 1. Verificar se o código está atualizado (AGORA)
```bash
ssh root@45.179.88.173
cd /path/to/revesbot-final
python3 _verify_server_fix.py
```

Esperado output:
```
✅ Código: ATUALIZADO
✅ Banco: ACESSÍVEL
```

### 2. Se o código NÃO estiver atualizado:

#### Opção A: Git pull (mais seguro)
```bash
cd /path/to/revesbot-final
git pull origin main
# ou
git checkout apps/api/patterns/final_suggestion.py
```

#### Opção B: Copiar arquivo manualmente
Copie o arquivo `apps/api/patterns/final_suggestion.py` do repositório local para o servidor:
```bash
scp apps/api/patterns/final_suggestion.py root@45.179.88.173:/path/to/revesbot-final/apps/api/patterns/
```

### 3. Reiniciar o serviço
```bash
pm2 restart all
# ou se for docker:
docker-compose restart
# ou se for systemd:
systemctl restart seu_servico
```

### 4. Verificar que está rodando
```bash
python3 _verify_server_fix.py
```

Esperar ~2-5 min para novos snapshots serem gerados.

## Validação

### Curto prazo (24h):
- Verificar que novos snapshots estão sendo gerados
- Observar se `invertedInFinal` tem valores menores (~2-4 vs 3-6 antes)

### Médio prazo (1-2 dias):
Rodar a validação completa nos 18k novos snapshots:
```bash
python3 _validate_inversion_hypothesis.py
```

Esperado:
- Cenário C (penalizado): média ~24 (vs 34.15 antes)
- Cenário A (não penalizado): média ~14 (sem mudança)
- Geral com inverted: ~16.8 (vs 18.57 antes)

## Rollback (se necessário)

Se o impacto for pior que esperado, reverter:
```bash
git checkout apps/api/patterns/final_suggestion.py
pm2 restart all
```

## Métricas a monitorar

- **invertedInFinal count:** Deve permanecer similar (~3-6 por snapshot)
- **Posições de Cenário C:** Deve cair ~10 posições em média
- **Taxa de acerto geral:** Não deve piorar (esperado: melhore ~0.5 pos)

## Questões?

Abra um issue ou revise `/apps/api/patterns/final_suggestion.py` linhas 938-944

---
Data: 2026-05-07
Status: Ready for deployment
