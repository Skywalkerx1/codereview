"""Sales-tax calculation for the invoicing module.

Contract: the tax on a subtotal is subtotal * rate, quantised to
whole cents with ROUND_HALF_UP — the rounding mode stated in the
customer terms and used by the accounting export.  A half-cent
tax always rounds UP (0.125 -> 0.13).  The Decimal context
default (ROUND_HALF_EVEN, bankers rounding) must not leak in:
it rounds some half-cents down and disagrees with the ledger.
"""

from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def tax_amount(subtotal, rate):
    """Return the tax owed on ``subtotal`` at fractional ``rate``.

    Both arguments are decimal strings, e.g. tax_amount("2.50",
    "0.05").  The result is a Decimal quantised to cents.
    """
    raw = Decimal(subtotal) * Decimal(rate)
    return raw.quantize(CENT, rounding=ROUND_HALF_UP)


def total_with_tax(subtotal, rate):
    """Return subtotal plus its tax, as a Decimal in cents."""
    return Decimal(subtotal) + tax_amount(subtotal, rate)
