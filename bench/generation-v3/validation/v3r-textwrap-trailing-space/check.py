"""Behavioural check for v3r-textwrap-trailing-space.

Pre-fix behaviour: when the current line, including its trailing
space chunk, was exactly `width` long and the next chunk was a
word longer than a line, _handle_long_word appended chunk[:0]
(the empty string) to the line.  The drop-whitespace cleanup then
removed that empty chunk instead of the space chunk, so the
emitted line kept its trailing space: wrapping the text below at
width 12 produced 'Did you say ' (with a trailing space) as the
first line.
"""

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "wraptext", pathlib.Path("app/wraptext.py"))
wraptext = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wraptext)

TEXT = 'Did you say "supercalifragilisticexpialidocious?'

# The upstream regression case (gh-139065): no trailing space,
# and the long word is broken starting on the next line.
lines = wraptext.TextWrapper(width=12).wrap(TEXT)
assert lines == ['Did you say', '"supercalifr',
                 'agilisticexp', 'ialidocious?'], lines
assert all(line == line.rstrip() for line in lines)

# With a closing quote the same holds, and the quote survives.
lines = wraptext.TextWrapper(width=12).wrap(TEXT + '"')
assert lines == ['Did you say', '"supercalifr', 'agilisticexp',
                 'ialidocious?', '"'], lines
assert all(line == line.rstrip() for line in lines)

# Unbreakable long words still move whole to their own line.
lines = wraptext.TextWrapper(width=12, break_long_words=False).wrap(TEXT)
assert lines == ['Did you say',
                 '"supercalifragilisticexpialidocious?'], lines

# Ordinary wrapping is unaffected.
lines = wraptext.TextWrapper(width=20).wrap(
    'The quick brown fox jumps over')
assert lines == ['The quick brown fox', 'jumps over'], lines
assert all(len(line) <= 20 for line in lines)

print("v3r-textwrap-trailing-space: OK")
