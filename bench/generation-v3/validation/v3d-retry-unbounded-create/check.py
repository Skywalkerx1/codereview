import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/mailbox_provisioning.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class StopLoop(BaseException):
    """Sentinel the retry loop must not swallow."""

class AlwaysDown:
    def __init__(self): self.calls = 0
    def create(self, name):
        self.calls += 1
        if self.calls > 12:
            raise StopLoop()
        raise mod.TransientError("provider down")

client = AlwaysDown()
try:
    mod.provision_mailbox(client, "team", sleep=lambda s: None)
    raise AssertionError("persistent failure should raise")
except mod.TransientError:
    pass
assert client.calls == mod.MAX_ATTEMPTS, client.calls

class Flaky:
    def __init__(self): self.calls = 0
    def create(self, name):
        self.calls += 1
        if self.calls < 3:
            raise mod.TransientError("try again")
        return "mailbox-1"
flaky = Flaky()
assert mod.provision_mailbox(flaky, "team", sleep=lambda s: None) == "mailbox-1"
assert flaky.calls == 3
delays = []
class Down3:
    def __init__(self): self.calls = 0
    def create(self, name):
        self.calls += 1
        raise mod.TransientError("down")
try:
    mod.provision_mailbox(Down3(), "x", sleep=delays.append)
except mod.TransientError:
    pass
assert all(d <= mod.MAX_DELAY_SECONDS for d in delays), delays
print("ok")
