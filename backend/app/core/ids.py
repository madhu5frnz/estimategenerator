from __future__ import annotations

import secrets
import time
import uuid


def new_id() -> uuid.UUID:
    """UUIDv7 (RFC 9562): time-ordered, so new rows append to the end of B-tree indexes."""
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(secrets.token_bytes(10), "big")
    rand_a = rand >> 68  # 12 bits
    rand_b = rand & ((1 << 62) - 1)  # 62 bits
    value = (unix_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76 | rand_a << 64 | 0b10 << 62 | rand_b
    return uuid.UUID(int=value)
