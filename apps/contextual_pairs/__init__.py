"""Pair strategy on top of the contextual ranking.

When exactly two of the 7 ranking numbers are from 0 to 9 (the pair), the bet is built from
the terminals, mirror and digit sum of both numbers instead of the 7 suggested numbers.
"""

# Bump when the rule changes: the Redis keys carry it, so the totals start again from zero.
PAIRS_VERSION = 1
STRATEGY = "pairs"
# Stored in every Mongo document (``strategy_version``) and in its ``_id`` prefix.
STRATEGY_TAG = f"{STRATEGY}-{PAIRS_VERSION}"
