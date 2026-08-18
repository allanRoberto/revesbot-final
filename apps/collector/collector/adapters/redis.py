from __future__ import annotations

import redis


class RedisPublisher:
    def __init__(self, url: str, channel: str):
        self.client = redis.from_url(
            url,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
            decode_responses=True,
        )
        self.channel = channel

    def ping(self) -> None:
        self.client.ping()

    def publish(self, payload: str) -> int:
        return int(self.client.publish(self.channel, payload))
