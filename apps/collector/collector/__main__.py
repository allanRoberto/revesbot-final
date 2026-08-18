from __future__ import annotations

import logging

from dotenv import load_dotenv

from .adapters.mongo import MongoResultRepository
from .adapters.redis import RedisPublisher
from .config import CollectorSettings
from .health import start_health_server, start_watchdog
from .logging_config import configure_logging
from .maintenance.retention import start_retention_worker
from .providers.pragmatic import PragmaticCollector
from .state import CollectorState


def main() -> None:
    load_dotenv()
    settings = CollectorSettings.from_env()
    configure_logging(settings.log_level)
    logger = logging.getLogger("collector")
    state = CollectorState()
    repository = MongoResultRepository(settings.mongo_url, settings.mongo_database, settings.mongo_collection)
    publisher = RedisPublisher(settings.redis_url, settings.redis_channel)

    repository.ping()
    repository.ensure_indexes()
    state.mongo_ok = True
    publisher.ping()
    state.redis_ok = True
    start_health_server(state, settings)
    start_watchdog(state, settings)
    start_retention_worker(repository, settings.retention_limit_per_table, settings.retention_interval_seconds)

    logger.info(
        "collector_started database=%s collection=%s health=%s:%s tables=%s",
        settings.mongo_database, settings.mongo_collection,
        settings.health_host, settings.health_port, len(settings.subscribe_keys),
    )
    PragmaticCollector(settings, repository, publisher, state).run_forever()


if __name__ == "__main__":
    main()
