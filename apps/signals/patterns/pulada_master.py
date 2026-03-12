from helpers.utils.filters import is_skipped_sequence, get_neighbords, get_numbers_by_terminal, get_terminal

def process_roulette(roulette, numbers) :

    if len(numbers) < 100 :
        return None
    
    base_target = numbers[3]
    check_1 = numbers[4]
    check_2 = numbers[5]

    if is_skipped_sequence(check_1, check_2) :
        if check_1 < check_2 :
            trigger = check_1 + 1
        else :
            trigger = check_1 - 1

        terminal = get_terminal(base_target)

        targets =  get_numbers_by_terminal(terminal);

        bet = [];

        neighbords_list = [m for n in targets for m in get_neighbords(n)]

        bet.extend(neighbords_list)
        bet.extend(targets)


        check_paid = any(item in [numbers[0], numbers[1], numbers[2]] for item in bet)

        if check_paid :
            return None

        bet.insert(0,0)


        return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "PULADA",
            "triggers":trigger,
            "targets":[base_target],
            "bets": bet,
            "passed_spins" : 0,
            "spins_required" : 2,
            "spins_count": 0,
            "gales" : 3,
            "score" : 0,
            "snapshot":numbers[:200],
            "status": "processing",
            "message" : "Gatilho encontrado!",
            "tags" : [],
        }