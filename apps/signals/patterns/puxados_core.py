from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from collections import Counter, defaultdict
import json
import os
import redis
import urllib.request


# Roda europeia (ordem do racetrack)
EU_WHEEL = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
    5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
]
WHEEL_INDEX = {n: i for i, n in enumerate(EU_WHEEL)}


def parse_numbers(text: str) -> List[int]:
    """
    Extrai inteiros de um texto (um por linha ou separados por espaços).
    """
    nums: List[int] = []
    for raw in text.replace(",", " ").split():
        raw = raw.strip()
        if raw == "":
            continue
        nums.append(int(raw))
    return nums


def to_chronological(nums_top_is_most_recent: List[int]) -> List[int]:
    """
    Seu padrão: mais recente está no topo.
    Para varrer 'após X', precisamos do mais antigo -> mais recente.
    """
    return list(reversed(nums_top_is_most_recent))


def racetrack_neighbors(n: int, k: int = 2) -> Dict[int, List[int]]:
    """
    Retorna vizinhos no racetrack por distância.
    Ex.: k=2 -> {1: [vizinho_esq, vizinho_dir], 2: [dois_esq, dois_dir]}
    """
    if n not in WHEEL_INDEX:
        raise ValueError(f"Número {n} não existe na roda europeia.")
    i = WHEEL_INDEX[n]
    L = len(EU_WHEEL)
    out: Dict[int, List[int]] = {}
    for d in range(1, k + 1):
        out[d] = [EU_WHEEL[(i - d) % L], EU_WHEEL[(i + d) % L]]
    return out


@dataclass
class OccurrenceWindow:
    occ_id: int
    idx: int  # índice do 27 no vetor cronológico
    after: List[int]  # números após o alvo (até window)


@dataclass
class PullReport:
    target: int
    window: int
    occurrences: List[OccurrenceWindow]
    plus1_counts: Counter
    window_counts: Counter
    terminal_counts: Counter
    neighbor_hits_by_distance: Dict[int, int]
    neighbor_set_all: set
    neighbors_by_distance: Dict[int, List[int]]


@dataclass
class SimulationResult:
    total_predictions: int
    wins: int
    losses: int
    win_rate: float
    total_hits: int


def analyze_target_pull(nums_top_is_recent: List[int], target: int, window: int = 3) -> PullReport:
    """
    Fiel ao que fiz hoje:
    - reverte a lista (porque o topo é o mais recente)
    - acha cada ocorrência do target
    - captura até 3 números depois
    - consolida +1 e janela (+1/+2/+3)
    - mede vizinhos (±1 e ±2) dentro da janela
    - conta terminais dentro da janela
    """
    seq = to_chronological(nums_top_is_recent)

    occurrences: List[OccurrenceWindow] = []
    for i, n in enumerate(seq):
        if n == target:
            after = seq[i + 1:i + 1 + window]
            occurrences.append(OccurrenceWindow(len(occurrences) + 1, i, after))

    # Contagem do +1
    plus1 = Counter()
    for occ in occurrences:
        if len(occ.after) >= 1:
            plus1[occ.after[0]] += 1

    # Contagem total na janela (+1/+2/+3)
    win = Counter()
    terminals = Counter()
    for occ in occurrences:
        for x in occ.after:
            win[x] += 1
            terminals[x % 10] += 1

    # Vizinhança do target (racetrack)
    neigh = racetrack_neighbors(target, k=2)  # dist 1 e 2
    neigh_all = set(neigh[1] + neigh[2])

    hits_by_d = {1: 0, 2: 0}
    # Conta quantas vezes vizinhos aparecem na janela (qualquer posição dentro da janela)
    for occ in occurrences:
        for x in occ.after:
            if x in neigh[1]:
                hits_by_d[1] += 1
            if x in neigh[2]:
                hits_by_d[2] += 1

    return PullReport(
        target=target,
        window=window,
        occurrences=occurrences,
        plus1_counts=plus1,
        window_counts=win,
        terminal_counts=terminals,
        neighbor_hits_by_distance=hits_by_d,
        neighbor_set_all=neigh_all,
        neighbors_by_distance=neigh
    )


