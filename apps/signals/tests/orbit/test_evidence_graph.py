from shared.python.roulette.orbit.evidence_graph import EvidenceGraph, EvidenceGraphConfig
from shared.python.roulette.orbit.orbit_builder import OrbitBuilder


def test_overlapping_windows_do_not_duplicate_same_evidence_key():
    # Pivos proximos fazem o mesmo giro aparecer em mais de uma janela.
    history = [4, 5, 19, 14, 19, 13, 31, 19]
    context = OrbitBuilder(pre_window=5, post_window=5, memory_occurrences=8).build_context(
        history,
        len(history) - 1,
    )
    graph = EvidenceGraph(EvidenceGraphConfig(max_hops=1))
    evidence = graph.build(context)
    for candidate_rows in evidence.values():
        keys = {
            (row.source_spin_index, row.candidate, row.relation_type, row.path)
            for row in candidate_rows
        }
        assert len(keys) == len(candidate_rows)


def test_example_relations_reinforce_14():
    # Antes do pivo: 32,27,13,5,31. Todos os indices sao conhecidos.
    history = [32, 27, 13, 5, 31, 19]
    context = OrbitBuilder(pre_window=5, post_window=5).build_context(history, 5)
    evidence = EvidenceGraph().build(context)[14]
    paths = {row.path for row in evidence}
    relations = {row.relation_type for row in evidence}
    assert (13, 14) in paths
    assert (32, 14) in paths
    assert (5, 14) in paths
    assert "numeric_sequence" in relations
    assert "digit_sum" in relations
