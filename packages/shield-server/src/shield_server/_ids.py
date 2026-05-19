"""UUIDv7 (RFC 9562) — port of Elydora packages/server/src/utils/uuid.ts.

48-bit Unix-ms timestamp in the high bits => lexicographically sortable ids
(used for server-issued receipt_ids, exactly as Elydora generateUUIDv7()).
"""

from __future__ import annotations

import os
import time


def generate_uuid7() -> str:
    now = int(time.time() * 1000)
    b = bytearray(os.urandom(16))
    b[0] = (now >> 40) & 0xFF
    b[1] = (now >> 32) & 0xFF
    b[2] = (now >> 24) & 0xFF
    b[3] = (now >> 16) & 0xFF
    b[4] = (now >> 8) & 0xFF
    b[5] = now & 0xFF
    b[6] = (b[6] & 0x0F) | 0x70  # version 7
    b[8] = (b[8] & 0x3F) | 0x80  # variant 10xx
    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