def format_report(rep: PullReport) -> str:
    """
    Imprime no estilo do relatório que eu fiz hoje:
    1) Varredura ocorrência por ocorrência (O1: 27 -> a -> b -> c)
    2) Consolidado +1
    3) Consolidado janela (+1/+2/+3)
    4) Vizinhança do racetrack e contagem na janela
    5) Terminais na janela
    """
    lines: List[str] = []
    lines.append(f"ALVO: {rep.target} | Janela: +1..+{rep.window}")
    lines.append(f"Ocorrências encontradas: {len(rep.occurrences)}")
    lines.append("")
    lines.append("1) Varredura ocorrência por ocorrência (alvo -> +1 / +2 / +3)")
    for occ in rep.occurrences:
        chain = " -> ".join([str(rep.target)] + [str(x) for x in occ.after])
        # Se não tiver 3 depois, fica menor (igual eu marquei no O19)
        lines.append(f"O{occ.occ_id}: {chain}")
    lines.append("")

    # +1 mais repetidos
    lines.append("2) Puxada direta (+1 após o alvo)")
    if len(rep.plus1_counts) == 0:
        lines.append("Nenhuma ocorrência com +1 disponível.")
    else:
        top_plus1 = rep.plus1_counts.most_common(10)
        lines.append("Mais frequentes em +1:")
        lines.append("  " + " | ".join([f"{n} = {c}x" for n, c in top_plus1]))
    lines.append("")

    # janela +1..+3
    lines.append(f"3) Puxada na janela (+1..+{rep.window})")
    if len(rep.window_counts) == 0:
        lines.append("Nenhuma ocorrência com janela disponível.")
    else:
        top_win = rep.window_counts.most_common(12)
        lines.append("Mais frequentes na janela:")
        lines.append("  " + " | ".join([f"{n} = {c}x" for n, c in top_win]))
    lines.append("")

    # vizinhos racetrack
    n1 = rep.neighbors_by_distance[1]
    n2 = rep.neighbors_by_distance[2]
    lines.append("4) Vizinhança do racetrack (roleta europeia)")
    lines.append(f"±1 do {rep.target}: {n1[0]} e {n1[1]}")
    lines.append(f"±2 do {rep.target}: {n2[0]} e {n2[1]}")
    total_hits = rep.neighbor_hits_by_distance[1] + rep.neighbor_hits_by_distance[2]
    total_slots = len(rep.occurrences) * rep.window
    lines.append(f"Acertos de vizinho dentro da janela: {total_hits} em {total_slots} posições observadas")
    lines.append(f"  hits(±1) = {rep.neighbor_hits_by_distance[1]} | hits(±2) = {rep.neighbor_hits_by_distance[2]}")
    lines.append("")

    # terminais
    lines.append("5) Terminais na janela (+1..+3)")
    if len(rep.terminal_counts) == 0:
        lines.append("Sem terminais (janela vazia).")
    else:
        top_term = rep.terminal_counts.most_common()
        lines.append("Frequência por terminal:")
        lines.append("  " + " | ".join([f"t{t} = {c}x" for t, c in top_term]))
    lines.append("")

    # resumo curto
    if len(rep.window_counts) > 0:
        a, _ = rep.window_counts.most_common(1)[0]
        b = rep.window_counts.most_common(2)[1][0] if len(rep.window_counts) >= 2 else None
        c = rep.window_counts.most_common(3)[2][0] if len(rep.window_counts) >= 3 else None
        lines.append("RESUMO (núcleo puxado pela janela):")
        core = [a] + ([b] if b is not None else []) + ([c] if c is not None else [])
        lines.append("  " + " · ".join(str(x) for x in core))

    return "\n".join(lines)


def build_prediction_from_history(
    history_seq: List[int],
    target: int,
    window: int,
    top_window: int,
    top_plus1: int,
) -> Tuple[List[int], Counter, Counter]:
    """
    Monta a sugestao usando:
    - top_window da janela (+1..+window)
    - top_plus1 do +1 direto
    """
    plus1 = Counter()
    win = Counter()

    for i, n in enumerate(history_seq):
        if n != target:
            continue
        after = history_seq[i + 1:i + 1 + window]
        if after:
            plus1[after[0]] += 1
        for x in after:
            win[x] += 1

    suggestion: List[int] = []
    for n, _ in win.most_common(top_window):
        if n not in suggestion:
            suggestion.append(n)
    for n, _ in plus1.most_common(top_plus1):
        if n not in suggestion:
            suggestion.append(n)

    return suggestion, win, plus1


