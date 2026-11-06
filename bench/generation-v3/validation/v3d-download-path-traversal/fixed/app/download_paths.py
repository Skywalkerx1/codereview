"""Resolving user-requested file names inside the download root.

Contract: downloads are served only from inside the configured
download root.  The requested name is joined to the root and the
fully resolved path must still lie inside the resolved root;
names containing ``..`` segments, or absolute paths, raise
ValueError.  Building the path by plain string concatenation and
serving whatever results would let a requester escape the root
and read arbitrary files (``../`` traversal).
"""

from pathlib import Path


def resolve_download(root, filename):
    """Resolve ``filename`` inside download ``root``.

    Returns the absolute Path to serve.  Raises ValueError if the
    resolved path would escape the root.
    """
    if not filename:
        raise ValueError("filename must not be empty")
    root_path = Path(root).resolve()
    candidate = (root_path / filename).resolve()
    if not candidate.is_relative_to(root_path):
        raise ValueError("filename escapes the download root")
    return candidate


def is_servable(root, filename):
    """Return True iff ``filename`` resolves inside ``root``."""
    try:
        resolve_download(root, filename)
        return True
    except ValueError:
        return False
