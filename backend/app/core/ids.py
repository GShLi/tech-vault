import os
import time
from typing import Optional


_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_ulid(now_ms: Optional[int] = None) -> str:
    timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if timestamp < 0 or timestamp >= (1 << 48):
        raise ValueError("timestamp is outside the ULID range")
    randomness = int.from_bytes(os.urandom(10), "big")
    return _encode(timestamp, 10) + _encode(randomness, 16)


def is_valid_ulid(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 26
        and all(character in _ALPHABET for character in value)
    )
