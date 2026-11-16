"""Pair strategy on top of the contextual ranking.

When exactly two of the 7 ranking numbers are from 0 to 9 (the pair), the bet is built from
the terminals, mirror and digit sum of both numbers instead of the 7 suggested numbers.
"""

# Bump when the rule changes in a way that makes the old results incomparable: the Redis keys
# carry it, so the totals start again from zero.
PAIRS_VERSION = 1
STRATEGY = "pairs"
# Stored in every Mongo document (``strategy_version``) and in its ``_id`` prefix.
STRATEGY_TAG = f"{STRATEGY}-{PAIRS_VERSION}"

# Rule changes made inside version 1 on purpose (the history was kept and corrected by hand,
# see docs/design/pares-similaridade-contextual.md):
#   2026-11-16: the two numbers of the pair are also in the bet, without neighbors, and pair 6-9
#               is ignored (an exception of the strategy).
