from helpers.utils.filters import get_terminal, is_consecutive
from helpers.utils.get_neighbords import get_neighbords

from helpers.classificador import ClassificadorProximidade


from typing import List, Dict, Any, Callable, Optional

# -------- filtros ----------
def filter_break_not_same_as_run_terminal(
    numbers: List[int],
    run: Dict[str, Any],
    get_terminal: Callable[[int], int],
    mode: str = "first"
) -> bool:
    if not run or "terminals" not in run or not run["terminals"]:
        return False
    break_term = get_terminal(numbers[0])
    seq_terms = run["terminals"]
    if mode == "any":
        return break_term not in seq_terms
    return break_term != seq_terms[0]


def filter_trigger_not_same_as_run_terminal(
    numbers: List[int],
    run: Dict[str, Any],
    get_terminal: Callable[[int], int],
    mode: str = "first"
) -> bool:
    if not run or "terminals" not in run or not run["terminals"]:
        return False

    trigger: Optional[int] = run.get("trigger")
    if trigger is None:
        end = run.get("end")
        if end is None or end + 1 >= len(numbers):
            return False
        trigger = numbers[end + 1]

    trig_term = get_terminal(trigger)
    seq_terms = run["terminals"]
    if mode == "any":
        return trig_term not in seq_terms
    return trig_term != seq_terms[0]


def filter_trigger_not_completes_run(
    numbers: List[int],
    run: Dict[str, Any],
    get_terminal: Callable[[int], int],
    **_   # <- aceita e ignora kwargs como mode="first"
) -> bool:
    terms = run.get("terminals")
    direction = run.get("direction")
    if not terms or direction not in ("up", "down"):
        return False

    trigger: Optional[int] = run.get("trigger")
    if trigger is None:
        end = run.get("end")
        if end is None or end + 1 >= len(numbers):
            return False
        trigger = numbers[end + 1]
    trig_term = get_terminal(trigger)

    if "next_terminal" in run:
        next_terminal = run["next_terminal"]
    else:
        t0 = terms[0]
        next_terminal = (t0 + 1) % 10 if direction == "down" else (t0 - 1) % 10

    return trig_term != next_terminal


def filter_break_not_completes_run(
    numbers,
    run,
    get_terminal,
    **_
) -> bool:
    """
    Aprova (True) se a QUEBRA (numbers[0]) NÃO completa/estende o run no lado oposto.
    Reprova (False) quando terminal(quebra) == terminal_apos_ultimo_no_mesmo_sentido do run.

    Ex.: numbers = [17, 15, 26, 23] (recente->antigo)
         run = 15(5) -> 26(6), direção 'up'
         último terminal = 6; próximo no mesmo sentido = 7
         quebra = 17 (terminal 7) => reprovar.
    """
    terms = run.get("terminals")
    direction = run.get("direction")
    if not terms or direction not in ("up", "down"):
        return False  # sem contexto suficiente

    break_term = get_terminal(numbers[0])
    last_term = terms[-1]

    # próximo terminal após o ÚLTIMO do run, seguindo a mesma direção do run
    if direction == "up":
        far_side_next = (last_term + 1) % 10
    else:  # "down"
        far_side_next = (last_term - 1) % 10

    # reprova se a quebra "completa" (i.e., estende) o run
    return break_term != far_side_next

def filter_no_backward_run_from_trigger(
    numbers: List[int],
    run: Dict[str, Any],
    get_terminal: Callable[[int], int],
    min_len: int = 2,
    wrap: bool = True,
    **_
) -> bool:
    """
    ✅ Aprova (True) se NÃO existir uma sequência de terminais contígua iniciando no gatilho.
    ❌ Reprova (False) se existir um run de terminais (↑ ou ↓) com comprimento >= min_len,
       começando exatamente em numbers[end+1] (gatilho) e seguindo para os mais antigos.

    Exemplo (recente -> antigo):
      numbers = [2, 15, 26, 30, 21, 12]
      run     = 15(5), 26(6)   => end = 2
      gatilho = numbers[3] = 30 (0)
      atrás   = 30(0), 21(1), 12(2)  => run de tamanho 3  ➜ deve reprovar
    """
    end = run.get("end")
    if end is None:
        return False  # sem contexto suficiente

    trig_idx = end + 1
    if trig_idx >= len(numbers) - 1:
        # não há pelo menos (gatilho, próximo) para iniciar run
        return True  # aprova por não haver sequência

    # Pré-calcular terminais a partir do gatilho até o fim da janela
    tail = numbers[trig_idx:]  # gatilho -> mais antigos
    terms = [get_terminal(x) for x in tail]

    def next_up(a: int, b: int) -> bool:
        return b == ((a + 1) % 10) if wrap else (b == a + 1)

    def next_down(a: int, b: int) -> bool:
        return b == ((a - 1) % 10) if wrap else (b == a - 1)

    # Determinar direção usando (gatilho -> próximo)
    if next_up(terms[0], terms[1]):
        direction = "up"
    elif next_down(terms[0], terms[1]):
        direction = "down"
    else:
        return True  # não inicia run atrás do gatilho => aprova

    # Estender run a partir do gatilho
    end_local = 1  # índice em 'tail' (terms) do fim do run (min 1 pois já temos 2 itens consecutivos)
    while end_local + 1 < len(terms):
        a, b = terms[end_local], terms[end_local + 1]
        if (direction == "up" and next_up(a, b)) or (direction == "down" and next_down(a, b)):
            end_local += 1
        else:
            break

    length = end_local + 1  # quantos itens no run iniciado no gatilho
    # ❌ Reprova se houver run com tamanho >= min_len
    return length < min_len
