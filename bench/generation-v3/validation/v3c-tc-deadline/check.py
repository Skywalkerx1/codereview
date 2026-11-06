import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/deadline.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

now = [100.0]
dl = mod.Deadline(10.0, clock=lambda: now[0])
assert dl.remaining() == 10.0 and dl.expired() is False
now[0] = 109.5
assert dl.remaining() == 0.5 and dl.expired() is False
now[0] = 110.0  # exactly at the deadline: flips
assert dl.expired() is True and dl.remaining() == 0.0
now[0] = 999.0  # remaining never goes negative
assert dl.remaining() == 0.0 and dl.expired() is True
try:
    dl.raise_if_expired(); assert False
except mod.DeadlineExceeded:
    pass
# Zero duration is already expired; negative is rejected
assert mod.Deadline(0.0, clock=lambda: 5.0).expired() is True
try:
    mod.Deadline(-1.0, clock=lambda: 5.0); assert False
except ValueError:
    pass
# run_chunks: all chunks run while time remains, results in order
now2 = [0.0]
dl2 = mod.Deadline(10.0, clock=lambda: now2[0])
def step(v, advance):
    def run():
        now2[0] += advance
        return v
    return run
assert mod.run_chunks([step("a", 3), step("b", 3)], dl2) == ["a", "b"]
# A chunk that would start after expiry never runs
ran = []
dl3 = mod.Deadline(5.0, clock=lambda: now2[0])  # now2=6 -> ends at 11
def first():
    now2[0] = 20.0; ran.append("first"); return 1
def second():
    ran.append("second"); return 2
try:
    mod.run_chunks([first, second], dl3); assert False
except mod.DeadlineExceeded:
    pass
assert ran == ["first"]  # second was checked and skipped
# Empty chunk list returns empty, even on an expired deadline is an error-free no-op check order: no chunks, no check
assert mod.run_chunks([], dl3) == []
print("ok")
