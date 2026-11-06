"""Behavioural check for v3r-logging-adapter-merge-extra.

Pre-fix behaviour: LoggerAdapter.process merged whenever the
'extra' key was present in kwargs and merge_extra was set,
unpacking both dicts unconditionally.  With merge_extra=True, an
adapter created without extra crashed with TypeError ('NoneType'
object is not a mapping) as soon as a call did pass extra, and a
call passing extra=None crashed the same way when the adapter
did have an extra dict.  (Upstream gh-138162.)
"""

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "logadapter", pathlib.Path("app/logadapter.py"))
logadapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logadapter)


class FakeLogger:
    def __init__(self):
        self.calls = []

    def log(self, level, msg, *args, **kwargs):
        self.calls.append((level, msg, kwargs))


logger = FakeLogger()

# Adapter WITH extra, merge_extra=True (upstream test_extra_merged).
adapter = logadapter.LoggerAdapter(
    logger, extra={'foo': '1'}, merge_extra=True)
adapter.critical('with extra', extra={'bar': '2'})
assert logger.calls[-1][2]['extra'] == {'foo': '1', 'bar': '2'}
adapter.critical('no extra')  # must not fail
assert logger.calls[-1][2]['extra'] == {'foo': '1'}
adapter.critical('none extra', extra=None)  # must not fail
assert logger.calls[-1][2]['extra'] == {'foo': '1'}

# Per-call keys win on conflict (upstream precedence test).
adapter.critical('conflict', extra={'foo': '2'})
assert logger.calls[-1][2]['extra'] == {'foo': '2'}

# Adapter WITHOUT extra, merge_extra=True (the new upstream test
# test_extra_merged_without_extra): every call shape works.
bare = logadapter.LoggerAdapter(logger, merge_extra=True)
bare.critical('call extra', extra={'foo': '1'})
assert logger.calls[-1][2]['extra'] == {'foo': '1'}
bare.critical('no extra')  # must not fail
assert logger.calls[-1][2]['extra'] is None
bare.critical('none extra', extra=None)  # must not fail
assert logger.calls[-1][2]['extra'] is None

# merge_extra=False keeps the classic behaviour: the adapter's
# extra replaces any per-call extra.
plain = logadapter.LoggerAdapter(logger, extra={'foo': '1'})
plain.critical('ignored extra', extra={'bar': '2'})
assert logger.calls[-1][2]['extra'] == {'foo': '1'}

# process() returns the (msg, kwargs) pair unchanged in shape.
msg, kwargs = adapter.process('hello', {})
assert msg == 'hello' and kwargs == {'extra': {'foo': '1'}}

print("v3r-logging-adapter-merge-extra: OK")