# -------- orquestrador ----------
def apply_filters(
    numbers: List[int],
    run: Dict[str, Any],
    get_terminal: Callable[[int], int],
    filters: List[Callable[..., bool]],
    **common_kwargs
) -> bool:
    """
    Executa todos os filtros e só aprova (True) se TODOS retornarem True.
    `common_kwargs` é repassado a cada filtro (útil p/ passar `mode="any"` etc).
    """
    for f in filters:
        if not f(numbers, run, get_terminal, **common_kwargs):
            return False
    return True


def roulette_eu_numbers_by_terminal(terminal: int, include_single_zero: bool = True) -> List[int]:
    """
    Retorna todos os números da roleta europeia (0–36) cujo terminal é `terminal` (0–9).
    - terminal=1  -> [1, 11, 21, 31]
    - terminal=6  -> [6, 16, 26, 36]
    - terminal=0  -> [0, 10, 20, 30]   (se include_single_zero=False, então [10, 20, 30])

    Parâmetros:
        terminal (int): dígito de 0 a 9.
        include_single_zero (bool): se False, remove o 0 quando terminal=0.

    Retorna:
        List[int]: lista ordenada de números.
    """
    if not isinstance(terminal, int) or not (0 <= terminal <= 9):
        raise ValueError("`terminal` deve ser um inteiro entre 0 e 9.")

    nums = [n for n in range(37) if n % 10 == terminal]
    if terminal == 0 and not include_single_zero:
        nums = [n for n in nums if n != 0]
    return nums


