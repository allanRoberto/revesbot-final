# Estrutura do Monorepo

## Objetivo

Preparar o repositório para uma arquitetura híbrida, com aplicações Python e
JavaScript isoladas, sem reescrever a lógica existente.

## Estrutura atual consolidada

```text
revesbot-final/
  apps/
    api/
    auth_api/
    bot_automatico/
    collector/
    monitoring/
      scripts/
      src/        # legado interno mantido por compatibilidade
    signals/
  shared/
    python/
    javascript/
  infra/
    pm2/
    nginx/
    deploy/
  docs/
  src/            # wrappers legados
```

## Decisões desta etapa

- `apps/` é o ponto principal para aplicações executáveis.
- `shared/` é o destino de código compartilhado por linguagem.
- `infra/` concentra deploy e operação.
- `src/` no root foi reduzido a compatibilidade temporária.
- `apps/monitoring/src` permanece como legado interno nesta etapa para evitar
  quebra de imports e entrypoints.
- Os entrypoints de `apps/monitoring` foram estabilizados para execução tanto do
  diretório do app quanto do root do repositório.

## Próximas etapas sugeridas

- extrair duplicações Python reais para `shared/python/`;
- reduzir `sys.path` shims;
- substituir `apps/monitoring/src` por um pacote interno com nome estável;
- padronizar execução e ambiente por app;
- separar deploy por ambiente (`staging` e `production`).
