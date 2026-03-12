def process_roulette(roulette, results: list[int], min_gap: int = 12) -> list[dict]:
    """
    Detecta padrões:
        - 0, X ... 0, X
        - X, 0 ... X, 0
    Onde X é o mesmo número, com pelo menos min_gap entre as ocorrências
    e sem nenhum outro zero no intervalo.

    Retorna uma lista de dicionários com:
        - tipo: '0>X' ou 'X>0'
        - x: número puxado
        - index1: índice da 1ª ocorrência
        - index2: índice da 2ª ocorrência
    """
    matches = []

    for i in range(len(results) - 1):
        # padrão 0 > X
        if results[i] == 0:
            x = results[i + 1]
            for j in range(i + min_gap + 1, len(results) - 1):
                if results[j] == 0 and results[j + 1] == x:
                    # verifica se não tem outro zero entre i+2 e j-1
                    if 0 not in results[i + 2:j]:
                        matches.append({
                            "tipo": "0>X",
                            "x": x,
                            "index1": i,
                            "index2": j
                        })
                    break

        # padrão X > 0
        elif results[i + 1] == 0:
            x = results[i]
            for j in range(i + min_gap + 1, len(results) - 1):
                if results[j] == x and results[j + 1] == 0:
                    if 0 not in results[i + 2:j]:  # verifica se não tem outro zero no meio
                        matches.append({
                            "tipo": "X>0",
                            "x": x,
                            "index1": i,
                            "index2": j
                        })
                    break

    print(f"https://gamblingcounting.com/{roulette['slug']}")
    print(matches)
