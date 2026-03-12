from helpers.utils.get_figure import get_figure
from helpers.utils.get_mirror import get_mirror
from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.filters import soma_digitos, first_index_after
from collections import Counter

def buscar_sequencia(numbers, num1, num2):
    for i in range(5, len(numbers) - 1):
        if numbers[i:i+2] == [num1, num2] or numbers[i:i+2] == [num2, num1]:
            return i
    return None

def process_roulette(roulette, numbers, num_ocorrencias=3, nums_para_tras=40, nums_apos_ocorrencia=3, 
                    aplicar_decaimento=True, peso_vizinhos=0.9):
        """
        num_ocorrencias: número de ocorrências do número a buscar (padrão: 2)
        nums_para_tras: quantos números analisar para trás do gatilho 5 (padrão: 12)
        nums_apos_ocorrencia: quantos números pegar após cada ocorrência (padrão: 2)
        aplicar_decaimento: se True, zera o score quando o número aparece (padrão: True)
        peso_vizinhos: peso aplicado ao score dos vizinhos (0 a 1, padrão: 0.5)
        """
        if(len(numbers) < 10):
            return None
        
        p0 = numbers[0]
        p1 = numbers[1]

        contador = Counter(numbers)


        frequentes = [num for num, qtd in contador.most_common(10)]

    
        # Verificar se temos números suficientes antes do 5
        if len(numbers) < nums_para_tras + 1:  # Precisamos de pelo menos N números antes
            return None
            
        # Dicionário para contar scores dos números (usando float agora por causa dos pesos)
        score_counter = Counter()
        
        # Lista para rastrear números que já apareceram (decaimento)
        numeros_pagos = set()
        
        # Para cada um dos N números anteriores ao 5
        for idx in range(1, nums_para_tras + 1):
            # Verificar se o índice está dentro do range
            if idx >= len(numbers):
                break
                
            trigger = numbers[idx]
            
            if trigger == 0:
                continue
            
            # Lista para armazenar os índices das ocorrências
            ocorrencias = []
            last_index = idx
            
            # Buscar as N ocorrências do número
            for _ in range(num_ocorrencias):
                next_index = first_index_after(numbers, trigger, last_index + 1)
                if next_index is None:
                    break
                ocorrencias.append(next_index)
                last_index = next_index
            
            # Se não encontrou todas as ocorrências necessárias, pular
            if len(ocorrencias) < num_ocorrencias:
                continue
            
            # Pegar os N números após cada ocorrência
            for occ_idx in ocorrencias:
                # Verificar se temos números suficientes após a ocorrência
                if occ_idx + nums_apos_ocorrencia >= len(numbers):
                    continue
                    
                # Pegar os N números após esta ocorrência
                for i in range(1, nums_apos_ocorrencia + 1):
                    if occ_idx + i < len(numbers):
                        num = numbers[occ_idx + i]
                        if num is not None:
                            # Adicionar score completo ao número principal
                            score_counter[num] += 1
                            
                            # Adicionar score reduzido aos vizinhos
                            if peso_vizinhos > 0:
                                vizinhos = get_neighbords(num)
                                for vizinho in vizinhos:
                                    if vizinho is not None:
                                        score_counter[vizinho] += peso_vizinhos
                
                # Aplicar decaimento: o número que apareceu na ocorrência foi "pago"
                if aplicar_decaimento and occ_idx < len(numbers):
                    numero_pago = numbers[occ_idx]
                    numeros_pagos.add(numero_pago)
            
            # Também adicionar os números após o trigger original
            for i in range(1, nums_apos_ocorrencia + 1):
                if idx + i < len(numbers):
                    num = numbers[idx + i]
                    if num is not None:
                        # Adicionar score completo ao número principal
                        score_counter[num] += 1
                        
                        # Adicionar score reduzido aos vizinhos
                        if peso_vizinhos > 0:
                            vizinhos = get_neighbords(num)
                            for vizinho in vizinhos:
                                if vizinho is not None:
                                    score_counter[vizinho] += peso_vizinhos
            
            # Aplicar decaimento: o trigger original também foi "pago"
            if aplicar_decaimento:
                numeros_pagos.add(trigger)
        
        # Aplicar decaimento: zerar scores dos números que foram "pagos"
        if aplicar_decaimento:
            for num_pago in numeros_pagos:
                if num_pago in score_counter:
                    score_counter[num_pago] -= 0 
                    vizinhos = get_neighbords(num_pago)
                    for vizinho in vizinhos:
                        if vizinho is not None:
                            score_counter[vizinho] -= 0.6
        
        # Remover números com score zero ou negativo antes de pegar os top 5
        score_counter = Counter({k: v for k, v in score_counter.items() if v > 0})
        
        # Se não encontrou nenhum número com score positivo
        if not score_counter:
            return None
            
        # Pegar os 5 melhores números por score
        top_5 = [(num, count) for num, count in score_counter.most_common(5)]

        nums = [num for num, count in top_5]
        count = [count for num, count in top_5]

        # Calculando tudo de uma vez
        soma = sum(count)
        media = soma / len(count)


            
        if p0 > 0:

        
            # Adicionar espelhos dos 5 melhores
            bet = nums.copy()

            vizinhos_list = [m for n in bet for m in get_neighbords(n)] 

            #bet.extend(vizinhos_list)

            figure_list = [m for n in bet for m in get_figure(soma_digitos(n))]
            vizinho_list = [m for n in bet for m in get_neighbords((n))]

            # Remove todos os números de nums da figure_list
            figure_list_filtrada = [item for item in figure_list if item not in nums]

            #bet.extend(mirror_list)

            numeros_puxados = []

            for num in nums :
                idx = first_index_after(numbers, num, i+1)
                if idx is None :
                    break

                numeros_puxados.extend(numbers[idx - 2 : idx])
                numeros_puxados.extend(numbers[idx + 2 : idx])
            
            # Remover duplicatas e ordenar
            bet = sorted(set(bet))

            if sum(1 for num in numeros_puxados if num in numbers[1:20]) >= len(numeros_puxados) * 0.8:
            
                return {
                    "roulette_id": roulette['slug'],
                    "roulette_name": roulette["name"],
                    "roulette_url": roulette["url"],
                    "pattern": f"TRIANGULACAO-SUPREMA",
                    "triggers": [numbers[0]],
                    "targets": [*bet],
                    "bets": bet,
                    "passed_spins": 0,
                    "spins_required": 0,
                    "spins_count": 0,
                    "snapshot": numbers,
                    "status": "processing",
                    "message": f"Gatilho ativado!",
                    "tags": [],  # Adicionando as tags coletadas
                }