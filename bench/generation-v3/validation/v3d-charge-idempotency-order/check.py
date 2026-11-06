import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/charge_service.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class FlakyGateway:
    """Charges successfully, then loses the first response."""
    def __init__(self):
        self.charges = 0
    def charge(self, amount_cents):
        self.charges += 1
        if self.charges == 1:
            raise mod.ChargeError("response lost after charging")
        return "receipt-2"

store = {}
gateway = FlakyGateway()
try:
    mod.process_charge(store, gateway, "order-77", 4200)
    raise AssertionError("first attempt should propagate the error")
except mod.ChargeError:
    pass
record = mod.process_charge(store, gateway, "order-77", 4200)
assert gateway.charges == 1, f"charged {gateway.charges} times"
assert record["status"] in ("pending", "completed")

# A clean first charge completes and is not repeated on retry.
class GoodGateway:
    def __init__(self): self.charges = 0
    def charge(self, amount_cents):
        self.charges += 1
        return "receipt-1"
store2, gw2 = {}, GoodGateway()
rec = mod.process_charge(store2, gw2, "order-78", 1000)
assert rec["status"] == "completed" and rec["receipt"] == "receipt-1"
again = mod.process_charge(store2, gw2, "order-78", 1000)
assert gw2.charges == 1 and again is rec
print("ok")
