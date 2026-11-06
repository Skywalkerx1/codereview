import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/token_expiry.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
expired = now - timedelta(hours=1)
still_valid = now + timedelta(hours=2)
# An expiry one hour in the past (UTC) must be rejected.
assert mod.token_is_valid(expired) is False
# An expiry two hours ahead must be accepted.
assert mod.token_is_valid(still_valid) is True
# Injected-clock behaviour is exact.
assert mod.token_is_valid(still_valid, now=now) is True
assert mod.token_is_valid(expired, now=now) is False
# Naive expiries are rejected as programming errors.
try:
    mod.token_is_valid(datetime(2030, 1, 1))
    raise AssertionError("naive expiry accepted")
except ValueError:
    pass
print("ok")
