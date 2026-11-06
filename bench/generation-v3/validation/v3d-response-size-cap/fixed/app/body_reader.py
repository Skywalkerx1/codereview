"""Bounded download of an upstream response body.

Contract: upstream bodies are untrusted and unbounded.  Bodies
are read in chunks and the read aborts with ValueError as soon as
the accumulated size exceeds ``max_bytes``; a body of exactly
``max_bytes`` is accepted.  The whole stream must never be pulled
into memory in a single unbounded read — a hostile or broken
upstream could otherwise exhaust the worker's memory and take
down the worker for every other tenant sharing it.  Callers rely
on the ValueError to answer 502 and log the upstream as faulty.
"""

DEFAULT_MAX_BYTES = 1_048_576
CHUNK_SIZE = 65_536


def read_body(stream, max_bytes=DEFAULT_MAX_BYTES):
    """Read ``stream`` to EOF, enforcing the ``max_bytes`` cap.

    Returns the body bytes.  Raises ValueError if the body is
    larger than ``max_bytes``.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    chunks = []
    total = 0
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"body exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)
