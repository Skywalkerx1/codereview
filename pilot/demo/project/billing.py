"""Tiny billing module for a small shop's checkout."""

import time


class GatewayError(Exception):
    """The payment gateway rejected or failed a charge."""


def dollars_to_cents(dollars):
    """Convert a dollar amount to integer cents."""
    return int(round(dollars * 100))


class Order:
    def __init__(self, total_dollars):
        self.total_dollars = total_dollars


def charge_order(gateway, order):
    """Charge an order through the payment gateway.

    The gateway API expects ``amount_cents``: an integer number
    of cents (so $49.99 is passed as 4999).
    """
    amount_cents = dollars_to_cents(order.total_dollars)
    return gateway.charge(amount_cents=amount_cents, currency="usd")
