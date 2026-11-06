import unittest

from billing import Order, charge_order, dollars_to_cents


class FakeGateway:
    def __init__(self):
        self.calls = []

    def charge(self, amount_cents, currency):
        self.calls.append((amount_cents, currency))
        return {"status": "ok", "amount_cents": amount_cents}


class BillingTests(unittest.TestCase):
    def test_dollars_to_cents(self):
        self.assertEqual(dollars_to_cents(49.99), 4999)
        self.assertEqual(dollars_to_cents(10), 1000)

    def test_charge_order_sends_cents(self):
        gateway = FakeGateway()
        charge_order(gateway, Order(49.99))
        self.assertEqual(gateway.calls, [(4999, "usd")])


if __name__ == "__main__":
    unittest.main()