def simulate_accuracy(
    nums_top_is_recent: List[int],
    limit: int = 500,
    window: int = 3,
    top_window: int = 12,
    top_plus1: int = 3,
) -> SimulationResult:
    """
    Simula previsoes:
    - Usa o numero atual como gatilho
    - Sugestao = top_window da janela + top_plus1 do +1
    - Win se algum dos proximos 'window' numeros estiver na sugestao
    """
    seq = to_chronological(nums_top_is_recent)
    if limit and len(seq) > limit:
        seq = seq[-limit:]

    wins = 0
    losses = 0
    total = 0
    total_hits = 0

    for i in range(len(seq) - window):
        target = seq[i]
        history_seq = seq[:i]
        if not history_seq:
            continue
        suggestion, _, _ = build_prediction_from_history(
            history_seq,
            target=target,
            window=window,
            top_window=top_window,
            top_plus1=top_plus1,
        )
        if not suggestion:
            continue

        next_nums = seq[i + 1:i + 1 + window]
        hits = sum(1 for n in next_nums if n in suggestion)
        total_hits += hits
        total += 1
        if hits > 0:
            wins += 1
        else:
            losses += 1

    win_rate = (wins / total * 100) if total else 0.0
    return SimulationResult(
        total_predictions=total,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        total_hits=total_hits,
    )


def simulate_accuracy_stride(
    nums_top_is_recent: List[int],
    limit: int = 500,
    window: int = 3,
    top_window: int = 12,
    top_plus1: int = 3,
) -> SimulationResult:
    """
    Simula previsoes a cada 'window' numeros:
    - Usa o ultimo numero do bloco como gatilho
    - Sugestao = top_window da janela + top_plus1 do +1
    - Win se algum dos proximos 'window' numeros estiver na sugestao
    """
    seq = to_chronological(nums_top_is_recent)
    if limit and len(seq) > limit:
        seq = seq[-limit:]

    wins = 0
    losses = 0
    total = 0
    total_hits = 0

    block = window
    for i in range(0, len(seq) - (block * 2), block):
        history_end = i + block - 1
        target = seq[history_end]
        history_seq = seq[:history_end]
        if not history_seq:
            continue
        suggestion, _, _ = build_prediction_from_history(
            history_seq,
            target=target,
            window=window,
            top_window=top_window,
            top_plus1=top_plus1,
        )
        if not suggestion:
            continue
        next_nums = seq[history_end + 1:history_end + 1 + window]
        if len(next_nums) < window:
            break
        hits = sum(1 for n in next_nums if n in suggestion)
        total_hits += hits
        total += 1
        if hits > 0:
            wins += 1
        else:
            losses += 1

    win_rate = (wins / total * 100) if total else 0.0
    return SimulationResult(
        total_predictions=total,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        total_hits=total_hits,
    )


