"""Behavioural check for v3r-robotparser-decimal-digits.

Pre-fix behaviour: the guards used str.isdigit().  A value such
as '²' (U+00B2 SUPERSCRIPT TWO) passes isdigit() but int()
rejects it, so a robots.txt containing 'Crawl-delay: ²' raised
ValueError and aborted parsing of the whole file, access rules
included.  (Upstream gh-153404.)
"""

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "robotdelays", pathlib.Path("app/robotdelays.py"))
robotdelays = importlib.util.module_from_spec(spec)
spec.loader.exec_module(robotdelays)

SUPERSCRIPT_TWO = "²"      # isdigit() True, isdecimal() False
ARABIC_INDIC_FIVE = "٥"    # isdecimal() True, int() == 5

# The upstream NonDecimalDigitsTest: parsing must not raise, and
# both directives are ignored.
parser = robotdelays.RobotDelays()
parser.parse(['User-Agent: *',
              'Disallow: /tmp/',
              'Crawl-delay: ' + SUPERSCRIPT_TWO,
              'Request-rate: ' + SUPERSCRIPT_TWO + '/5'])
assert parser.crawl_delay('*') is None
assert parser.request_rate('*') is None

# The upstream NonDecimalDenominatorTest.
parser = robotdelays.RobotDelays()
parser.parse(['User-agent: *',
              'Disallow: /tmp/',
              'Request-rate: 5/' + SUPERSCRIPT_TWO])
assert parser.request_rate('*') is None

# A bad value does not abort the rest of the group either.
parser = robotdelays.RobotDelays()
parser.parse(['User-agent: *',
              'Crawl-delay: ' + SUPERSCRIPT_TWO,
              'Request-rate: 2/3'])
assert parser.crawl_delay('*') is None
assert parser.request_rate('*') == robotdelays.RequestRate(2, 3)

# Ordinary decimal values parse as before.
parser = robotdelays.RobotDelays()
parser.parse(['User-agent: *', 'Crawl-delay: 10', 'Request-rate: 1/5'])
assert parser.crawl_delay('*') == 10
rate = parser.request_rate('*')
assert rate == robotdelays.RequestRate(1, 5)
assert rate.requests == 1 and rate.seconds == 5

# Non-ASCII *decimal* digits are still accepted, matching int():
# isdecimal() is exactly the predicate int() can handle.
parser = robotdelays.RobotDelays()
parser.parse(['User-agent: *', 'Crawl-delay: ' + ARABIC_INDIC_FIVE])
assert parser.crawl_delay('*') == 5

print("v3r-robotparser-decimal-digits: OK")
