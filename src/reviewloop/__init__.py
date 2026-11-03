"""Backwards-compatible alias — ReviewLoop was renamed CodeReview
in v0.5.0. New code should import `codereview`."""

from codereview import *  # noqa: F401,F403
from codereview import cli, core, github, providers  # noqa: F401
from codereview import VERSION, __version__  # noqa: F401
