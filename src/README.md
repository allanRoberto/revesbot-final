# Compatibilidade Legada

O diretório `src/` foi mantido apenas como camada temporária de compatibilidade.

Os scripts ativos foram movidos para:

- `apps/monitoring/scripts/monitor_bot.py`
- `apps/monitoring/scripts/monitor_bot_integrado.py`

Os arquivos em `src/` agora funcionam como wrappers para não quebrar rotinas
externas que ainda executem os caminhos antigos.
