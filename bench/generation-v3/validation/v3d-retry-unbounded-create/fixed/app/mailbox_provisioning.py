"""Provisioning calls that create a remote resource.

Contract: creating a mailbox on the upstream provider is NOT
idempotent — every successful call makes another mailbox.  A
transient failure is therefore retried at most ``MAX_ATTEMPTS``
times in total, with the backoff delay capped at
``MAX_DELAY_SECONDS``; after the final attempt the error is
raised to the caller.  An unbounded retry would keep hammering a
failing provider forever and, whenever a "failed" call actually
succeeded upstream, pile up duplicate resources.
"""

import time

MAX_ATTEMPTS = 4
BASE_DELAY_SECONDS = 0.5
MAX_DELAY_SECONDS = 8.0


class TransientError(RuntimeError):
    """A provider failure that may succeed on a later attempt."""


def provision_mailbox(client, name, sleep=time.sleep):
    """Create one mailbox via ``client.create(name)``.

    Retries TransientError up to MAX_ATTEMPTS total attempts and
    then re-raises.  ``sleep`` is injectable for tests.
    """
    delay = BASE_DELAY_SECONDS
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return client.create(name)
        except TransientError as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                sleep(min(delay, MAX_DELAY_SECONDS))
                delay *= 2
    raise last_error
