"""codereview — multi-model code review with a deterministic gate."""

from .core import VERSION, run_review, run_verification

__all__ = ["VERSION", "run_review", "run_verification"]
__version__ = VERSION
