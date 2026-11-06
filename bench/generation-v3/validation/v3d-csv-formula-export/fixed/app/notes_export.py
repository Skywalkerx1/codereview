"""CSV export of user-supplied review notes for spreadsheet use.

Contract: cell text is data, never a formula.  Any field whose
first non-space character is one of ``=``, ``+``, ``-`` or ``@``
is neutralised by prefixing a single quote before export, so a
spreadsheet opening the file cannot evaluate it as a formula.
All other fields are exported unchanged.
"""

import csv

FORMULA_PREFIXES = ("=", "+", "-", "@")


def neutralise(field):
    """Prefix formula-leading fields with a single quote."""
    stripped = field.lstrip(" \t")
    if stripped[:1] in FORMULA_PREFIXES:
        return "'" + field
    return field


def export_notes(rows, out):
    """Write ``rows`` (iterables of strings) to file-like ``out``."""
    writer = csv.writer(out)
    for row in rows:
        writer.writerow([neutralise(field) for field in row])
