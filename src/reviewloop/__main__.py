"""Backwards-compatible alias — renamed CodeReview in v0.5.0."""

from codereview.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
