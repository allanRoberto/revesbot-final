# utils/graceful.py
import asyncio
import signal
from contextlib import suppress

def setup_graceful_shutdown(loop: asyncio.AbstractEventLoop):
    stop_event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    async def shutdown():
        await stop_event.wait()          # bloqueia até Ctrl+C
        tasks = [t for t in asyncio.all_tasks(loop) if t is not
                 asyncio.current_task(loop)]
        for t in tasks:
            t.cancel()
        # aguarda tasks cancelarem (ignora CancelledError)
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)

    loop.create_task(shutdown())
