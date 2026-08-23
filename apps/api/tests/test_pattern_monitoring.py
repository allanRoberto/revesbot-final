from api.routes.pattern_monitoring import simulate_bankroll


def test_simulation_uses_each_signals_actual_bet_count():
    signals = [
        {
            "status": "won",
            "won_at_attempt": 1,
            "bet_count": 8,
            "payout": 36,
            "roulette_id": "table-a",
        },
        {
            "status": "lost",
            "bet_count": 5,
            "payout": 36,
            "roulette_id": "table-b",
        },
    ]

    result = simulate_bankroll(
        signals,
        starting_bankroll=1000,
        attempt_values=[2.5, 1.5, 1.5, 1.0],
    )

    assert result["wins"] == 1
    assert result["losses"] == 1
    assert result["total_wagered"] == 52.5
    assert result["profit"] == 37.5
    assert result["ending_bankroll"] == 1037.5


def test_simulation_reclassifies_late_win_when_horizon_is_shorter():
    signals = [{"status": "won", "won_at_attempt": 4, "bet_count": 7, "payout": 36}]

    result = simulate_bankroll(
        signals,
        starting_bankroll=1000,
        attempt_values=[2.5, 1.5, 1.5],
    )

    assert result["wins"] == 0
    assert result["losses"] == 1
    assert result["profit"] == -38.5
