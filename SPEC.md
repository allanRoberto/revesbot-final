# SPEC.md Sistema de predição de sinais para a Roleta européia

## 1. Objetivo

Construir um sistema em **Python** que:
1. Consuma spins (números) por **roleta** (`roulette_id`) publicados via **Redis** (originados do MongoDB).

2. Execute múltiplos **padrões** (plugins) que geram **predições** (candidatos) com a configuração de tentativas`attempts` (tentativas).

3. Una as sugestões em um **ranking de números únicos**, com **score** e **confiança**.

4. Mantenha o ciclo de vida completo de cada predição em 5 estados:
   - `waiting`, `processing`, `win`, `lost`, `cancelled`

5. Registre:
   - Em qual **tentativa** a predição bateu (`hit_attempt`) e em qual `seq/ts`.
   - Se foi `lost` ou `cancelled`, por quê e quando. 
   

6. Após resolução (`win/lost/cancelled`), execute uma janela de auditoria de mais **M spins** (default 10) para registrar:
   - Quantas vezes a predição bateria após resolver.
   - Em quais spins (`seq/ts`) bateu.

7. Disponibilize um **Backtester** e um **Otimizador** que reprocessam históricos do Mongo sem esperar spins ao vivo, usando o **mesmo pipeline** do online.



## 2 Estrutura de programação 

### Formação dos padrões:  src/signals

    - Todo padrão serve para todas as roleta, os padrões são processados em todas as roletas da lista *roulette_list* o padrão recebe 3 parametros que são : (roulette) que armazena os dados de cada roleta, e (numbers) que é o histórico dos últimos 500 números daquela roleta em questão, ele processa o padrão e retorna o sinal, caso naquele giro não tenha formado o sinal ele retorna None. 

    - Os padrões precisam ter a função process_roulette(roulette, numbers) para que sejam processados de uma só vez no arquivo run_all_patterns.py. Esse arquivo recebe os últimos números e transmite para todos os padrões de uma só vez. Aguarda a resposta de cada um e salve o sinal num canal do redis. 

    Os principais arquivos desse diretório são :
        - main.py
        - patterns/*
        - patterns/run_all_patterns.py
        -simulate.py

    
    O arquivo main.py é o orquestador que recebe os números que podem ser oriundos de uma simulação ou em tempo real. 

    O arquivo run_all_patterns.py reune todos os padrões e recebe os números, distribui de uma só vez os números para todos os padrões cadastrados e recebe os sinais dos padrões que possuem sinais para enviar. 

    O arquivo simulate.py faz a simulação dos números, ele faz uma consulta inicial na api e inverte a lista, publica um por um em outro canal, o new_result_simulate. 

### Execução do Sinal : src/monitoring

    - Nesse módulo monitoramos o sinal gerado no canal do Redis, ficamos ouvindo as mensagens e quando um sinal chega e realizamos seu processamento (processor_monitoring.py), o processamento fica responsável por gerenciar o status, processar spins e monitorar o sinal pós finalizado. 

    - Para iniciar o monitoramento eu utilizo o comando no terminal : python -m src.signal_listener. Quando quero resetar os sinais cadastrados eu uso o clear_signals.py

    - Cada sinal é processado em uma task separada para não interromper o processamento dos outros padrões concorrentes. 


### Banco de dados

    - Os resultados de cada roleta são coletados diretamente do websocket da provedora e cadastrado no banco de daodos mongoDB e em seguida esse resultado é transmitido no canal do Redis o new_result, esse canal serve para que outras aplicações ouçam os novos números sem a necessidade de consultar o banco de dados. 

    - A estrutura de dados é para cadastrar um número é: 
                "roulette_id": str,
                "roulette_name" : str,
                "value": int,
                "timestamp": Date
    
    
