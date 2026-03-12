from helpers.utils.get_neighbords import get_neighbords
from helpers.classificador import ClassificadorProximidade


def process_roulette(roulette, numbers) :

    print(roulette["name"])

    if len(numbers) < 40 :
        return None

    p0 = numbers[0]

    target = numbers[p0]

    classificador = ClassificadorProximidade()

    for number in numbers[:40]:
        classificador.adicionar_numero(number)

    ranking = classificador.get_ranking()[:1]


    print(ranking)
    numeros = [ranking[0][0]]
    score = int(ranking[0][1])


    if not target in numeros :
        print("recusado")
        return None

    target_neighbords3 = get_neighbords(target, 3)
    target_neighbords2 = get_neighbords(target, 2)
    target_neighbords1 = get_neighbords(target, 1)

    bet = [*target_neighbords3, *target_neighbords2, *target_neighbords1, target, 0]

    bet = sorted(set(bet))
    tags = []
    if numbers[0] in bet :
        tags.append("gatilho_na_aposta")

    return {
          "roulette_id": roulette['slug'],
          "roulette_name" : roulette["name"],
          "roulette_url" : roulette["url"],
          "pattern" : "7NUMEROS IMEDIATO",
          "triggers":[numbers[0]],
          "targets":[target],
          "bets":[*target_neighbords3, *target_neighbords2, *target_neighbords1, target, 0],
          "passed_spins" : 0,
          "spins_required" : 0,
          "spins_count": 0,
          "gales" : 8,
          "score" : score,
          "snapshot":numbers[:p0 + 4],
          "status":"processing",
          "message" : "Gatilho encontrado!",
          "tags" : tags,
     }

    return None