"""Card charges with idempotency protection for the checkout API.

Contract: the idempotency record for a charge key is written to
the store BEFORE the gateway is called.  A charge request can
fail after the gateway has taken the money (connection lost while
reading the response); when the client retries with the same key,
the pre-written record is what stops a second charge.  Retrying a
key that already has a record returns that record and never calls
the gateway again.
"""


class ChargeError(RuntimeError):
    """The gateway call did not complete cleanly."""


def process_charge(store, gateway, key, amount_cents):
    """Charge ``amount_cents`` once for idempotency ``key``.

    ``store`` is a mutable mapping of charge records, ``gateway``
    exposes ``charge(amount_cents) -> receipt_id``.  Returns the
    stored record dict.
    """
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    existing = store.get(key)
    if existing is not None:
        return existing
    record = {"key": key, "amount_cents": amount_cents,
              "status": "pending", "receipt": None}
    store[key] = record
    receipt = gateway.charge(amount_cents)
    record["receipt"] = receipt
    record["status"] = "completed"
    return record
