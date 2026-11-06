"""Keyset pagination over the activity feed.

Contract: rows are ordered by ``(created_at, id)``.  Many rows can
share one ``created_at`` timestamp, so the pagination cursor
encodes BOTH the last row's ``created_at`` and its ``id``, and the
next page resumes strictly after that pair.  Walking all pages
must yield every row exactly once — no duplicates and no skipped
rows, however many timestamps tie.
"""


def encode_cursor(row):
    """Encode the position after ``row`` as an opaque string."""
    return f"{row['created_at']}|{row['id']}"


def paginate(rows, page_size, cursor=None):
    """Return ``(page, next_cursor)`` for the feed.

    ``next_cursor`` is None when the page is the last one.
    """
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["id"]))
    if cursor is not None:
        cur_ts, cur_id = cursor.rsplit("|", 1)
        ordered = [
            r for r in ordered
            if (r["created_at"], r["id"]) > (cur_ts, int(cur_id))
        ]
    page = ordered[:page_size]
    next_cursor = encode_cursor(page[-1]) if len(ordered) > page_size else None
    return page, next_cursor
