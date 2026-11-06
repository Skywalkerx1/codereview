"""Behavioural check for v3r-numeric-range-slicing.

Pre-fix behaviour: the slice branch of __getitem__ defaulted a
missing slice start/stop to the range's own _start/_stop,
regardless of the step direction.  numeric_range(0, 10, 2)[::-1]
therefore produced an empty range instead of [8, 6, 4, 2, 0],
and the upstream regression case numeric_range(10.0, 0.0, -2.0)
sliced with [::-1] did not yield the reversed range either.
"""

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "numrange", pathlib.Path("app/numrange.py"))
numrange = importlib.util.module_from_spec(spec)
spec.loader.exec_module(numrange)
numeric_range = numrange.numeric_range

# The regression test added by the fix (more-itertools PR #1128):
# reversing a descending float range.
sliced = numeric_range(10.0, 0.0, -2.0)[::-1]
assert (sliced._start, sliced._stop, sliced._step) == (2.0, 12.0, 2.0)
assert list(sliced) == [2.0, 4.0, 6.0, 8.0, 10.0]

# A pre-existing case the fix had to keep passing.
sliced = numeric_range(1.0, 9.0, 1.5)[-10:None:3]
assert sliced._step == 4.5
assert list(sliced) == [1.0, 5.5]

# Integer ranges slice exactly like the built-in range, across
# directions, steps, clamping and empty results.
slices = [slice(None, None, -1), slice(1, 4), slice(None, None, 2),
          slice(-3, None), slice(10, 20), slice(None, None, -3),
          slice(3, 0, -1), slice(None), slice(-100, 100)]
for params in [(0, 10, 2), (5,), (10, 0, -3), (0, 10, 3), (7, 7, 1)]:
    for sl in slices:
        assert list(numeric_range(*params)[sl]) == \
            list(range(*params)[sl]), (params, sl)

# Integer indexing, including negative indices and bounds.
r = numeric_range(0, 10, 2)
assert r[0] == 0 and r[3] == 6 and r[-1] == 8 and len(r) == 5
try:
    r[5]
except IndexError:
    pass
else:
    raise AssertionError("index 5 did not raise IndexError")

print("v3r-numeric-range-slicing: OK")
