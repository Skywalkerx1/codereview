"""Behavioural check for v3r-statistics-inf-nan-stdev.

Pre-fix behaviour: stdev() and pstdev() read mss.numerator
directly to take the square root.  With an infinite or NaN input
the mean square is a float, which has no .numerator, so the call
failed with AttributeError ('float' object has no attribute
'numerator') instead of a meaningful error about the data.
"""

import importlib.util
import math
import pathlib

spec = importlib.util.spec_from_file_location(
    "spread", pathlib.Path("app/spread.py"))
spread = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spread)

# Finite data: exact, independently known values.
assert spread.stdev([1, 2, 3, 4, 5]) == math.sqrt(2.5)
assert spread.pstdev([1, 2, 3, 4, 5]) == math.sqrt(2.0)
assert spread.stdev([1, 2, 3]) == 1.0
assert spread.pstdev([7]) == 0.0
assert spread.stdev([1.5, 2.5]) == math.sqrt(0.5)
assert spread.stdev([1, 2, 3], xbar=2) == 1.0
assert spread.pstdev([2, 4, 4, 4, 5, 5, 7, 9], mu=5) == 2.0

# The upstream regression test (gh-140938): inf and NaN inputs
# raise ValueError naming the cause, in either position.
for func in (spread.stdev, spread.pstdev):
    for bad_data in ([1.0, math.inf], [1.0, math.nan],
                     [math.inf, 1.0, 2.0], [1.0, 2.0, math.nan]):
        try:
            func(bad_data)
        except ValueError as exc:
            assert "inf or nan" in str(exc), exc
        else:
            raise AssertionError(
                "%s(%r) did not raise" % (func.__name__, bad_data))

# Too few data points still raise StatisticsError.
for func, data in ((spread.stdev, [1]), (spread.pstdev, [])):
    try:
        func(data)
    except spread.StatisticsError:
        pass
    else:
        raise AssertionError("%s(%r) did not raise StatisticsError"
                             % (func.__name__, data))

print("v3r-statistics-inf-nan-stdev: OK")
