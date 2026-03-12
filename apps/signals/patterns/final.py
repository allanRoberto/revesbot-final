from helpers.classificador import ClassificadorProximidade

# variável global para lembrar último ranking
ultimo_ranking = None  

from typing import Callable, List, Tuple



FILTER_SWITCHES = {
    "ranking": True,
}

Filter = Tuple[str, str, Callable[[], bool], str]

debug = True


def run_filters(filters: List[Filter], debug: bool = False) -> Tuple[bool, List[str]]:
    """Retorna *True* se algum filtro bloquear e lista de todas as tags identificadas."""
    tags_identificadas = []
    
    for categoria, descricao, cond, tag in filters:
        if not FILTER_SWITCHES.get(categoria, True):
            continue  # grupo desligado
        try:
            if cond():
                tags_identificadas.append(tag)
                if debug:
                    print(f"[{categoria.upper()}] {descricao} - TAG: {tag}")
                # Por enquanto não bloqueia, apenas coleta tags
        except Exception as e:
            if debug:
                print(f"[ERRO] {categoria} — {descricao}: {e}")
    
    return False, tags_identificadas  # Nunca bloqueia por enquanto, apenas retorna as tags

def process_roulette(roulette, numbers):

    if len(numbers) < 200:
        return None

    classificador = ClassificadorProximidade()

    for number in numbers:
        classificador.adicionar_numero(number)

    ranking = classificador.get_ranking()[:5]

    # Extrai apenas os scores
    scores = [score for _, score in ranking]
    soma = sum(scores)
    media = soma / len(scores) if scores else 0
    diferenca_1_2 = abs(scores[0] - scores[1]) if len(scores) > 1 else 0
    minimo = min(scores) if scores else 0


    filters: List[Filter] = []

    if FILTER_SWITCHES["ranking"]:
            filters += [
               ("ranking", "score maior que 50", lambda: soma > 50, "soma_maior_50"),
               ("ranking", "score maior que 60", lambda: soma > 60, "soma_maior_60"),
               ("ranking", "score maior que 70", lambda: soma > 70, "soma_maior_70"),
               ("ranking", "score maior que 80", lambda: soma > 80, "soma_maior_80"),
               ("ranking", "score maior que 90", lambda: soma > 90, "soma_maior_90"),
               ("ranking", "score maior que 100", lambda: soma > 100, "soma_maior_100"),
               ("ranking", "score maior que 110", lambda: soma > 110, "soma_maior_110"),
               ("ranking", "score maior que 120", lambda: soma > 120, "soma_maior_120"),
               ("ranking", "score maior que 130", lambda: soma > 130, "soma_maior_130"),
               ("ranking", "score maior que 140", lambda: soma > 140, "soma_maior_140"),
               ("ranking", "score maior que 150", lambda: soma > 150, "soma_maior_150"),
               ("ranking", "score maior que 160", lambda: soma > 160, "soma_maior_160"),
               ("ranking", "score maior que 160", lambda: media > 0, f"media_{media}"),
               ("ranking", "score maior que 160", lambda: diferenca_1_2 > 0, f"diferenca_{diferenca_1_2}"),
               ("ranking", "score maior que 160", lambda: minimo > 0, f"minimo_{minimo}"),

            ]

    bloqueado, tags = run_filters(filters, debug)

    ranking = classificador.get_ranking()[:18]


    bet = [num for num, _ in ranking]

    print(soma)

    if soma > 120 and media > 16 :

        return {
            "roulette_id": roulette['slug'],
            "roulette_name": roulette["name"],
            "roulette_url": roulette["url"],
            "pattern": "FINAL",
            "triggers": [numbers[0]],
            "targets": [*bet],
            "bets": [*bet],
            "passed_spins": 0,
            "spins_required": 0,
            "spins_count": 0,
            "snapshot": numbers[:50],
            "gales" : 8,
            "status": "processing",
            "message": "Gatilho encontrado!",
            "tags": tags,
        }
    
    return None

