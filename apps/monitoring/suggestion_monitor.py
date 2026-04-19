#!/usr/bin/env python3
import asyncio
import logging

from src.suggestion_monitor_worker import main as suggestion_monitor_main


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(suggestion_monitor_main())
