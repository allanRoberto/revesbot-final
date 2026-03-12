from helpers.utils.filters import get_terminal, get_numbers_by_terminal
from helpers.utils.get_neighbords import get_neighbords
from helpers.classificador import ClassificadorProximidade



def process_roulette(roulette, numbers) :

    p2 = numbers[2]
    p3 = numbers[3]

    p0 = numbers[0]
    p1 = numbers[1]

    p4 = numbers[4]

    p2_terminal = get_terminal(p2)
    p3_terminal = get_terminal(p3)
    p4_terminal = get_terminal(p4)

    if p2_terminal == p3_terminal and not p3_terminal == p4_terminal :
        alvos = get_numbers_by_terminal(p3_terminal)

        vizinhos = [m for n in alvos for m in get_neighbords(n)]

        bet = [*alvos, *vizinhos]

        bet = sorted(set(bet))


        classificador = ClassificadorProximidade(peso_principal = 3.5,
            peso_vizinhos = 1.4,
            peso_vizinhos1 = 1.2,
            peso_duzia = 0.5,
            peso_cor = 0,
            peso_puxada = 2,
            qtd_puxada = 10,
            decaimento = 0.5)

        for number in numbers[:50]:
            classificador.adicionar_numero(number)

        ranking = classificador.get_ranking()[:25]


        numeros = [num for num, _ in ranking]

        # Interseção preservando ordem dos candidatos (se preferir ordem do ranking, inverta a lógica)
        bet_set = set(bet)
        matches = [n for n in numeros if n in bet_set]

        if len(matches) < 7:
            # opcional: logar o motivo
            print(f"[FILTRO RANK] Reprovado: apenas {len(matches)} candidatos no ranking (mínimo = 8).")
            return None


        if p0 in bet or p1 in bet :
            return None
        

        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "TERMINAILS",
                "triggers":[numbers[0]],
                "targets":[*alvos],
                "bets": [0, *matches[:6]],
                "passed_spins" : 0,
                "spins_required" : 2,
                "spins_count": 0,
                "gales" : 16,
                "score" : 0,
                "snapshot":numbers[:10],
                "status":"processing",
                "message" : "Gatilho encontrado!",
                "tags" : [],
            }
  