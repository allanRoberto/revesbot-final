#!/usr/bin/env python3
"""Legacy entrypoint kept while servers transition to ``main.py``."""

from collector.__main__ import main
from collector.providers.pragmatic import PragmaticCollector

Pragmatic = PragmaticCollector


if __name__ == "__main__":
    main()