def find_terminal_run_after_break_bidir(
    nums: List[int],
    get_terminal: Callable[[int], int],
    min_len: int = 3,
    wrap: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Retorna a primeira sequência contígua de terminais consecutivos (↑ ou ↓),
    começando em nums[1], desde que nums[0] seja QUEBRA (não consecutivo de nums[1]).
    Direção (↑ ou ↓) é inferida entre nums[1] e nums[2] e mantida.
    - wrap=True considera 9->0 (↑) e 0->9 (↓).

    Ex.: nums = [12, 15, 26, 17, 28, 10]
         terms= [2, 5, 6, 7, 8, 0]
         -> retorna 15,26,17,28 (terminais 5,6,7,8) (↑)
    Suporta também runs decrescentes, ex.: terminais 8,7,6,5,...
    """
    n = len(nums)
    if n < 2:
        return None

    terms = [get_terminal(x) for x in nums]

    def next_up(a: int, b: int) -> bool:
        return b == ((a + 1) % 10) if wrap else (b == a + 1)

    def next_down(a: int, b: int) -> bool:
        return b == ((a - 1) % 10) if wrap else (b == a - 1)

    # 1) Validar QUEBRA no primeiro elemento:
    # se nums[0] -> nums[1] forem consecutivos (↑ ou ↓), não houve quebra.
    if next_up(terms[0], terms[1]) or next_down(terms[0], terms[1]):
        return None

    # 2) Determinar direção usando nums[1] -> nums[2]
    if n < 3:
        return None  # não dá pra formar sequência >=3

    direction = None
    if next_up(terms[1], terms[2]):
        direction = "up"
    elif next_down(terms[1], terms[2]):
        direction = "down"
    else:
        return None  # não iniciou run

    # 3) Estender a sequência contígua conforme a direção
    start = 1
    end = 2
    while end + 1 < n:
        a, b = terms[end], terms[end + 1]
        if direction == "up" and next_up(a, b):
            end += 1
        elif direction == "down" and next_down(a, b):
            end += 1
        else:
            break

    length = end - start + 1
    if length >= min_len:
        return {
            "values": nums[start:end + 1],
            "terminals": terms[start:end + 1],
            "start": start,
            "end": end,
            "length": length,
            "direction": direction
        }

    return None


# ---- wrapper: obter gatilho e next_terminal + números do terminal ----
def get_next_terminal_numbers(
    numbers: List[int],
    window: int = 10,
    min_len: int = 3,
    include_single_zero: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Considera numbers[0:window] (recente -> antigo).
    Se existir um run (↑ ou ↓) válido pós-quebra, retorna:
      - trigger: número logo após o fim do run (antes do início no tempo)
      - next_terminal: terminal que completaria o run do lado mais recente
      - next_terminal_numbers: todos os números 0–36 com esse terminal
      - + metadados do run (values, terminals, start, end, length, direction)
    """
    if len(numbers) < max(window, 3):
        return None

    slice_ = numbers[:window]
    res = find_terminal_run_after_break_bidir(slice_, get_terminal, min_len=min_len, wrap=False)
    if not res:
        return None

    start = res["start"]
    end = res["end"]
    direction = res["direction"]
    terminals = res["terminals"]

    # trigger: número imediatamente após o fim do run na janela
    if end + 1 >= len(slice_):
        return None
    trigger = slice_[end + 1]

    # next_terminal: o terminal que antecede o primeiro terminal do run (lado mais recente)
    t0 = terminals[0]
    if direction == "down":
        next_terminal = (t0 + 1) % 10   # ex.: 10,9,8 -> próximo seria 11 (1)
    else:  # "up"
        next_terminal = (t0 - 1) % 10   # ex.: 8,9,10 -> próximo seria 7

    next_terminal_numbers = roulette_eu_numbers_by_terminal(next_terminal, include_single_zero)

    return {
        "trigger": trigger,
        "next_terminal": next_terminal,
        "next_terminal_numbers": next_terminal_numbers,
        **res
    }


def process_roulette(roulette, numbers) : 

    if len(numbers) < 10 :
        return None
    
    res = get_next_terminal_numbers(numbers, window=10, min_len=2)

    

    if res:
        ok = apply_filters(
            numbers,
            res,
            get_terminal,
            filters=[
                filter_break_not_same_as_run_terminal,
                filter_trigger_not_same_as_run_terminal,
                filter_trigger_not_completes_run,
                filter_break_not_completes_run,   
                filter_no_backward_run_from_trigger  # quebra NÃO completa pelo lado oposto
            ],
            mode="any",  # será repassado aos filtros que aceitam `mode`
        )
        if ok:

            if(numbers[0] == 0) : 
                return None
            
            if get_terminal(numbers[0]) == get_terminal(numbers[res["end"] + 1]) :
                return None
            

            if is_consecutive(get_terminal(numbers[0]), get_terminal(numbers[res["trigger"]])) :
                return None

            classificador = ClassificadorProximidade()

            for number in numbers[:50]:
                classificador.adicionar_numero(number)

            ranking = classificador.get_ranking()[:10]


            numeros = [num for num, _ in ranking]

            # Interseção preservando ordem dos candidatos (se preferir ordem do ranking, inverta a lógica)
            matches = [n for n in res["next_terminal_numbers"] if n in numeros]

            if len(matches) < 0:
                # opcional: logar o motivo
                print(f"[FILTRO RANK] Reprovado: apenas {len(matches)} candidatos no ranking (mínimo = 3).")
                return None
            

            trigger_neighbords = get_neighbords(res["trigger"])

            if 0 in res["values"] :
                return None
            
            p0_terminal = get_terminal(numbers[0])
            trigger_terminal = get_terminal(res["trigger"])

            

            if(is_consecutive(p0_terminal, trigger_terminal)) :
                return None
            

            print(res)
            bet = res["next_terminal_numbers"];
      

            mirror_list = [m for n in bet for m in get_neighbords(n)]

            bet.extend(mirror_list)

            bet = sorted(set(bet));

            bet.insert(0,0)

            if(res["next_terminal"] == 0) :
                return None 

            return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "7NUMEROS IMEDIATO",
                "triggers":[res["trigger"]],
                "targets":[res["next_terminal"]],
                "bets": bet,
                "passed_spins" : 0,
                "spins_required" : 2,
                "spins_count": 0,
                "gales" : 10,
                "score" : 0,
                "snapshot":numbers[:10],
                "status":"waiting",
                "message" : "Gatilho encontrado!",
                "tags" : [],
            }
        else:
            return None
    else:
        return None

        
        


     


        
   
    
