"""Behavioural check for v3r-robotparser-normalize-urls.

Pre-fix behaviour: parse() percent-decoded rule paths once with
unquote(), and can_fetch() percent-decoded the whole URL and
re-encoded it with quote() after urlparse/urlunparse had split
the query off.  A trailing '?' was lost in that round trip, and a
percent-encoded '%3F' in a path was turned into a real '?'
(likewise '%3D' and '%26' became query syntax), so rules matched
the wrong URLs: a rule for '/another/path?' also blocked
'/another/path' and '/another/path?name=value', and a rule for
'/some/path?name=value' did not match reliably either.
"""

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "robotrules", pathlib.Path("app/robotrules.py"))
robotrules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(robotrules)

# Unit level: the trailing '?' survives normalisation, and an
# encoded '?' is not a query delimiter.
assert robotrules.normalize_path('/another/path?') == '/another/path?'
assert robotrules.normalize_path('/x%3Fy') == '/x%3Fy'
assert robotrules.normalize_path('/x?y') == '/x?y'
assert robotrules.normalize_path('/x%3Fy') != robotrules.normalize_path('/x?y')

# The upstream DisallowQueryStringTest cases (gh-111788).
parser = robotrules.RobotRules()
parser.parse([
    'User-agent: *',
    'Disallow: /some/path?name=value',
    'Disallow: /another/path?',
    'Disallow: /yet/one/path?name=value&more',
])
good = ['/some/path', '/some/path?',
        '/some/path%3Fname=value', '/some/path?name%3Dvalue',
        '/another/path', '/another/path%3F',
        '/yet/one/path?name=value%26more']
bad = ['/some/path?name=value',
       '/another/path?', '/another/path?name=value',
       '/yet/one/path?name=value&more']
for url in good:
    assert parser.can_fetch('TestBot', url) is True, url
for url in bad:
    assert parser.can_fetch('TestBot', url) is False, url

# A subset of the upstream PercentEncodingTest cases (gh-88375):
# encoded and raw spellings of the same character are equivalent,
# double-encoding is a different path, and %2F is a path segment
# character, not a separator the rule can be bypassed with.
parser2 = robotrules.RobotRules()
parser2.parse([
    'User-agent: *',
    'Disallow: /a2/%5A%2D%2E%5F%7E',
    'Disallow: /p3%25xy',
    'Disallow: /john%20smith',
    'Disallow: /question%3Fq=v',
    'Disallow: /slash%2F',
])
for url in ['/a2/Z-._~', '/a2/%5A%2D%2E%5F%7E', '/p3%25xy',
            '/john smith', '/john%20smith', '/question%3Fq=v',
            '/slash%2F', '/slash/']:
    assert parser2.can_fetch('TestBot', url) is False, url
for url in ['/p3%2525xy', '/question?q=v', '/a2/other']:
    assert parser2.can_fetch('TestBot', url) is True, url

# Full URLs are reduced to path plus query before matching.
assert parser.can_fetch(
    'TestBot', 'http://example.com/some/path?name=value') is False
assert parser.can_fetch(
    'TestBot', 'http://example.com/some/path') is True

print("v3r-robotparser-normalize-urls: OK")