def watch_redis_predictions() -> None:
    """
    Escuta o canal new_result e recalcula o placar a cada 3 numeros.
    """
    redis_url = os.getenv("REDIS_CONNECT")
    if not redis_url:
        print("Defina REDIS_CONNECT antes de executar.")
        return

    slug = input("Slug da roleta: ").strip()
    if not slug:
        print("Slug vazio. Saindo.")
        return

    r = redis.from_url(redis_url, decode_responses=True)
    pubsub = r.pubsub()
    pubsub.subscribe("new_result")

    numbers: List[int] = []
    window = 3
    wins = 0
    losses = 0
    total_hits = 0
    total_predictions = 0
    current_suggestion: List[int] = []
    current_confidence: str | None = None
    current_base: int | None = None
    confidence_stats = {
        "alta": {"wins": 0, "losses": 0, "hits": 0, "total": 0},
        "media": {"wins": 0, "losses": 0, "hits": 0, "total": 0},
        "baixa": {"wins": 0, "losses": 0, "hits": 0, "total": 0},
    }
    pending_hits: List[int] = []

    base_url = os.getenv("BASE_URL_API", "https://api.revesbot.com.br")
    history_url = f"{base_url}/history/{slug}?limit=500"

    try:
        with urllib.request.urlopen(history_url, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            numbers = payload.get("results", [])
    except Exception as exc:
        print(f"Falha ao buscar historico inicial: {exc}")
        numbers = []

    if numbers:
        print(f"Historico inicial carregado: {len(numbers)} numeros")
    else:
        print("Historico inicial vazio; aguardando numeros no Redis.")

    print(f"Monitorando {slug} no canal new_result...")

    try:
        for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                data = json.loads(message.get("data", "{}"))
            except json.JSONDecodeError:
                continue

            if data.get("slug") != slug:
                continue

            result = data.get("result")

            if result is None:
                continue

            try:
                num = int(result)
            except (TypeError, ValueError):
                continue

            numbers.insert(0, num)
            if len(numbers) > 2000:
                numbers = numbers[:2000]

            # Se ja existe sugestao ativa, acumula os proximos 3 numeros
            if current_suggestion:
                pending_hits.append(num)
                if len(pending_hits) >= window:
                    hits = sum(1 for n in pending_hits[:window] if n in current_suggestion)
                    total_hits += hits
                    total_predictions += 1
                    if hits > 0:
                        wins += 1
                    else:
                        losses += 1
                    if current_confidence in confidence_stats:
                        bucket = confidence_stats[current_confidence]
                        bucket["hits"] += hits
                        bucket["total"] += 1
                        if hits > 0:
                            bucket["wins"] += 1
                        else:
                            bucket["losses"] += 1

                    last_three = pending_hits[:window]
                    win_rate = (wins / total_predictions * 100) if total_predictions else 0.0
                    print(
                        "Placar: "
                        f"{wins}/{losses} | "
                        f"Win% {win_rate:.2f}% | "
                        f"Hits {total_hits} | "
                        f"Ultimos 3: {', '.join(map(str, last_three))}"
                    )
                    if current_confidence in confidence_stats:
                        bucket = confidence_stats[current_confidence]
                        bucket_rate = (bucket["wins"] / bucket["total"] * 100) if bucket["total"] else 0.0
                        print(
                            f"  Conf ({current_confidence}) "
                            f"W/L {bucket['wins']}/{bucket['losses']} | "
                            f"Win% {bucket_rate:.2f}% | Hits {bucket['hits']}"
                        )

                    pending_hits = []
                    current_suggestion = []
                    current_confidence = None
                    current_base = None

            # Gera uma nova sugestao imediatamente ao receber um numero
            if not current_suggestion:
                seq = to_chronological(numbers)
                if len(seq) < 2:
                    continue
                target = seq[-1]
                history_seq = seq[:-1]
                base_count = history_seq.count(target)
                if base_count >= 12:
                    confidence = "alta"
                elif base_count >= 6:
                    confidence = "media"
                else:
                    confidence = "baixa"
                suggestion, _, _ = build_prediction_from_history(
                    history_seq,
                    target=target,
                    window=window,
                    top_window=12,
                    top_plus1=3,
                )
                if suggestion:
                    current_suggestion = suggestion
                    current_confidence = confidence
                    current_base = target
                    print(
                        f"Sugestao (12+3) para {slug}: {', '.join(map(str, suggestion))}"
                    )
                    print(
                        f"  Base: {current_base} | "
                        f"Ocorrencias no historico: {base_count} | "
                        f"Confianca: {current_confidence}"
                    )
    finally:
        pubsub.close()


def analyze_post_trigger_block(post_numbers: List[int]) -> str:
    """
    Replica o mini-diagnóstico que eu fiz quando você me deu:
    9, 19, 33, 33, 24, 32, 13
    - repetição (travamento)
    - terminais
    - relações de vizinho relevantes (ex.: 33 -> 24 é ±2 do 33)
    """
    lines: List[str] = []
    lines.append("ANÁLISE DO BLOCO 'PÓS-GATILHO' (números após o alvo)")
    lines.append("Sequência: " + " · ".join(map(str, post_numbers)))
    lines.append("")

    # Repetições exatas consecutivas
    reps = []
    for i in range(1, len(post_numbers)):
        if post_numbers[i] == post_numbers[i - 1]:
            reps.append((i - 1, post_numbers[i]))
    if reps:
        lines.append("Repetição exata consecutiva detectada:")
        for idx, val in reps:
            lines.append(f"  posição {idx}->{idx+1}: {val} -> {val}")
    else:
        lines.append("Sem repetição exata consecutiva.")
    lines.append("")

    # Terminais
    terminals = Counter([n % 10 for n in post_numbers])
    lines.append("Terminais no bloco:")
    lines.append("  " + " | ".join([f"t{t} = {c}x" for t, c in terminals.most_common()]))
    lines.append("")

    # Relações de vizinhança entre números consecutivos (distância 1 ou 2 na roda)
    lines.append("Encostos de vizinhança (entre consecutivos, ±1/±2 no racetrack):")
    found = False
    for i in range(1, len(post_numbers)):
        a = post_numbers[i - 1]
        b = post_numbers[i]
        if a in WHEEL_INDEX and b in WHEEL_INDEX:
            neigh_a = racetrack_neighbors(a, k=2)
            if b in neigh_a[1]:
                lines.append(f"  {a} -> {b}  (vizinho ±1 do {a})")
                found = True
            elif b in neigh_a[2]:
                lines.append(f"  {a} -> {b}  (vizinho ±2 do {a})")
                found = True
    if not found:
        lines.append("  (nenhum encosto ±1/±2 entre consecutivos)")
    return "\n".join(lines)


# ---------------------------
# EXEMPLO DE USO
# ---------------------------
if __name__ == "__main__":
    mode = input("Modo (redis/exemplo): ").strip().lower()
    if mode == "redis":
        watch_redis_predictions()
        raise SystemExit(0)

    raw = """
5
3
12
23
2
10
29
14
33
35
31
12
8
10
31
6
33
3
18
15
2
0
9
19
33
33
24
32
13
27
30
32
12
12
4
14
20
29
24
36
1
30
27
29
31
7
25
11
2
2
9
30
31
28
6
10
31
13
1
34
0
16
2
35
20
6
31
9
10
4
4
26
24
17
18
9
26
5
7
35
32
28
34
13
11
12
14
20
35
25
21
24
23
14
34
17
22
33
11
20
24
22
25
1
3
4
20
31
33
9
16
8
33
10
0
26
27
33
3
10
3
10
1
33
33
18
34
1
12
33
20
20
30
0
11
18
22
30
13
21
34
23
20
26
18
31
36
3
0
33
9
9
18
21
27
35
7
17
17
26
2
32
28
15
11
25
11
34
28
33
35
22
27
23
6
21
14
35
2
27
13
36
27
7
29
16
10
6
34
28
36
33
3
7
32
33
29
27
24
25
17
13
24
3
25
0
35
10
5
6
21
2
3
33
20
24
10
19
6
11
5
27
15
10
1
28
33
17
18
22
22
10
23
35
10
34
34
16
26
8
10
30
10
29
8
8
0
10
4
11
16
6
36
13
20
6
5
14
28
26
1
28
24
10
1
21
14
0
22
4
18
2
16
24
18
4
10
22
9
26
1
32
30
18
0
24
14
11
34
14
18
9
12
0
19
1
25
26
32
32
26
9
20
20
1
28
31
0
24
25
20
15
24
5
5
28
36
30
3
31
4
22
2
5
10
10
0
36
13
31
23
4
10
6
26
21
5
2
22
33
12
17
30
18
6
27
10
3
10
8
5
9
9
31
30
16
7
12
33
30
3
0
19
5
15
6
24
35
36
1
10
4
30
4
31
30
10
11
7
15
22
18
34
27
32
17
1
5
19
5
11
13
12
19
17
36
34
29
27
7
25
6
35
36
7
28
9
25
1
36
27
15
14
27
26
11
33
20
35
34
33
23
8
27
5
13
10
25
7
9
9
3
35
18
13
1
33
18
6
7
36
31
21
27
29
34
11
23
27
30
2
21
7
10
31
22
12
4
31
13
4
5
27
34
15
33
36
27
16
11
28
14
8
36
5
16
18
36
20
28
10
9
22
9
36
23
13
2
1
9
32
33
16
31
8
3
24
33
24
14
"""
    nums = parse_numbers(raw)

    # Exatamente como fizemos: "o que o 27 está puxando"
    rep = analyze_target_pull(nums, target=31, window=3)
    print(format_report(rep))

    sim = simulate_accuracy_stride(nums, limit=500, window=3, top_window=12, top_plus1=3)
    print("\nSIMULACAO (500 nums, previsao a cada 3):")
    print(f"Predicoes: {sim.total_predictions} | W/L: {sim.wins}/{sim.losses} | Win%: {sim.win_rate:.2f}% | Hits: {sim.total_hits}")
