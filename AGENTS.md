Analise este repositório e reorganize-o de forma incremental, sem quebrar o funcionamento atual, preparando a base para uma arquitetura mais escalável no futuro.

Contexto do projeto:

O projeto se chama revesbot-final e atualmente está organizado assim:

revesbot-final/
    src/
        bot-automatico/
            api/
        signals/
        monitoring/
        collector/

Significado de cada módulo:

1. src/bot-automatico/
   - aplicação em JavaScript
   - responsável por executar apostas automáticas na roleta

2. src/bot-automatico/api/
   - aplicação em JavaScript
   - responsável pela autenticação/login na casa de apostas
   - gerencia sessão, cookies, tokens ou equivalente

3. src/signals/
   - aplicação em Python
   - responsável por analisar resultados e formar sinais/padrões

4. src/monitoring/
   - aplicação em Python
   - responsável por monitorar sinais, gatilhos e processamento relacionado

5. src/collector/
   - aplicação em Python
   - responsável por coletar dados dos jogos
   - conecta em websocket das mesas
   - escuta resultados
   - salva no banco
   - publica eventos no Redis

Importante:
- bot-automatico e bot-automatico/api são JavaScript
- signals, monitoring e collector são Python
- não converta linguagens
- preserve a stack atual de cada módulo

Objetivo desta etapa:

Quero começar organizando o repositório sem fazer uma refatoração destrutiva.
A ideia é melhorar a estrutura, clareza e separação de responsabilidades, preparando o projeto para uma arquitetura mais avançada depois.

Sua tarefa nesta etapa é:

1. Analisar a estrutura atual do projeto.
2. Propor uma nova organização mantendo compatibilidade com o código existente.
3. Reorganizar o repositório sem alterar desnecessariamente a lógica já implementada.
4. Separar claramente aplicações Python e JavaScript.
5. Criar uma base de monorepo híbrido, mantendo cada aplicação isolada.
6. Preparar o repositório para deploy e manutenção mais fáceis.

Estrutura alvo desejada:

revesbot-final/
  apps/
    bot_automatico/           # JavaScript
    auth_api/                 # JavaScript
    signals/                  # Python
    monitoring/               # Python
    collector/                # Python

  shared/
    python/
      config/
      db/
      redis/
      models/
      roulette/
      utils/

    javascript/
      config/
      services/
      utils/

  infra/
    pm2/
    nginx/
    deploy/

  docs/

Observações sobre a estrutura alvo:

- src/bot-automatico deve ir para apps/bot_automatico
- src/bot-automatico/api deve virar apps/auth_api
- src/signals deve ir para apps/signals
- src/monitoring deve ir para apps/monitoring
- src/collector deve ir para apps/collector

Regras importantes:

1. Não quebrar o funcionamento atual.
2. Não reescrever a lógica inteira se não for necessário.
3. Mover apenas o que fizer sentido nesta primeira etapa.
4. Ajustar imports Python e JavaScript conforme necessário.
5. Criar arquivos __init__.py onde necessário nos módulos Python.
6. Manter a possibilidade de rodar cada aplicação individualmente.
7. Manter dependências separadas por aplicação sempre que fizer sentido.
8. Não tentar unificar Python e JavaScript à força.
9. Preservar nomes, fluxos e responsabilidade dos módulos.
10. Não remover arquivos sem explicar antes.

O que quero que você faça primeiro:

1. Analise todo o projeto.
2. Identifique:
   - quais arquivos pertencem a cada aplicação
   - quais módulos/utilitários são compartilháveis
   - quais imports vão quebrar com a mudança
   - quais pontos exigem cuidado por causa da diferença entre Python e JavaScript

3. Antes de aplicar qualquer mudança, me mostre:
   - plano de reorganização
   - estrutura atual resumida
   - estrutura nova proposta
   - lista de arquivos/pastas que serão movidos
   - lista de possíveis ajustes de imports
   - riscos de quebra

4. Só depois disso, aplique a reorganização.

Depois que você terminar essa primeira etapa, também quero que o projeto fique preparado para uma segunda etapa futura com:
- arquitetura orientada a eventos
- melhor separação entre apps e código compartilhado
- padronização de execução com PM2
- deploy por ambiente
- staging e produção

Mas nesta primeira etapa foque em:
- organização real do repositório
- mínimo de ruptura
- compatibilidade com o código existente

Entrega esperada nesta etapa:
- repositório reorganizado
- imports ajustados
- base inicial de apps/, shared/ e infra/
- sem quebrar aplicações existentes
- com explicação clara do que foi alterado

Importante: faça uma reorganização conservadora. Prefira mover e ajustar imports em vez de reescrever lógica interna. Preserve ao máximo os entrypoints atuais de cada aplicação.

## Regra de segurança

Antes de modificar arquivos:
- sempre mostrar plano de refatoração
- listar arquivos que serão movidos
- listar imports que serão alterados
- esperar confirmação

## Stack

Python:
- FastAPI
- Redis
- WebSocket
- workers

JavaScript:
- Node.js
- automação de apostas

Infra:
- Redis
- PM2
- Nginx