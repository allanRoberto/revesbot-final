#!/usr/bin/env python3
import asyncio

from src.signal_listener import main as signal_listener_main


if __name__ == "__main__":
    asyncio.run(signal_listener_main())
