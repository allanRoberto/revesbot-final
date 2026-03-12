from helpers.utils.filters import (
    first_index_after,
    is_consecutive,
    any_consecutive,
    has_same_terminal,
    is_repetition,
    is_check_neigbor_two_numbers,
    appears_in_slice,
)

def process_roulette(roulette, numbers) :
    idxs = (0, 1, 2)
    p0, p1, p2 = [numbers[i] for i in idxs] # p1 : Gatilho | p0 : Alvo

     # 1 ) Procura outra ocorrência do número que não seja igual ao número após ele e com uma distância de 12 números. 
    second_p1 = first_index_after(numbers, p1, start=13)

     # 2 ) Verifica se encontrou a segunda ocorrência do gatilho
    if second_p1 is None:
        print(f"001 - [{roulette['name']}] - [{roulette['slug']}] {p1} não aparece novamente nas últimas 200 posições apartir da primeira ocorrência")
        return None
    
    if(numbers[second_p1 - 1] == p0) : 
        print(f"002 - [{roulette['name']}] - [{roulette['slug']}] O número atrás de p1 ({p1}) é igual ao número atrás da segunda ocorrência de p1")
        return None

    pos2 = second_p1

    print(f"https://gamblingcounting.com/{roulette['slug']}")

    print(p0, p1)
    print(numbers[second_p1 - 1], p1)
    
    while True:
        pos3 = first_index_after(numbers, p1, pos2 + 1)  # Garante avanço

        if pos3 is None:
            print(f"005 - [{roulette['name']}] - [{roulette['slug']}] Não há mais ocorrências de {p1} após posição {pos2}")
            return None

        if (pos3 - pos2) < 12:
            pos2 = pos3  # Pula ocorrência muito próxima
        else:
            break  # Encontrou uma ocorrência válida 


    return None