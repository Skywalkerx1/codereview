"""Per-user response cache for the account-documents API.

Contract: a cached payload belongs to exactly one user.  The
cache key is built from BOTH the caller's user id and the
resource id, so two users requesting the same resource id can
never be served each other's payload — document payloads contain
private account data and cross-user disclosure is a security
incident, not a cache miss.
"""


def cache_key(user_id, resource_id):
    """Return the cache key for one user's view of a resource."""
    return f"user:{user_id}:resource:{resource_id}"


def get_document(cache, user_id, resource_id, loader):
    """Return the document for ``user_id``/``resource_id``.

    ``cache`` is a mutable mapping; ``loader(user_id, resource_id)``
    fetches the authoritative payload on a miss.  The loader runs
    at most once per (user, resource) pair.
    """
    key = cache_key(user_id, resource_id)
    if key not in cache:
        cache[key] = loader(user_id, resource_id)
    return cache[key]
