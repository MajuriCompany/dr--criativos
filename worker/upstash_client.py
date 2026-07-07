"""Thin wrapper around the Upstash Redis REST API. No SDK needed — it's just
HTTP, which works identically from this local Python worker and from the
Next.js side (via @upstash/redis on Vercel).
"""
from __future__ import annotations

import requests


class Upstash:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token

    def cmd(self, *parts):
        resp = requests.post(
            self.url,
            headers={"Authorization": f"Bearer {self.token}"},
            json=list(parts),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["result"]

    def get(self, key: str):
        return self.cmd("GET", key)

    def set(self, key: str, value: str):
        return self.cmd("SET", key, value)

    def delete(self, key: str):
        return self.cmd("DEL", key)

    def rpush(self, key: str, value: str):
        return self.cmd("RPUSH", key, value)

    def lpush(self, key: str, value: str):
        return self.cmd("LPUSH", key, value)

    def ltrim(self, key: str, start: int, stop: int):
        return self.cmd("LTRIM", key, start, stop)

    def lrange(self, key: str, start: int, stop: int):
        return self.cmd("LRANGE", key, start, stop) or []

    def lrem(self, key: str, count: int, value: str):
        return self.cmd("LREM", key, count, value)

    def lmove(self, source: str, destination: str, source_side: str = "LEFT", dest_side: str = "RIGHT"):
        """Atomically pop from `source` and push to `destination`. This is the
        primitive that makes job claiming race-free: only one caller can ever
        pop a given ID off the queue, so two worker processes can never claim
        the same job."""
        return self.cmd("LMOVE", source, destination, source_side, dest_side)
